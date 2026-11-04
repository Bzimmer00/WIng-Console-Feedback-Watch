import unittest
import numpy as np
from core import Ring, Detector, filtered_audio, demo_block

class AudioTests(unittest.TestCase):
    def test_ring_wrap_and_partial(self):
        r=Ring(5,1);r.append(np.arange(3)[:,None]);np.testing.assert_array_equal(r.tail()[:,0],[0,1,2])
        r.append(np.arange(3,9)[:,None]);np.testing.assert_array_equal(r.tail()[:,0],[4,5,6,7,8])
        np.testing.assert_array_equal(r.tail(2)[:,0],[7,8])
    def test_quiet_tone_localization_and_noise(self):
        rate=48000; rng=np.random.default_rng(12); ring=Ring(6000,2); d=Detector(rate,2);events=[]
        for i in range(30):
            t=(i*1024+np.arange(1024))/rate;x=rng.normal(0,.0005,(1024,2))
            x[:,1]+=.006*np.sin(2*np.pi*2500*t);ring.append(x)
            e,_=d.analyze(ring.tail(4096),(i+1)*1024/rate,1024/rate);events+=e
        self.assertTrue(events);self.assertEqual(events[0].channel,1)
        self.assertLess(abs(events[0].frequency-2500),10)
        self.assertLess(events[0].level,-40)
    def test_broadband_noise_and_brief_transient(self):
        rate=48000;ring=Ring(6000,1);d=Detector(rate,1);rng=np.random.default_rng(81);events=[]
        for i in range(60):
            t=(i*1024+np.arange(1024))/rate;x=rng.normal(0,.002,(1024,1))
            if 10<=i<14:x[:,0]+=.03*np.sin(2*np.pi*3200*t)
            ring.append(x);e,_=d.analyze(ring.tail(4096),(i+1)*1024/rate,1024/rate);events+=e
        self.assertEqual(events,[])
    def test_filter_reconstruction_and_isolation(self):
        rate=48000;t=np.arange(rate)/rate
        a=(.1*np.sin(2*np.pi*1000*t)+.1*np.sin(2*np.pi*4000*t)).astype(np.float32)
        b=filtered_audio(a,rate,1000,200,'Selected band');c=filtered_audio(a,rate,1000,200,'Band removed')
        np.testing.assert_allclose(b+c,a,atol=1e-7)
        fft=np.abs(np.fft.rfft(b[4000:-4000]));f=np.fft.rfftfreq(len(b)-8000,1/rate)
        self.assertGreater(fft[np.argmin(abs(f-1000))],100*fft[np.argmin(abs(f-4000))])
    def test_demo_detects_injected_tone(self):
        rate=48000;d=Detector(rate,2);ring=Ring(6000,2);rng=np.random.default_rng(42);found=[]
        for i in range(480):
            x=demo_block(i*1024,1024,rate,2,rng);ring.append(x)
            if i%4==3:
                e,_=d.analyze(ring.tail(4096),(i+1)*1024/rate,4096/rate);found+=e
        self.assertTrue(any(abs(e.frequency-1250)<10 for e in found))

if __name__=='__main__':unittest.main()
