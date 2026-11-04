import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile,json,zipfile,traceback
from pathlib import Path
import app
from PySide6 import QtWidgets,QtCore
from scipy.io import wavfile
app.ROOT=Path(tempfile.mkdtemp(prefix='wing-v02-smoke-'));a=QtWidgets.QApplication([]);w=app.Window()
w.channels.setValue(4);w.pre.setValue(2);w.post.setValue(1);w.popup_early.setChecked(False);w.popup_persistent.setChecked(True)
w.show();errors=[]
def on_error(kind,value,tb):
    errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=on_error
w.start()
for i in range(4):w.channel_table.selectRow(i)
def review():
    assert w.events,'No saved clips'
    assert any(f['label']=='Early candidate' for f in w.flags)
    assert any(f['label']=='Persistent ringing' for f in w.flags)
    assert any(f['frequency']>1000 for f in w.flags)
    e=next(e for e in w.events if any(f['frequency']>1000 for f in e.get('flags',[])))
    flag=next(f for f in e['flags'] if f['frequency']>1000);flag['event_id']=e['id']
    w.review_flag(flag);assert w.clip is not None
    w.listen_source.setCurrentIndex(1);mix=w.playback_audio();assert len(mix)==len(w.clip)
    for e in w.events:
        r,x=wavfile.read(e['wav']);r2,m=wavfile.read(e['mix_wav'])
        assert r==r2 and len(x)==len(m)
    w.tabs.setCurrentIndex(1);w.detach_current();assert len(w.detached)==1
    w.tabs.setCurrentIndex(3);w.detach_current();assert len(w.detached)==2
    previous=w.engine.latest[0]
    def advance():
        assert w.engine.latest[0]>previous,'Review/detach blocked analysis'
        assert w.flag_panels['Persistent ringing'].isVisible()
        assert not w.flag_panels['Early candidate'].isVisible()
        w.reattach_all();assert not w.detached
        w.tabs.setCurrentIndex(2);a.processEvents();w.grab().save(str(app.ROOT/'Review.png'))
        w.tabs.setCurrentIndex(1);a.processEvents();w.grab().save(str(app.ROOT/'Live.png'))
        w.tabs.setCurrentIndex(3);a.processEvents();w.grab().save(str(app.ROOT/'Analytics.png'))
        w.close();QtCore.QTimer.singleShot(1300,finish)
    QtCore.QTimer.singleShot(800,advance)
def finish():
    assert not w.engine.is_alive() and w.engine.stream is None
    assert not errors,errors
    print('PASS: both flags, synced input/context WAVs, review continues, popups, detached panels, close/flush',flush=True)
    print('Session:',app.ROOT,flush=True);a.exit(0)
a.setQuitOnLastWindowClosed(False)
QtCore.QTimer.singleShot(13500,review)
QtCore.QTimer.singleShot(23000,lambda:(print('FAIL: timeout',flush=True),a.exit(2)))
sys.exit(a.exec())
