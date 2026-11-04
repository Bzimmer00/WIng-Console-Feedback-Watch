import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.io import wavfile
from PySide6 import QtWidgets,QtCore
import app

class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.root_patch=patch.object(app,'ROOT',self.root);self.root_patch.start()
        self.w=app.Window()
        self.w.message=lambda text: (_ for _ in ()).throw(AssertionError(text))
        self.w.popup_early.setChecked(False);self.w.popup_persistent.setChecked(False)
    def tearDown(self):
        self.w.close();self.qt.processEvents();self.root_patch.stop();self.temp.cleanup()
    def event(self):
        directory=self.root/'events';directory.mkdir(exist_ok=True)
        rate=48000;t=np.arange(rate)/rate
        a=(.03*np.sin(2*np.pi*2500*t)).astype(np.float32);mix=(a*.25).astype(np.float32)
        wavfile.write(directory/'example.wav',rate,a);wavfile.write(directory/'example.mix.wav',rate,mix)
        event=dict(id='example',time='2026-11-02T10:00:00-08:00',source='WING USB',demo=False,channel=1,name='Lead',frequency=2500.,level=-30.,prominence=20.,duration=1.,label='Persistent ringing',trigger_seconds=.5,complete_postroll=False,audio_gap=False,wav=str(directory/'example.wav'),mix_wav=str(directory/'example.mix.wav'))
        self.w.add_event(event);self.w.event_table.selectRow(0);self.qt.processEvents();return event,a,mix
    def test_detach_and_reattach_keeps_same_page(self):
        original=self.w.tabs.widget(1);self.w.tabs.setCurrentIndex(1);self.w.detach_current();self.qt.processEvents()
        self.assertEqual(len(self.w.detached),1)
        panel=next(iter(self.w.detached.values()));self.assertIs(panel.page,original)
        panel.close();self.assertIs(self.w.tabs.widget(1),original);self.assertFalse(self.w.detached)
    def test_override_survives_console_refresh_and_profile_reload(self):
        self.w.console_names={'ch/1':'Console Vox'};self.w.mapping_confirm.setChecked(True)
        self.assertEqual(self.w.channel_table.item(0,1).text(),'Console Vox')
        self.w.name_table.item(0,3).setText('My local lead');self.w.console_names['ch/1']='Different console name';self.w.sync_names()
        self.assertEqual(self.w.channel_table.item(0,1).text(),'My local lead')
        self.w.save_profile();self.w.name_table.item(0,3).setText('Temporary');self.w.load_profile()
        self.assertEqual(self.w.channel_table.item(0,1).text(),'My local lead')
    def test_review_mix_flags_and_audio_export(self):
        e,a,mix=self.event();self.assertIsNotNone(self.w.clip)
        self.w.listen_source.setCurrentIndex(1);np.testing.assert_allclose(self.w.playback_audio(),mix)
        flag=dict(e,recording_status='collecting',event_id=e['id']);self.w.receive_flag(flag)
        self.w.review_flag(flag);self.assertEqual(self.w.event_table.currentRow(),0)
        output=self.root/'review.wav'
        with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(output),'WAV (*.wav)')):self.w.export_audio()
        rate,exported=wavfile.read(output);np.testing.assert_allclose(exported,mix)
        self.assertFalse(self.w.flag_panels['Early candidate'].isVisible())
    def test_incoming_clip_does_not_reset_current_review(self):
        e,a,mix=self.event();self.w.listen_source.setCurrentIndex(1)
        newer=dict(e,id='new-example',frequency=3200)
        self.w.add_event(newer);self.qt.processEvents()
        self.assertEqual(self.w.selected_event['id'],'example')
        self.assertEqual(self.w.listen_source.currentIndex(),1)
        np.testing.assert_allclose(self.w.playback_audio(),mix)
    def test_chart_and_bundle_exports(self):
        self.event();self.w.update_analytics()
        for extension in ('png','svg'):
            output=self.root/f'chart.{extension}'
            with patch.object(QtWidgets.QInputDialog,'getItem',return_value=('Clips by input',True)),patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(output),extension)):
                self.w.export_chart()
            self.assertGreater(output.stat().st_size,100)
        output=self.root/'bundle.zip'
        with patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=(str(output),'ZIP')):self.w.export_bundle()
        for job in self.w.export_jobs:job.join(3)
        with zipfile.ZipFile(output) as z:
            self.assertIsNone(z.testzip());self.assertIn('audio/example.mix.wav',z.namelist())
            events=json.loads(z.read('clips.json'));self.assertEqual(events[0]['wav'],'audio/example.wav')
    def test_old_mono_event_still_loads_without_context(self):
        e,a,mix=self.event();e.pop('mix_wav');e.pop('label');self.w.add_event(e);self.w.event_table.selectRow(0);self.qt.processEvents()
        self.assertIsNotNone(self.w.clip);self.assertFalse(self.w.listen_source.model().item(1).isEnabled())

if __name__=='__main__':unittest.main()
