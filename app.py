"""WING Feedback Watch — desktop prototype, audio capture only."""
import csv, json, os, sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import spectrogram
from PySide6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg
from engine import Engine, Player, sd
from core import filtered_audio
from features import Features

ROOT=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'WingFeedbackWatch'
ROOT.mkdir(parents=True,exist_ok=True)
pg.setConfigOptions(antialias=True, background='#101b2d', foreground='#a8bad1')

STYLE='''
QWidget { background:#0b1322; color:#dce6f3; font-family:Segoe UI; font-size:12px; }
QLabel#title {font-size:25px; font-weight:700; color:#ffffff;}
QLabel#subtitle {color:#8fa6c4;}
QGroupBox {border:1px solid #263851; border-radius:8px; margin-top:12px; padding:12px 7px 7px; font-weight:600;}
QGroupBox::title {subcontrol-origin:margin; left:10px; color:#91aac9;}
QPushButton {background:#1e344d; border:1px solid #38516e; border-radius:5px; padding:7px 12px;}
QPushButton:hover {background:#2c4867;} QPushButton:disabled {color:#64758c; background:#152338;}
QPushButton#primary {background:#167d7f; color:white; border:1px solid #20a3a4; font-weight:700;}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {background:#142238; border:1px solid #31465f; border-radius:4px; padding:4px;}
QTableWidget {background:#101b2d; alternate-background-color:#142238; border:0; gridline-color:#22334b;}
QHeaderView::section {background:#18283e; color:#a2bad6; padding:7px; border:0;}
QTableWidget::item:selected {background:#235269;}
QTabWidget::pane {border:0;} QTabBar::tab {padding:10px 18px; background:#132036; color:#91a9c7;}
QTabBar::tab:selected {background:#203a52; color:#75e1db;}
QLabel#stat {font-size:18px; font-weight:600; color:#66ded4; padding:8px; background:#142238; border-radius:5px;}
QSplitter::handle {background:#22334b; width:4px; height:4px;}
'''

def button(text,fn,primary=False):
    b=W.QPushButton(text); b.clicked.connect(fn)
    if primary:b.setObjectName('primary')
    return b

def plot(title,xlabel,ylabel):
    p=pg.PlotWidget(title=title); p.setLabel('bottom',xlabel); p.setLabel('left',ylabel)
    p.showGrid(x=True,y=True,alpha=.15); p.getAxis('bottom').enableAutoSIPrefix(False); return p

def group(title,layout):
    g=W.QGroupBox(title);g.setLayout(layout);return g

