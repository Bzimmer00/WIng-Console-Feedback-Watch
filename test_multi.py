import time,unittest
import numpy as np
from core import Detector,Ring

class MultiTests(unittest.TestCase):
    def analyze(self,blocks,rate=48000,**settings):
        n=blocks[0].shape[1];d=Detector(rate,n,**settings);r=Ring(6000,n);events=[]
        for i,x in enumerate(blocks):
            r.append(x);found,_=d.analyze(r.tail(4096),(i+1)*1024/rate,1024/rate);events.extend(found)
        return events
    def test_quiet_tone_under_alternating_louder_tones(self):
        blocks=[]
        for i in range(55):
            t=(i*1024+np.arange(1024))/48000
            x=.003*np.sin(2*np.pi*2500*t)+.1*np.sin(2*np.pi*(550 if i%8<4 else 850)*t)
            blocks.append(x[:,None].astype(np.float32))
        events=self.analyze(blocks)
        self.assertTrue(any(abs(e.frequency-2500)<10 and e.label=='Early candidate' for e in events))
        self.assertTrue(any(abs(e.frequency-2500)<10 and e.label=='Persistent ringing' for e in events))
    def test_cooldown_does_not_hide_new_frequency_on_same_channel(self):
        blocks=[]
        for i in range(70):
            t=(i*1024+np.arange(1024))/48000
            f=2000 if i<32 else 4000
            blocks.append((.01*np.sin(2*np.pi*f*t))[:,None].astype(np.float32))
        found=self.analyze(blocks)
        for freq in (2000,4000):self.assertTrue(any(abs(e.frequency-freq)<10 and e.label=='Persistent ringing' for e in found))
    def test_both_types_and_no_repeated_stationary_alerts(self):
        blocks=[]
        for i in range(80):
            t=(i*1024+np.arange(1024))/48000;blocks.append((.01*np.sin(2*np.pi*2500*t))[:,None].astype(np.float32))
        found=self.analyze(blocks)
        self.assertEqual([e.label for e in found],['Early candidate','Persistent ringing'])
    def test_gap_retains_but_does_not_count_missing_time(self):
        d=Detector(48000,1,hold=.4,early=.15,gap=.1);r=Ring(6000,1);events=[]
        # Explicit silent FFT windows, then the same peak within gap tolerance.
        for i in range(10):
            t=np.arange(4096)/48000
            a=(.01*np.sin(2*np.pi*2500*t))[:,None]
            if i in (4,5):a=np.zeros_like(a)
            e,_=d.analyze(a,(i+1)*.04,.04);events+=e
        self.assertEqual(sum(e.label=='Early candidate' for e in events),1)
        self.assertFalse(any(e.label=='Persistent ringing' for e in events))
    def test_sweeping_tone_does_not_qualify_as_stable_ringing(self):
        blocks=[]
        for i in range(100):
            t=(i*1024+np.arange(1024))/48000
            x=.02*np.sin(2*np.pi*(1800*t+150*t*t))
            blocks.append(x[:,None].astype(np.float32))
        found=self.analyze(blocks)
        self.assertFalse(any(e.label=='Persistent ringing' for e in found))
    def test_48_channels_and_report_processing_budget(self):
        rate=48000;hop=1024;frames=70;r=Ring(6000,48);d=Detector(rate,48)
        frequencies=1500+np.arange(48)*43;found=[];start=time.perf_counter()
        for i in range(frames):
            t=(i*hop+np.arange(hop))/rate
            x=(.005*np.sin(2*np.pi*t[:,None]*frequencies)).astype(np.float32)
            r.append(x);events,_=d.analyze(r.tail(4096),(i+1)*hop/rate,hop/rate);found+=events
        elapsed=time.perf_counter()-start
        self.assertEqual({e.channel for e in found if e.label=='Persistent ringing'},set(range(48)))
        print(f'48-input synthetic benchmark: {frames*hop/rate:.2f}s audio processed in {elapsed:.2f}s (this machine only)',flush=True)

if __name__=='__main__':unittest.main()
