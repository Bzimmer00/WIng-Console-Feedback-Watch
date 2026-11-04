"""Driver lifecycle regression checks; no Windows hardware required."""
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from engine import Engine

class CaptureTests(unittest.TestCase):
    def config(self):
        return dict(demo=False, device=7, rate=48000, channels=2, pre=1, post=1,
                    prominence=16, floor=-65, hold=.45, max_clips=20,
                    names=['A','B'],source='WING USB',device_label='WING [ASIO]')
    def test_main_thread_lifecycle_background_analysis_and_restart(self):
        owner=threading.get_ident();calls=[];streams=[]
        class Stream:
            def __init__(self, **kwargs):
                assert threading.get_ident()==owner
                self.options=kwargs;self.active=False;streams.append(self);calls.append('open')
            def start(self):
                assert threading.get_ident()==owner
                self.active=True;calls.append('start')
            def stop(self):
                assert threading.get_ident()==owner
                self.active=False;calls.append('stop')
            def close(self):
                assert threading.get_ident()==owner
                calls.append('close')
        with tempfile.TemporaryDirectory() as directory, patch('engine.sd',SimpleNamespace(InputStream=Stream)):
            for _ in range(2):
                e=Engine(self.config(),directory);e.prepare_capture();e.start()
                for _ in range(8):streams[-1].options['callback'](np.zeros((1024,2),np.float32),1024,None,False)
                deadline=time.monotonic()+2
                while e.latest is None and time.monotonic()<deadline:time.sleep(.01)
                self.assertIsNotNone(e.latest);self.assertEqual(e.latest[2].shape[1],2)
                e.quit.set();e.join(2);self.assertFalse(e.is_alive());self.assertFalse(e.error)
                e.close_capture();e.close_capture()
            self.assertEqual(calls,['open','start','stop','close']*2)
    def test_48_simultaneous_flags_flush_without_dropping_clips(self):
        class Stream:
            def __init__(self,**kwargs):self.callback=kwargs['callback'];self.active=False
            def start(self):self.active=True
            def stop(self):self.active=False
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory, patch('engine.sd',SimpleNamespace(InputStream=Stream)):
            config=self.config();config.update(channels=48,names=[f'Input {i+1}' for i in range(48)],max_clips=100)
            e=Engine(config,directory);e.prepare_capture();e.start()
            for i in range(44):
                t=(i*1024+np.arange(1024))/48000
                x=(.005*np.sin(2*np.pi*t[:,None]*(1500+np.arange(48)*43))).astype(np.float32)
                e.stream.callback(x,1024,None,False)
            deadline=time.monotonic()+7
            while (e.latest is None or e.latest[0]<44*1024/48000) and time.monotonic()<deadline:time.sleep(.01)
            e.quit.set();e.join(7);e.close_capture()
            self.assertFalse(e.is_alive());self.assertEqual(e.saved,48,e.error)
            from pathlib import Path
            import json
            from scipy.io import wavfile
            for path in Path(directory).glob('*.json'):
                event=json.loads(path.read_text());r,a=wavfile.read(event['wav']);r2,m=wavfile.read(event['mix_wav'])
                self.assertEqual(r,r2);self.assertEqual(len(a),len(m));self.assertTrue(event['flags'])
    def test_start_failure_closes_stream(self):
        calls=[]
        class Stream:
            def __init__(self,**kw):pass
            def start(self):raise RuntimeError('Failed to load ASIO driver')
            def stop(self):calls.append('stop')
            def close(self):calls.append('close')
        with tempfile.TemporaryDirectory() as directory, patch('engine.sd',SimpleNamespace(InputStream=Stream)):
            e=Engine(self.config(),directory)
            with self.assertRaisesRegex(RuntimeError,'Failed to load'):e.prepare_capture()
            self.assertIsNone(e.stream);self.assertEqual(calls,['stop','close'])
    def test_callback_backlog_marks_gap(self):
        class Stream:
            def __init__(self,**kw):self.callback=kw['callback']
            def start(self):pass
            def stop(self):pass
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory, patch('engine.sd',SimpleNamespace(InputStream=Stream)):
            e=Engine(self.config(),directory);e.prepare_capture()
            for _ in range(129):e.stream.callback(np.zeros((1024,2),np.float32),1024,None,False)
            self.assertTrue(e.callback_gap.is_set())
            e.audio_queue.get_nowait();e.stream.callback(np.zeros((1024,2),np.float32),1024,None,False)
            values=[]
            while not e.audio_queue.empty():values.append(e.audio_queue.get_nowait())
            self.assertTrue(values[-1][1]);e.close_capture()

if __name__=='__main__':unittest.main()
