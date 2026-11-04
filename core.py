"""Audio-only analysis. No console control, socket, MIDI, OSC or routing API."""
from dataclasses import dataclass
import numpy as np
from scipy.signal import find_peaks, butter, sosfiltfilt

@dataclass
class Detection:
    channel: int
    frequency: float
    level: float
    prominence: float
    label: str = 'Suspected ringing'
    baseline_excess: float = 0.
    growth_db_sec: float = 0.
    frequency_spread: float = 0.
    observed_seconds: float = 0.

class Ring:
    def __init__(self, frames, channels):
        self.data = np.zeros((frames, channels), np.float32)
        self.pos = 0
        self.size = 0
    def append(self, x):
        x = np.asarray(x, dtype=np.float32)[-len(self.data):]
        n = len(x); first = min(n, len(self.data)-self.pos)
        self.data[self.pos:self.pos+first] = x[:first]
        if first < n: self.data[:n-first] = x[first:]
        self.pos = (self.pos+n) % len(self.data)
        self.size = min(len(self.data), self.size+n)
    def tail(self, count=None):
        n = min(self.size, count if count is not None else self.size)
        start = (self.pos-n) % len(self.data)
        if start+n <= len(self.data): return self.data[start:start+n].copy()
        return np.concatenate((self.data[start:], self.data[:n-(len(self.data)-start)]))

class Detector:
    """Track up to eight narrowband candidates/input; labels are not probabilities."""
    def __init__(self, rate, channels, prominence=12, floor=-75, hold=.45,
                 early=.18, gap=.10, cooldown=8., adaptive=False):
        self.rate,self.channels=rate,channels
        self.prominence,self.floor,self.hold=prominence,floor,hold
        self.early=min(early,hold);self.gap=gap;self.cooldown=cooldown;self.adaptive=adaptive
        self.nfft=4096;self.window=np.hanning(self.nfft)
        self.freq=np.fft.rfftfreq(self.nfft,1/rate)
        self.score=np.zeros(channels);self.tracks=[[] for _ in range(channels)]
        self.recent=[[] for _ in range(channels)];self.baseline=None;self.elapsed=0.
    def reset(self):
        self.tracks=[[] for _ in range(self.channels)];self.score[:]=0
        self.baseline=None;self.elapsed=0.
    @staticmethod
    def tolerance(f):return max(18.,f*.008)
    def analyze(self,samples,now,dt):
        if len(samples)<self.nfft:return [],None
        spec=np.abs(np.fft.rfft(samples[-self.nfft:]*self.window[:,None],axis=0))*2/self.window.sum()
        db=20*np.log10(np.maximum(spec,1e-10));self.score[:]=0;events=[]
        if self.baseline is None:self.baseline=db.copy()
        self.elapsed+=dt
        for ch in range(self.channels):
            tracks=self.tracks[ch]=[t for t in self.tracks[ch] if now-t['last']<=self.gap+dt+1e-6]
            self.recent[ch]=[e for e in self.recent[ch] if now-e[0]<self.cooldown]
            peaks,props=find_peaks(db[:,ch],prominence=self.prominence,distance=3)
            valid=(self.freq[peaks]>=100)&(self.freq[peaks]<=min(16000,self.rate*.45))&(db[peaks,ch]>=self.floor)
            peaks=peaks[valid];proms=props['prominences'][valid]
            # Rank by prominence rather than allowing a loud vocal to own the tracker.
            order=np.argsort(proms)[-8:][::-1];used=set()
            for idx in order:
                p=int(peaks[idx]);f=self.freq[p]
                a,b,c=db[p-1:p+2,ch];den=a-2*b+c
                f+=float(np.clip(.5*(a-c)/den,-.5,.5) if abs(den)>1e-9 else 0)*self.rate/self.nfft
                excess=float(db[p,ch]-self.baseline[p,ch])
                if self.adaptive and (self.elapsed<1.5 or excess<6):continue
                candidates=[t for t in tracks if id(t) not in used and abs(f-t['f'])<=self.tolerance(f)]
                if candidates:
                    t=min(candidates,key=lambda t:abs(f-t['f']))
                    t['duration']+=min(dt,max(0,now-t['last']))
                    t['low']=min(t['low'],f);t['high']=max(t['high'],f)
                else:
                    t=dict(f=f,duration=dt,last=now,first=now,level=float(db[p,ch]),low=f,high=f,sent=set())
                    tracks.append(t)
                used.add(id(t));t['f']=float(f);t['last']=now
                if t['high']-t['low']>max(25.,f*.012):
                    t.update(duration=dt,first=now,level=float(db[p,ch]),low=f,high=f,sent=set())
                self.score[ch]=max(self.score[ch],min(1,t['duration']/self.hold))
                for label,threshold in [('Early candidate',self.early),('Persistent ringing',self.hold)]:
                    if t['duration']+1e-9<threshold or label in t['sent']:continue
                    t['sent'].add(label)
                    if any(e[1]==label and abs(e[2]-f)<=self.tolerance(f) for e in self.recent[ch]):continue
                    self.recent[ch].append((now,label,float(f)))
                    span=max(dt,now-t['first'])
                    events.append(Detection(ch,float(f),float(db[p,ch]),float(proms[idx]),label,
                        excess,(float(db[p,ch])-t['level'])/span,t['high']-t['low'],t['duration']))
            self.tracks[ch]=sorted(tracks,key=lambda t:t['last'],reverse=True)[:16]
        # Slow upward adaptation preserves evidence of emerging tones; downward adapts faster.
        weight=np.where(db<self.baseline,min(1,dt/.5),min(1,dt/30))
        self.baseline+=weight*(db-self.baseline)
        return events,db

def filtered_audio(audio, rate, center, bandwidth, mode):
    if mode=='Full clip': return audio.copy()
    lo=max(20,center-bandwidth/2); hi=min(rate*.48,center+bandwidth/2)
    if hi<=lo: raise ValueError('Frequency band is outside the clip sample rate.')
    sos=butter(4,[lo,hi],btype='bandpass',fs=rate,output='sos')
    band=sosfiltfilt(sos,audio).astype(np.float32)
    return band if mode=='Selected band' else audio-band

def demo_block(start, frames, rate, channels, rng):
    t=(start+np.arange(frames))/rate
    x=rng.normal(0,.0015,(frames,channels)).astype(np.float32)
    for ch in range(channels):
        # Moving harmonic material plus periodically injected, quiet narrowband ringing.
        phase=2*np.pi*(130+ch*11)*t + 120*np.sin(2*np.pi*.8*t)
        x[:,ch]+=(.004*np.sin(phase)+.002*np.sin(2*phase)).astype(np.float32)
        cycle=(t+ch*2)%18
        envelope=np.clip((cycle-7)*3,0,1)*np.clip((12-cycle)*3,0,1)
        x[:,ch]+=(.018*envelope*np.sin(2*np.pi*(1250+ch*310)*t)).astype(np.float32)
    return x