class Window(Features,W.QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('WING Feedback Watch • v0.2.0');self.resize(1500,960)
        self.engine=None;self.player=None;self.events=[];self.clip=None;self.clip_rate=48000
        self.active_config=None;self.profiles={};self.live_ch=0;self.last_live_time=-1
        try:self.profiles=json.loads((ROOT/'profiles.json').read_text())
        except (FileNotFoundError,ValueError):pass
        shell=W.QWidget();self.setCentralWidget(shell);outer=W.QVBoxLayout(shell)
        head=W.QHBoxLayout();title=W.QLabel('WING  /  FEEDBACK WATCH');title.setObjectName('title');head.addWidget(title)
        head.addStretch();self.badge=W.QLabel('AUDIO CAPTURE ONLY  •  No console control');self.badge.setObjectName('stat');head.addWidget(self.badge);outer.addLayout(head)
        sub=W.QLabel('Monitor • investigate • listen     |     Suspected ringing is a diagnostic hint, not confirmed feedback.');sub.setObjectName('subtitle');outer.addWidget(sub)
        self.tabs=W.QTabWidget();outer.addWidget(self.tabs,1)
        self.setup_ui();self.monitor_ui();self.review_ui();self.analytics_ui();self.extra_ui()
        self.status=W.QLabel('Stopped. Select Demo to explore, or configure an installed audio driver.');outer.addWidget(self.status)
        self.setStyleSheet(STYLE);self.refresh_devices();self.load_profile();self.load_events()
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(100)
    def setup_ui(self):
        page=W.QWidget();self.tabs.addTab(page,'01  Connection');layout=W.QVBoxLayout(page)
        row=W.QHBoxLayout();form=W.QFormLayout()
        self.source=W.QComboBox();self.source.addItems(['WING USB','Dante','Waves SoundGrid']);self.source.currentTextChanged.connect(self.load_profile)
        self.device=W.QComboBox();self.device.setMinimumWidth(410)
        self.demo=W.QCheckBox('Demo — generated audio, no console connection');self.demo.setChecked(True)
        self.rate=W.QComboBox();self.rate.addItems(['48000','44100','96000'])
        self.channels=W.QSpinBox();self.channels.setRange(1,48);self.channels.setValue(8);self.channels.valueChanged.connect(self.populate_channels)
        self.floor=W.QSpinBox();self.floor.setRange(-100,-10);self.floor.setValue(-75);self.floor.setSuffix(' dBFS')
        self.prom=W.QSpinBox();self.prom.setRange(6,40);self.prom.setValue(12);self.prom.setSuffix(' dB')
        self.hold=W.QDoubleSpinBox();self.hold.setRange(.15,3);self.hold.setSingleStep(.05);self.hold.setValue(.45);self.hold.setSuffix(' sec')
        self.pre=W.QSpinBox();self.pre.setRange(1,10);self.pre.setValue(5);self.pre.setSuffix(' sec')
        self.post=W.QSpinBox();self.post.setRange(1,10);self.post.setValue(5);self.post.setSuffix(' sec')
        self.limit=W.QSpinBox();self.limit.setRange(10,2000);self.limit.setValue(200)
        for label,widget in [('Source profile',self.source),('Input audio device',self.device),('Sample rate',self.rate),('Input channels (first N)',self.channels),('Minimum tone level',self.floor),('Peak prominence',self.prom),('Tone persistence',self.hold),('Before detection',self.pre),('After detection',self.post),('Maximum clips per capture session',self.limit)]:form.addRow(label,widget)
        form.addRow(self.demo)
        controls=W.QHBoxLayout();controls.addWidget(button('Refresh devices',self.refresh_devices));controls.addWidget(button('Save source profile',self.save_profile));form.addRow(controls)
        row.addWidget(group('LOCAL CAPTURE SETTINGS',form),1)
        notes=W.QLabel('Three source profiles, one active capture device at a time.\n\n'
            'Choose the actual installed driver. The source label does not create routing or translate protocols.\n\n'
            'USB: manually patch WING USB sends.\nDante: patch receiver channels using Dante Controller.\nSoundGrid: patch the recording driver using the Waves host.\n\n'
            'Prefer an ASIO device for multichannel capture. Other applications may hold the driver exclusively.\n\n'
            'Channel numbers here are audio-stream slots. Use Names / mapping for read-only console name import and local overrides. Verify the mapping against your audio patch.\n\n'
            'Network access sends only argument-free, allowlisted name queries. All edits affect this app only.\n\n'
            'Lower level/prominence thresholds or shorter persistence can detect quieter/shorter ringing, with more musical false alerts.\n\n'
            'Clips are saved locally as float WAV + JSON. Demo clips are labelled. No cloud uploads.');notes.setWordWrap(True);notes.setMaximumWidth(520)
        row.addWidget(group('CONNECTION GUIDE',W.QVBoxLayout()),1);row.itemAt(1).widget().layout().addWidget(notes);row.itemAt(1).widget().layout().addStretch()
        layout.addLayout(row)
        actions=W.QHBoxLayout();self.start_btn=button('Start monitoring',self.start,True);self.stop_btn=button('Stop monitoring',self.stop);self.stop_btn.setEnabled(False)
        actions.addWidget(self.start_btn);actions.addWidget(self.stop_btn);actions.addStretch();actions.addWidget(button('Open recordings folder',lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(ROOT/'events')))))
        layout.addLayout(actions);layout.addStretch()
        self.config_widgets=[self.source,self.device,self.demo,self.rate,self.channels,self.floor,self.prom,self.hold,self.pre,self.post,self.limit]
    def monitor_ui(self):
        page=W.QWidget();self.tabs.addTab(page,'02  Live monitor');v=W.QVBoxLayout(page)
        self.stats=W.QLabel('STOPPED  |  No incoming audio');self.stats.setObjectName('stat');v.addWidget(self.stats)
        split=W.QSplitter();v.addWidget(split)
        self.channel_table=W.QTableWidget(0,5);self.channel_table.setHorizontalHeaderLabels(['Input','Name / mapping','RMS dBFS','Ringing score','Status'])
        self.channel_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.channel_table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows);self.channel_table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.channel_table.itemSelectionChanged.connect(self.select_live_channel);split.addWidget(self.channel_table)
        right=W.QWidget();rv=W.QVBoxLayout(right);split.addWidget(right);split.setSizes([580,820])
        self.live_spec=plot('Live spectrum — select a channel','Frequency (Hz, logarithmic)','Magnitude (dBFS, peak-bin estimate)');self.live_spec.setLogMode(x=True)
        self.live_spec.getAxis('bottom').setTicks([[(np.log10(f),str(f)) for f in [100,200,500,1000,2000,5000,10000,20000]]])
        self.live_spec.setYRange(-100,0);self.live_spec.setXRange(np.log10(80),np.log10(18000));self.live_curve=self.live_spec.plot(pen=pg.mkPen('#62e2d4',width=2));rv.addWidget(self.live_spec)
        self.level_plot=plot('Recent channel level — last 30 seconds','Capture time (seconds)','RMS (dBFS)');self.level_curve=self.level_plot.plot(pen=pg.mkPen('#7d9fff',width=2));rv.addWidget(self.level_plot)
        self.level_history=[];self.populate_channels()
    def review_ui(self):
        page=W.QWidget();self.tabs.addTab(page,'03  Detection review');v=W.QVBoxLayout(page)
        self.review_note=W.QLabel('Select a saved event. Live analysis continues while this page is open.');self.review_note.setObjectName('stat');v.addWidget(self.review_note)
        splitter=W.QSplitter(QtCore.Qt.Orientation.Vertical);v.addWidget(splitter,1)
        self.event_table=W.QTableWidget(0,7);self.event_table.setHorizontalHeaderLabels(['Time','Source','Channel / name','Frequency Hz','Tone dBFS','Clip sec','Type'])
        self.event_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers);self.event_table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.event_table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection);self.event_table.itemSelectionChanged.connect(self.select_event)
        self.event_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch);splitter.addWidget(self.event_table)
        plots=W.QWidget();grid=W.QGridLayout(plots)
        self.wave=plot('Recorded waveform','Time from clip start (s)','Amplitude');self.wave_curve=self.wave.plot(pen='#7d9fff');grid.addWidget(self.wave,0,0)
        self.trigger=pg.InfiniteLine(angle=90,pen=pg.mkPen('#ffbd69',style=QtCore.Qt.PenStyle.DashLine));self.wave.addItem(self.trigger)
        self.review_spec=plot('Clip spectrum — click to choose a frequency','Frequency (Hz, logarithmic)','Magnitude (dBFS, peak-bin estimate)');self.review_spec.setLogMode(x=True);self.review_spec.getAxis('bottom').setTicks([[(np.log10(f),str(f)) for f in [100,200,500,1000,2000,5000,10000,20000]]]);self.review_curve=self.review_spec.plot(pen='#62e2d4');grid.addWidget(self.review_spec,0,1)
        self.band_marker=pg.LinearRegionItem([3.2,3.4],movable=False,brush=(65,220,203,35));self.review_spec.addItem(self.band_marker)
        self.review_spec.scene().sigMouseClicked.connect(self.spectrum_click)
        self.waterfall=plot('Spectrogram • color range -90 to -20 dBFS','Time from clip start (s)','Frequency (Hz)');self.image=pg.ImageItem(axisOrder='row-major');self.waterfall.addItem(self.image);grid.addWidget(self.waterfall,1,0,1,2)
        self.image.setLookupTable(pg.colormap.get('viridis').getLookupTable());splitter.addWidget(plots);splitter.setSizes([180,500])
        controls=W.QHBoxLayout();self.center=W.QDoubleSpinBox();self.center.setRange(30,20000);self.center.setValue(2500);self.center.setSuffix(' Hz')
        self.bandwidth=W.QSpinBox();self.bandwidth.setRange(20,10000);self.bandwidth.setValue(160);self.bandwidth.setSuffix(' Hz wide')
        self.mode=W.QComboBox();self.mode.addItems(['Full clip','Selected band','Band removed'])
        self.output=W.QComboBox();self.output.setMinimumWidth(200)
        self.volume=W.QSpinBox();self.volume.setRange(-60,0);self.volume.setValue(-18);self.volume.setSuffix(' dB playback')
        for w in [W.QLabel('Target'),self.center,self.bandwidth,self.mode,self.output,self.volume]:controls.addWidget(w)
        controls.addWidget(button('Play clip',self.play,True));controls.addWidget(button('Stop',self.stop_playback));v.addLayout(controls)
        self.center.valueChanged.connect(self.update_band);self.bandwidth.valueChanged.connect(self.update_band)
        foot=W.QHBoxLayout();foot.addWidget(W.QLabel('Replay goes only to the selected local output. Use headphones; verify its physical connection.'));foot.addStretch()
        foot.addWidget(button('Export detections CSV',self.export_csv));v.addLayout(foot)
    def analytics_ui(self):
        page=W.QWidget();self.tabs.addTab(page,'04  Analytics');g=W.QGridLayout(page)
        self.analytics_note=W.QLabel('Saved-event summaries • includes demo and live events, identified in the review table • last 500 loaded events');g.addWidget(self.analytics_note,0,0,1,2)
        self.count_plot=plot('Detections by audio input','Input channel','Saved events');g.addWidget(self.count_plot,1,0)
        self.hist_plot=plot('Suspected ringing by frequency range','Frequency (Hz, logarithmic)','Saved events');self.hist_plot.getAxis('bottom').setTicks([[(np.log10(f),str(f)) for f in [100,200,500,1000,2000,5000,10000,20000]]]);g.addWidget(self.hist_plot,1,1)
        self.trend=plot('Detection timeline','Minutes since earliest loaded event','Frequency (Hz)');g.addWidget(self.trend,2,0,1,2)
    def populate_channels(self):
        if not hasattr(self,'channel_table'):return
        names=[self.channel_table.item(i,1).text() for i in range(self.channel_table.rowCount()) if self.channel_table.item(i,1)]
        self.channel_table.setRowCount(self.channels.value())
        for r in range(self.channel_table.rowCount()):
            for col,text in enumerate([str(r+1),names[r] if r<len(names) else f'Input {r+1}','—','—','Awaiting audio']):
                item=W.QTableWidgetItem(text)
                if col!=1:item.setFlags(item.flags()&~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.channel_table.setItem(r,col,item)
        self.channel_table.selectRow(0)
        if hasattr(self,'name_table'):self.sync_names()
    def refresh_devices(self):
        if self.engine and self.engine.is_alive():return
        self.device.clear();self.output.clear();self.output.addItem('Select headphone output…',None)
        try:
            if sd is None: raise RuntimeError('Audio library unavailable; demo and clip review still work.')
            apis=sd.query_hostapis()
            for i,d in enumerate(sd.query_devices()):
                api=apis[d['hostapi']]['name'];label=f"{d['name']} [{api}]"
                if d['max_input_channels']>0:self.device.addItem(label,{'id':i,'name':d['name'],'max':d['max_input_channels']})
                # Keep console/network audio drivers out of review playback choices.
                excluded=any(s in label.lower() for s in ['asio','wing','dante','waves','soundgrid','voicemeeter','vb-audio','virtual'])
                if d['max_output_channels']>0 and not excluded:self.output.addItem(label,i)
        except Exception as exc:self.status.setText(f'Audio device enumeration failed: {exc}')
    def config(self):
        data=self.device.currentData()
        return dict(**self.extra_config(),source=self.source.currentText(),demo=self.demo.isChecked(),device=data['id'] if data else None,
            device_label=self.device.currentText(),rate=int(self.rate.currentText()),channels=self.channels.value(),
            floor=self.floor.value(),prominence=self.prom.value(),hold=self.hold.value(),pre=self.pre.value(),post=self.post.value(),
            max_clips=self.limit.value(),names=[self.channel_table.item(i,1).text() for i in range(self.channels.value())])
    def save_profile(self):
        c=self.config();c.pop('device');self.profiles[c['source']]=c
        (ROOT/'profiles.json').write_text(json.dumps(self.profiles,indent=2),encoding='utf-8');self.status.setText('Source profile saved locally.')
    def load_profile(self):
        if not hasattr(self,'channel_table'):return
        c=self.profiles.get(self.source.currentText())
        if not c:return
        self.channels.setValue(c['channels']);self.populate_channels();self.rate.setCurrentText(str(c['rate']));self.demo.setChecked(c['demo'])
        for w,key in [(self.floor,'floor'),(self.prom,'prominence'),(self.hold,'hold'),(self.pre,'pre'),(self.post,'post'),(self.limit,'max_clips')]:w.setValue(c[key])
        for i,name in enumerate(c['names'][:self.channel_table.rowCount()]):self.channel_table.item(i,1).setText(name)
        index=self.device.findText(c['device_label']);self.device.setCurrentIndex(index)
        self.load_extra(c)
    def start(self):
        if self.engine and self.engine.is_alive():return
        c=self.config();data=self.device.currentData()
        if c['early']>c['hold']:return self.message('Early persistence must be no longer than persistent-ringing persistence.')
        if not c['demo']:
            if not data:return self.message('Select an installed audio input device.')
            if c['channels']>data['max']:return self.message(f"This driver exposes {data['max']} input channels. Reduce the channel count or select its ASIO entry.")
            if self.output.currentData()==c['device']:return self.message('Choose a separate headphone output before starting.')
        if not self.stop_playback():return self.message('Playback is still stopping. Try again shortly.')
        self.active_config=c;self.level_history=[];self.multi_history=[];self.last_live_time=-1
        self.engine=Engine(c,ROOT/'events')
        try:
            self.engine.prepare_capture()
            self.engine.start()
        except Exception as exc:
            self.engine.close_capture()
            text=f"Capture could not start: {exc}\nDevice: {c['device_label']}\n{c['channels']} inputs at {c['rate']} Hz. Close other apps using this driver and confirm the device sample rate."
            self.status.setText(text);self.active_config=None
            return self.message(text)
        for w in self.config_widgets:w.setEnabled(False)
        self.channel_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.start_btn.setEnabled(False);self.stop_btn.setEnabled(True);self.status.setText('Opening capture device…');self.tabs.setCurrentIndex(1)
    def stop(self):
        if self.engine:self.engine.quit.set();self.status.setText('Stopping capture and completing pending clips…');self.stop_btn.setEnabled(False)
    def select_live_channel(self):
        self.live_ch=max(0,self.channel_table.currentRow())
    def tick(self):
        self.poll_names();self.poll_exports()
        if self.player and not self.player.is_alive():
            if self.player.error:self.status.setText(self.player.error)
            self.player=None
        if not self.engine:return
        if not self.engine.is_alive():
            try: self.engine.close_capture()
            except Exception as exc: self.status.setText(f'Driver cleanup failed: {exc}')
        while not self.engine.messages.empty():
            kind,data=self.engine.messages.get_nowait()
            if kind=='event':self.add_event(data)
            elif kind=='warning':self.status.setText(data)
            elif kind=='flag':self.receive_flag(data)
            elif kind=='started':self.status.setText('Demo monitoring active.' if self.active_config['demo'] else 'Live audio monitoring active.')
            elif kind=='stopped':
                for w in self.config_widgets:w.setEnabled(True)
                self.start_btn.setEnabled(True);self.stop_btn.setEnabled(False)
                self.channel_table.setEditTriggers(W.QAbstractItemView.EditTrigger.DoubleClicked|W.QAbstractItemView.EditTrigger.EditKeyPressed)
                self.stats.setText('STOPPED  |  Saved detections remain available')
                self.status.setText(self.engine.error or 'Capture stopped. Pending clips were saved with available post-roll.')
        latest=self.engine.latest
        if latest is None or not self.engine.is_alive():return
        now,f,db,levels,scores,gaps=latest
        if now==self.last_live_time:return
        self.last_live_time=now;ch=min(self.live_ch,len(levels)-1)
        self.draw_multi(now,f,db,levels)
        for i in range(len(levels)):
            for col,text in [(2,f'{levels[i]:.1f}'),(3,f'{scores[i]*100:.0f}%'),(4,'Persistent ringing' if scores[i]>=1 else 'Candidate tone' if scores[i]>.2 else 'Listening')]:
                self.channel_table.item(i,col).setText(text)
            self.channel_table.item(i,4).setForeground(QtGui.QColor('#ffbd69' if scores[i]>.2 else '#69d9c9'))
        prefix='DEMO • GENERATED AUDIO' if self.active_config['demo'] else self.active_config['source']
        self.stats.setText(f'{prefix}  |  {len(levels)} inputs  |  {now:.1f} sec  |  {self.engine.saved} clips saved  |  {gaps} audio gaps')
        if self.engine.error:self.status.setText(self.engine.error)
    def load_events(self):
        files=sorted((ROOT/'events').glob('*.json'))[-500:] if (ROOT/'events').exists() else []
        for p in files:
            try:
                e=json.loads(p.read_text(encoding='utf-8'));e['wav']=str(p.with_suffix('.wav'))
                mix=p.with_suffix('.mix.wav')
                e.pop('mix_wav',None)
                if mix.exists():e['mix_wav']=str(mix)
                if Path(e['wav']).exists():self.add_event(e,redraw=False)
            except (ValueError,KeyError,OSError):continue
        self.update_analytics()
    def add_event(self,e,redraw=True):
        self.event_table.blockSignals(True)
        self.events.append(e)
        if len(self.events)>500:self.events.pop(0);self.event_table.removeRow(self.event_table.rowCount()-1)
        self.event_table.insertRow(0)
        vals=[e['time'],e['source'],f"{e['channel']:02d} / {e['name']}",f"{e['frequency']:.1f}",f"{e['level']:.1f}",f"{e['duration']:.2f}",('DEMO • ' if e['demo'] else 'LIVE • ')+e.get('label','Legacy ringing')]
        for col,val in enumerate(vals):self.event_table.setItem(0,col,W.QTableWidgetItem(str(val)))
        self.event_table.item(0,0).setData(QtCore.Qt.ItemDataRole.UserRole,e)
        self.event_table.blockSignals(False)
        for flag in self.flags:
            if flag.get('event_id')==e['id']:flag['recording_status']='saved'
        for panel in self.flag_panels.values():panel.saved(e)
        if redraw:self.update_analytics()
    def select_event(self):
        row=self.event_table.currentRow()
        if row<0 or not self.event_table.item(row,0):return
        e=self.event_table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole)
        self.stop_playback()
        try:
            self.clip_rate,a=wavfile.read(e['wav'])
            if a.dtype.kind in 'iu':a=a.astype(np.float32)/np.iinfo(a.dtype).max
            if a.ndim>1:a=np.mean(a,axis=1)
            self.clip=np.asarray(a,dtype=np.float32);self.selected_event=e
            self.listen_source.setCurrentIndex(0)
            self.listen_source.model().item(1).setEnabled(bool(e.get('mix_wav')))
            self.center.setMaximum(self.clip_rate*.47);self.center.setValue(e['frequency'])
            stride=max(1,len(a)//14000);self.wave_curve.setData(np.arange(0,len(a),stride)/self.clip_rate,a[::stride]);self.trigger.setValue(e['trigger_seconds'])
            n=min(4096,len(a));f,t,s=spectrogram(a,fs=self.clip_rate,nperseg=n,noverlap=n*3//4,mode='magnitude',scaling='spectrum')
            avg=20*np.log10(np.maximum(np.max(s,axis=1)*2,1e-10));self.review_curve.setData(f[1:],avg[1:]);self.review_spec.setXRange(np.log10(80),np.log10(self.clip_rate*.45));self.review_spec.setYRange(-100,0)
            keep=f<=min(12000,self.clip_rate*.45);z=20*np.log10(np.maximum(s[keep],1e-10))
            dt=t[1]-t[0] if len(t)>1 else n/self.clip_rate;df=f[1]-f[0]
            self.image.setImage(z,autoLevels=False,levels=(-90,-20));self.image.setRect(QtCore.QRectF(float(t[0]-dt/2),-df/2,dt*len(t),df*sum(keep)))
            self.waterfall.setXRange(0,len(a)/self.clip_rate);self.waterfall.setYRange(0,min(12000,self.clip_rate*.45,max(3000,e['frequency']*2)))
            flags=' • partial post-roll' if not e.get('complete_postroll',True) else ''
            if e.get('audio_gap'):flags+=' • audio gap'
            self.review_note.setText(f"{e.get('label','Legacy ringing')} • {'DEMO' if e['demo'] else 'LIVE'} / input {e['channel']} / {e['name']}  •  suspected {e['frequency']:.1f} Hz{flags}")
            self.prepare_review_flags(e)
            self.update_band()
        except Exception as exc:self.clip=None;self.message(f'Could not read event: {exc}')
    def update_band(self):
        lo=max(20,self.center.value()-self.bandwidth.value()/2);hi=min(self.clip_rate*.48,self.center.value()+self.bandwidth.value()/2)
        self.band_marker.setRegion([np.log10(lo),np.log10(max(lo+1,hi))])
    def spectrum_click(self,event):
        if self.clip is None:return
        if self.review_spec.plotItem.vb.sceneBoundingRect().contains(event.scenePos()):
            p=self.review_spec.plotItem.vb.mapSceneToView(event.scenePos());self.center.setValue(float(10**np.clip(p.x(),1,4.4)))
    def play(self):
        if self.clip is None:return self.message('Select a detection clip first.')
        device=self.output.currentData()
        if device is None:return self.message('Select a local headphone output. Console/network audio outputs are excluded.')
        if self.active_config and not self.active_config['demo'] and device==self.active_config['device']:return self.message('Replay cannot use the capture device.')
        if not self.stop_playback():return self.message('Playback is still stopping. Try again shortly.')
        try:
            audio=filtered_audio(self.playback_audio(),self.clip_rate,self.center.value(),self.bandwidth.value(),self.mode.currentText())
            audio=np.clip(audio*10**(self.volume.value()/20),-1,1).astype(np.float32)
            self.player=Player(audio,self.clip_rate,device);self.player.start();self.status.setText(f'Playing {self.mode.currentText().lower()} through selected local output. Capture continues.')
        except Exception as exc:self.message(str(exc))
    def stop_playback(self):
        if self.player:
            self.player.quit.set();self.player.join(timeout=1)
            if self.player.is_alive():return False
            self.player=None
        return True
    def update_analytics(self):
        self.count_plot.clear();self.hist_plot.clear();self.trend.clear()
        if not self.events:return
        n=max(self.channels.value(),max(e['channel'] for e in self.events))
        counts=np.bincount([e['channel'] for e in self.events],minlength=n+1)[1:n+1]
        self.count_plot.addItem(pg.BarGraphItem(x=np.arange(1,n+1),height=counts,width=.65,brush='#56cfc7'))
        self.count_plot.setXRange(.3,n+.7,padding=0)
        edges=np.geomspace(100,20000,21);h,_=np.histogram([e['frequency'] for e in self.events],edges)
        # Place bars directly in logarithmic coordinates; tick labels show Hz.
        le=np.log10(edges)
        self.hist_plot.addItem(pg.BarGraphItem(x=(le[:-1]+le[1:])/2,height=h,width=np.diff(le)*.92,brush='#7d9fff'))
        self.hist_plot.setXRange(le[0],le[-1],padding=.02)
        from datetime import datetime
        times=np.array([datetime.fromisoformat(e['time']).timestamp() for e in self.events]);start=min(times)
        for demo,color in [(True,'#7d9fff'),(False,'#62e2d4')]:
            idx=[i for i,e in enumerate(self.events) if bool(e['demo'])==demo]
            self.trend.plot((times[idx]-start)/60,[self.events[i]['frequency'] for i in idx],pen=None,symbol='o',symbolBrush=color,symbolSize=8)
        self.trend.setTitle('Detection timeline • blue: demo / teal: live')
        self.extra_charts()
    def export_csv(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Export detection summary','feedback-detections.csv','CSV (*.csv)')
        if not path:return
        keys=['time','source','demo','channel','name','label','frequency','level','prominence','duration','audio_gap','wav']
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader()
                for e in self.events:
                    row=dict(e)
                    for k in keys:
                        if isinstance(row.get(k),str) and row[k].startswith(('=','+','-','@')):row[k]="'"+row[k]
                    w.writerow(row)
            self.status.setText('Detection summary exported.')
        except OSError as exc:self.message(str(exc))
    def message(self,text):W.QMessageBox.information(self,'Feedback Watch',text)
    def closeEvent(self,event):
        if self.player:self.player.quit.set()
        if self.engine:self.engine.quit.set()
        if (self.engine and self.engine.is_alive()) or (self.player and self.player.is_alive()) or any(job.is_alive() for job in self.export_jobs):
            self.status.setText('Closing: stopping audio and saving pending clips…')
            event.ignore();QtCore.QTimer.singleShot(150,self.close);return
        if self.engine:
            try:self.engine.close_capture()
            except Exception as exc:
                self.status.setText(f'Driver cleanup failed: {exc}');event.ignore();return
        for panel in list(self.detached.values()):panel.close()
        for panel in self.flag_panels.values():panel.close()
        event.accept()

if __name__=='__main__':
    app=W.QApplication(sys.argv);app.setStyle('Fusion');window=Window();window.show();sys.exit(app.exec())
