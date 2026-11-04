import os
os.environ.setdefault('SD_ENABLE_ASIO','1')
try:
    import sounddevice as sd
except (OSError, ImportError):
    sd = None  # Demo and saved-event review remain usable without an audio driver.
import json, queue, threading, time, uuid
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
import numpy as np
from scipy.io import wavfile
from core import Ring, Detector, demo_block

class Engine(threading.Thread):
    def __init__(self, config, directory):
        super().__init__(daemon=True)
        self.config=config; self.directory=Path(directory)
        self.quit=threading.Event(); self.messages=queue.Queue(maxsize=4096)
        self.latest=None; self.error=''; self.saved=0; self.scheduled=0; self.gaps=0
        self.stream=None; self.audio_queue=queue.Queue(maxsize=128)
        self.callback_gap=threading.Event()
    def prepare_capture(self):
        """Open/start on the main thread, where PortAudio was initialized."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Audio driver startup must run on the main thread.')
        if self.config['demo']: return
        if sd is None: raise RuntimeError('Audio library unavailable. Reinstall requirements and the device driver.')
        if self.stream is not None: raise RuntimeError('Capture is already open.')
        def receive(indata, frames, timing, status):
            # PortAudio callback: no file I/O, FFT, playback or console commands.
            gap=bool(status) or self.callback_gap.is_set()
            try:
                self.audio_queue.put_nowait((indata.copy(),gap))
                self.callback_gap.clear()
            except queue.Full:
                self.callback_gap.set()
        c=self.config
        try:
            self.stream=sd.InputStream(device=c['device'],samplerate=c['rate'],
                channels=c['channels'],dtype='float32',blocksize=1024,callback=receive)
            self.stream.start()
        except Exception:
            self.close_capture()
            raise
    def close_capture(self):
        """Called by the UI after analysis exits, or after startup fails."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Audio driver shutdown must run on the main thread.')
        stream=self.stream
        if stream is None: return
        try:
            try: stream.stop()
            finally: stream.close()
        finally:
            self.stream=None
    def send(self, kind, payload):
        try: self.messages.put_nowait((kind,payload))
        except queue.Full: self.error='Interface backlog: an event notification was dropped; saved files remain on disk.'
    def run(self):
        c=self.config; rate=c['rate']; channels=c['channels']; block=1024
        ring=Ring(int((c['pre']+.3)*rate)+4096,channels)
        detector=Detector(rate,channels,c['prominence'],c['floor'],c['hold'],
                          early=c.get('early',.18),gap=c.get('gap',.10),
                          adaptive=c.get('adaptive',False))
        pending={}; frame=0; rng=np.random.default_rng(420)
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
        except OSError as exc:
            self.error=f'Recording folder unavailable: {exc}'
            self.send('warning',self.error);self.send('stopped',None);return
        jobs=queue.Queue(maxsize=64)
        def write_clips():
            while True:
                job=jobs.get()
                if job is None: return
                event,audio,mix=job
                try:
                    stem=self.directory/event['id']
                    wavfile.write(str(stem)+'.wav',rate,audio)
                    event['wav']=str(stem)+'.wav'
                    if mix is not None:
                        wavfile.write(str(stem)+'.mix.wav',rate,mix)
                        event['mix_wav']=str(stem)+'.mix.wav'
                    for flag in event.get('flags',[]):flag['recording_status']='saved'
                    (Path(str(stem)+'.json')).write_text(json.dumps(event,indent=2),encoding='utf-8')
                    self.saved+=1; self.send('event',event)
                except Exception as exc:
                    self.error=f'Clip could not be saved: {exc}'; self.send('warning',self.error)
        writer=threading.Thread(target=write_clips,daemon=True);writer.start()
        def finish(ch):
            event=pending.pop(ch)
            audio=np.concatenate(event.pop('_parts')).astype(np.float32)
            mix_parts=event.pop('_mix_parts',None)
            mix=np.concatenate(mix_parts).astype(np.float32) if mix_parts is not None else None
            event.pop('_remaining',None)
            event['duration']=len(audio)/rate
            event['complete_postroll']=len(audio)>=round((event['trigger_seconds']+c['post'])*rate)
            try:
                jobs.put_nowait((event,audio,mix));self.scheduled+=1
            except queue.Full:
                self.error='Clip writer backlog full: clip dropped; analysis continues.'
                self.send('warning',self.error)
        try:
            if not c['demo']:
                if self.stream is None: raise RuntimeError('Capture was not prepared on the main thread.')
            self.send('started',None)
            next_time=time.perf_counter()
            while not self.quit.is_set():
                if c['demo']:
                    x=demo_block(frame,block,rate,channels,rng)
                    next_time+=block/rate
                    if self.quit.wait(max(0,next_time-time.perf_counter())): break
                else:
                    try: x,overflow=self.audio_queue.get(timeout=.25)
                    except queue.Empty:
                        if not self.stream.active: raise RuntimeError('Audio capture stopped. Check device and clock.')
                        continue
                    if overflow:
                        self.gaps+=1
                        # Never bridge persistence or pre-roll across missing audio.
                        for ch in list(pending):
                            pending[ch]['audio_gap']=True; finish(ch)
                        ring=Ring(len(ring.data),channels)
                        detector.reset()
                        self.send('warning','Audio overflow: continuity reset. Increase driver buffer or reduce load.')
                x_mix=np.mean(x,axis=1,dtype=np.float32) if pending and c.get('record_mix',True) else None
                for ch in list(pending):
                    e=pending[ch]; take=min(len(x),e['_remaining'])
                    e['_parts'].append(x[:take,ch].copy())
                    if e.get('_mix_parts') is not None:e['_mix_parts'].append(x_mix[:take].copy())
                    e['_remaining']-=take
                    if e['_remaining']<=0: finish(ch)
                ring.append(x); frame+=len(x)
                now=frame/rate
                events,db=detector.analyze(ring.tail(4096),now,len(x)/rate)
                if db is None: continue
                levels=20*np.log10(np.maximum(np.sqrt(np.mean(x*x,axis=0)),1e-10))
                self.latest=(now,detector.freq,db,levels,detector.score.copy(),self.gaps)
                pre_all=None;pre_mix=None
                for d in events:
                    stamp=datetime.now().astimezone().isoformat(timespec='milliseconds')
                    flag=asdict(d);flag.update(time=stamp,channel=d.channel+1,
                        name=c['names'][d.channel],demo=c['demo'],source=c['source'],
                        capture_seconds=now,recording_status='not recorded')
                    if d.channel in pending:
                        e=pending[d.channel]
                        flag.update(event_id=e['id'],recording_status='collecting')
                        e['flags'].append(dict(flag))
                        if d.label=='Persistent ringing':e['label']=d.label
                    elif self.scheduled+len(pending)>=c['max_clips']:
                        self.error='Session clip limit reached. Flags and analysis continue; new clips are not saved.'
                    else:
                        if pre_all is None:
                            pre_all=ring.tail(round(c['pre']*rate))
                            if c.get('record_mix',True):pre_mix=np.mean(pre_all,axis=1,dtype=np.float32)
                        pre=pre_all[:,d.channel]
                        eid=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
                        flag.update(event_id=eid,recording_status='collecting')
                        pending[d.channel]={
                            'id':eid,'time':stamp,'channel':d.channel+1,'name':c['names'][d.channel],
                            'frequency':d.frequency,'level':d.level,'prominence':d.prominence,
                            'label':d.label,'flags':[dict(flag)],'rate':rate,'source':c['source'],'demo':c['demo'],
                            'device_label':c['device_label'],'trigger_seconds':len(pre)/rate,
                            'mix_description':'Arithmetic mean of monitored inputs; not the console main mix',
                            'audio_gap':False,'settings':{k:c[k] for k in ('floor','hold','prominence')},
                            '_parts':[pre.copy()],
                            '_mix_parts':[pre_mix.copy()] if pre_mix is not None else None,
                            '_remaining':round(c['post']*rate)}
                    self.send('flag',flag)
        except Exception as exc:
            self.error=f'Capture stopped: {exc}'; self.send('warning',self.error)
        finally:
            for ch in list(pending): finish(ch)
            jobs.put(None);writer.join()
            self.send('stopped',None)

class Player(threading.Thread):
    """A separate explicit output stream; never uses the capture device for replay."""
    def __init__(self,audio,rate,device):
        super().__init__(daemon=True); self.audio=audio; self.rate=rate; self.device=device
        self.quit=threading.Event(); self.error=''
    def run(self):
        try:
            with sd.OutputStream(device=self.device,samplerate=self.rate,channels=1,dtype='float32') as s:
                for offset in range(0,len(self.audio),1024):
                    if self.quit.is_set(): break
                    s.write(self.audio[offset:offset+1024,None])
        except Exception as exc: self.error=f'Playback failed: {exc}'
