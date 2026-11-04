"""Local review, multi-input displays, exports and read-only name import."""
import csv,json,queue,threading,zipfile
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from PySide6 import QtCore,QtGui,QtSvg,QtWidgets as W
import pyqtgraph as pg
import pyqtgraph.exporters
from core import filtered_audio
from console_names import STRIPS,fetch_names
from panels import DetachedPanel,FlagPanel

COLORS=['#62e2d4','#7d9fff','#ffbd69','#eb8dda','#96db70','#f48383','#ded36b','#b3a1ff']

def spin(low,high,value,step=.05):
    w=W.QDoubleSpinBox();w.setRange(low,high);w.setValue(value);w.setSingleStep(step);return w

def table_item(text,editable=False):
    w=W.QTableWidgetItem(str(text))
    if not editable:w.setFlags(w.flags()&~QtCore.Qt.ItemFlag.ItemIsEditable)
    return w

def plot(title,xlabel,ylabel):
    p=pg.PlotWidget(title=title);p.setLabel('bottom',xlabel);p.setLabel('left',ylabel)
    p.showGrid(x=True,y=True,alpha=.15);p.getAxis('bottom').enableAutoSIPrefix(False);return p

class Features:
    def extra_ui(self):
        self.export_jobs=[];self.export_results=queue.Queue();self.detached={};self.flags=[];self.multi_history=[];self.name_results=queue.Queue();self.console_names={}
        self.flag_panels={k:FlagPanel(self,k) for k in ['Early candidate','Persistent ringing']}
        controls=W.QHBoxLayout()
        self.popup_early=W.QCheckBox('Pop up early candidates')
        self.popup_persistent=W.QCheckBox('Pop up persistent ringing');self.popup_persistent.setChecked(True)
        for widget in (self.popup_early,self.popup_persistent):controls.addWidget(widget)
        for kind in self.flag_panels:
            b=W.QPushButton('Open '+kind+' window');b.clicked.connect(lambda checked=False,k=kind:self.flag_panels[k].show());controls.addWidget(b)
        self.tabs.widget(0).layout().insertLayout(1,controls)
        self.early=spin(.05,2,.18);self.gap=spin(0,.3,.10)
        self.adaptive=W.QCheckBox('Require 6 dB emergence above learned background (experimental)')
        self.adaptive.setToolTip('Learns for 1.5 seconds after starting. Start with representative background and no ringing. May miss existing/slow-growing tones.')
        self.record_mix=W.QCheckBox('Record all-input context mix alongside each flagged input');self.record_mix.setChecked(True)
        f=W.QFormLayout();f.addRow('Early candidate persistence (sec)',self.early);f.addRow('Brief-gap tolerance (sec)',self.gap)
        f.addRow(self.adaptive);f.addRow(self.record_mix)
        self.tabs.widget(0).layout().insertLayout(1,f)
        self.config_widgets += [self.early,self.gap,self.adaptive,self.record_mix]
        tools=self.addToolBar('Windows and exports');tools.setMovable(False)
        tools.addAction('Detach current tab',self.detach_current)
        tools.addAction('Reattach all tabs',self.reattach_all)
        tools.addAction('Export…',self.export_menu)
        self.channel_table.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.channel_table.cellChanged.connect(self.local_name_changed)
        self.spec_legend=self.live_spec.addLegend();self.level_legend=self.level_plot.addLegend();self.legend_names=None
        self.multi_curves=[self.live_curve]+[self.live_spec.plot(pen=pg.mkPen(c,width=1.5)) for c in COLORS[1:]]
        self.level_curves=[self.level_curve]+[self.level_plot.plot(pen=pg.mkPen(c,width=1.5)) for c in COLORS[1:]]
        hint=W.QLabel('Ctrl/Shift-click rows to compare up to 8 spectra and level histories. ALL configured inputs are always analyzed.')
        self.tabs.widget(1).layout().insertWidget(1,hint)
        self.listen_source=W.QComboBox();self.listen_source.addItems(['Flagged input only','All monitored inputs together'])
        self.listen_source.setToolTip('The context mix is an arithmetic mean of captured inputs, not the WING main mix. Older clips may not include it.')
        self.tabs.widget(2).layout().insertWidget(1,self.listen_source)
        self.review_flag_selector=W.QComboBox();self.review_flag_selector.currentIndexChanged.connect(self.choose_review_flag)
        self.tabs.widget(2).layout().insertWidget(2,self.review_flag_selector)
        self.review_evidence=W.QLabel('Graphs show the flagged input; the audio source selector affects listening/export only.')
        self.tabs.widget(2).layout().insertWidget(3,self.review_evidence)
        self.type_plot=plot('Saved clips by highest flag type','Flag type','Saved clips')
        self.heat_plot=plot('Input / frequency heatmap • saved clips','Frequency (Hz, logarithmic)','Input slot')
        self.heat_image=pg.ImageItem(axisOrder='row-major');self.heat_plot.addItem(self.heat_image)
        self.heat_image.setLookupTable(pg.colormap.get('viridis').getLookupTable())
        self.heat_plot.getAxis('bottom').setTicks([[(np.log10(v),str(v)) for v in [100,200,500,1000,2000,5000,10000,16000]]])
        self.tabs.widget(3).layout().addWidget(self.type_plot,3,0)
        self.tabs.widget(3).layout().addWidget(self.heat_plot,3,1)
        self.names_ui()
    def extra_config(self):
        return dict(early=self.early.value(),gap=self.gap.value(),adaptive=self.adaptive.isChecked(),
            record_mix=self.record_mix.isChecked(),popup_early=self.popup_early.isChecked(),
            popup_persistent=self.popup_persistent.isChecked(),console_ip=self.console_ip.text().strip(),
            mapping_confirmed=self.mapping_confirm.isChecked(),console_names=self.console_names,
            mapping=[dict(strip=self.name_table.cellWidget(i,1).currentData(),
                          override=self.name_table.item(i,3).text()) for i in range(48)])
    def load_extra(self,c):
        for w,key,default in [(self.early,'early',min(.18,c.get('hold',.45))),(self.gap,'gap',.10)]:w.setValue(c.get(key,default))
        for w,key,default in [(self.adaptive,'adaptive',False),(self.record_mix,'record_mix',True),
                              (self.popup_early,'popup_early',False),(self.popup_persistent,'popup_persistent',True)]:w.setChecked(c.get(key,default))
        self.console_ip.setText(c.get('console_ip',''));self.console_names=c.get('console_names',{})
        self.name_table.blockSignals(True)
        mapping=c.get('mapping',[])
        for i in range(48):
            d=mapping[i] if i<len(mapping) else {}
            combo=self.name_table.cellWidget(i,1)
            strip=d.get('strip',STRIPS[i]);combo.blockSignals(True);combo.setCurrentIndex(max(0,combo.findData(strip)));combo.blockSignals(False)
            legacy=c.get('names',[])
            alias=d.get('override',legacy[i] if i<len(legacy) and legacy[i]!=f'Input {i+1}' else '')
            self.name_table.item(i,3).setText(alias)
        self.name_table.blockSignals(False)
        self.mapping_confirm.setChecked(c.get('mapping_confirmed',False));self.sync_names()
    def names_ui(self):
        page=W.QWidget();self.tabs.addTab(page,'05  Names / mapping');v=W.QVBoxLayout(page)
        note=W.QLabel('Read-only import: 40 channel strips + 8 aux strips. Audio input slots can have any patch, including stereo pairs. Verify each mapping. Local overrides never write to the console. Stop monitoring before changing mappings.');note.setWordWrap(True);v.addWidget(note)
        row=W.QHBoxLayout();self.console_ip=W.QLineEdit();self.console_ip.setPlaceholderText('WING IPv4 address')
        row.addWidget(self.console_ip);self.import_names_btn=W.QPushButton('Fetch names (read only)');self.import_names_btn.clicked.connect(self.import_names);row.addWidget(self.import_names_btn)
        self.names_status=W.QLabel('No console queried.');row.addWidget(self.names_status);v.addLayout(row)
        self.mapping_confirm=W.QCheckBox('I verified these input-slot → console-strip mappings against the audio patch')
        self.mapping_confirm.toggled.connect(self.sync_names);v.addWidget(self.mapping_confirm)
        self.name_table=W.QTableWidget(48,4);self.name_table.setHorizontalHeaderLabels(['Audio input slot','Mapped WING strip','Imported name','Local override (optional)'])
        self.name_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        for i,strip in enumerate(STRIPS):
            self.name_table.setItem(i,0,table_item(i+1));combo=W.QComboBox();combo.addItem('Unmapped',None)
            for candidate in STRIPS:combo.addItem(candidate,candidate)
            combo.setCurrentIndex(i+1);self.name_table.setCellWidget(i,1,combo)
            combo.currentIndexChanged.connect(self.sync_names)
            self.name_table.setItem(i,2,table_item(''));self.name_table.setItem(i,3,table_item('',True))
        self.name_table.cellChanged.connect(self.mapping_edited);v.addWidget(self.name_table)
        b=W.QPushButton('Save names / source profile');b.clicked.connect(self.save_profile);v.addWidget(b)
        self.config_widgets += [self.console_ip,self.import_names_btn,self.name_table,self.mapping_confirm,b]
    def sync_names(self,*args):
        if not hasattr(self,'name_table'):return
        self.channel_table.blockSignals(True)
        for i in range(48):
            strip=self.name_table.cellWidget(i,1).currentData()
            imported=self.console_names.get(strip,'')
            self.name_table.item(i,2).setText(imported)
            alias=self.name_table.item(i,3).text().strip()
            name=alias or (imported if self.mapping_confirm.isChecked() else '') or f'Input {i+1}'
            if i<self.channel_table.rowCount():self.channel_table.item(i,1).setText(name)
        self.channel_table.blockSignals(False)
    def mapping_edited(self,row,col):
        if col==3:self.sync_names()
    def local_name_changed(self,row,col):
        if col!=1 or not hasattr(self,'name_table'):return
        self.name_table.blockSignals(True);self.name_table.item(row,3).setText(self.channel_table.item(row,1).text());self.name_table.blockSignals(False)
    def import_names(self):
        ip=self.console_ip.text().strip();self.import_names_btn.setEnabled(False);self.names_status.setText('Fetching names…')
        def worker():
            try:self.name_results.put((fetch_names(ip),None))
            except Exception as exc:self.name_results.put((None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def poll_names(self):
        try:names,error=self.name_results.get_nowait()
        except queue.Empty:return
        self.import_names_btn.setEnabled(not(self.engine and self.engine.is_alive()))
        if error:self.names_status.setText(error)
        else:
            self.console_names=names;self.sync_names();self.names_status.setText(f'{len(names)}/48 names received. Verify mapping; save profile to retain.')
    def detach_current(self):
        index=self.tabs.currentIndex();page=self.tabs.widget(index)
        if page in self.detached:self.detached[page].show();return
        if index==0:return self.message('Keep Connection in the main window. Live, review, analytics and names can detach.')
        title=self.tabs.tabText(index);self.tabs.removeTab(index)
        placeholder=W.QWidget();layout=W.QVBoxLayout(placeholder);layout.addWidget(W.QLabel(title+' is in a separate window. Close that window to reattach.'))
        self.tabs.insertTab(index,placeholder,title);self.tabs.setCurrentIndex(index)
        panel=DetachedPanel(self,page,title,placeholder);self.detached[placeholder]=panel;panel.show()
    def reattach_all(self):
        for panel in list(self.detached.values()):panel.close()
    def receive_flag(self,flag):
        self.flags.append(flag);self.flags=self.flags[-2000:]
        panel=self.flag_panels[flag['label']];panel.add_flag(flag)
        enabled=self.popup_early if flag['label']=='Early candidate' else self.popup_persistent
        if enabled.isChecked():panel.show()
        self.status.setText(f"{flag['label']} • Input {flag['channel']} / {flag['name']} • {flag['frequency']:.1f} Hz • {flag['level']:.1f} dBFS")
    def review_flag(self,flag):
        for row in range(self.event_table.rowCount()):
            event=self.event_table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole)
            if event['id']==flag.get('event_id'):
                self.event_table.selectRow(row)
                for i in range(self.review_flag_selector.count()):
                    candidate=self.review_flag_selector.itemData(i)
                    if candidate.get('label')==flag.get('label') and abs(candidate['frequency']-flag['frequency'])<1:
                        self.review_flag_selector.setCurrentIndex(i);break
                self.center.setValue(flag['frequency']);self.tabs.setCurrentIndex(2)
                for panel in self.detached.values():
                    if panel.page.isAncestorOf(self.event_table):panel.show();panel.raise_()
                return
        self.message('This clip is still being recorded, was not saved, or is outside the latest 500 loaded clips.')
    def draw_multi(self,now,f,db,levels):
        self.multi_history.append((now,levels.copy()));self.multi_history=[p for p in self.multi_history if p[0]>=now-30]
        selected=sorted({i.row() for i in self.channel_table.selectionModel().selectedRows()})[:8] or [self.live_ch]
        selected=[i for i in selected if i<len(levels)]
        legend_names=tuple((ch,self.active_config['names'][ch]) for ch in selected)
        rebuild=legend_names!=self.legend_names
        if rebuild:self.spec_legend.clear();self.level_legend.clear();self.legend_names=legend_names
        for idx,(spectrum,level) in enumerate(zip(self.multi_curves,self.level_curves)):
            if idx>=len(selected):spectrum.clear();level.clear();continue
            ch=selected[idx];name=f"{ch+1}: {self.active_config['names'][ch]}"
            spectrum.setData(f[1:],db[1:,ch]);level.setData([t for t,a in self.multi_history],[a[ch] for t,a in self.multi_history])
            if rebuild:self.spec_legend.addItem(spectrum,name);self.level_legend.addItem(level,name)
        self.live_spec.setTitle(f'Live spectra • {len(selected)} displayed / {len(levels)} inputs analyzed')
    def playback_audio(self):
        if self.listen_source.currentIndex()==0:return self.clip
        path=self.selected_event.get('mix_wav')
        if not path:raise ValueError('This older clip has no all-input context mix.')
        rate,a=wavfile.read(path)
        if rate!=self.clip_rate:raise ValueError('Context mix sample rate does not match the input clip.')
        if a.dtype.kind in 'iu':a=a.astype(np.float32)/np.iinfo(a.dtype).max
        return np.asarray(a,dtype=np.float32)
    def extra_charts(self):
        kinds=['Early candidate','Persistent ringing','Legacy ringing'];counts=[sum(e.get('label','Legacy ringing')==k for e in self.events) for k in kinds]
        self.type_plot.clear();self.type_plot.addItem(pg.BarGraphItem(x=np.arange(3),height=counts,width=.6,brush='#ffbd69'))
        self.type_plot.getAxis('bottom').setTicks([list(enumerate(kinds))])
        bins=np.geomspace(100,16000,33);n=max(48,max((e['channel'] for e in self.events),default=1))
        heat=np.zeros((n,32))
        for e in self.events:
            frequency_bins={int(np.searchsorted(bins,flag['frequency'],side='right')-1) for flag in (e.get('flags',[]) or [e])}
            for j in frequency_bins:
                if 0<=j<32:heat[e['channel']-1,j]+=1
        self.heat_image.setImage(heat,levels=(0,max(1,float(heat.max()))))
        self.heat_image.setRect(QtCore.QRectF(np.log10(bins[0]),.5,np.log10(bins[-1]/bins[0]),n))
    def export_menu(self):
        menu=W.QMenu(self)
        actions=[('Saved clips CSV',self.export_csv),('Saved clips JSON',self.export_events_json),('Flag log CSV',self.export_flags_csv),
                 ('Selected audio WAV…',self.export_audio),('Loaded clips + metadata ZIP',self.export_bundle),('Chart PNG / SVG…',self.export_chart)]
        for label,fn in actions:menu.addAction(label,fn)
        menu.exec(self.cursor().pos())
    def export_events_json(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Export loaded clip metadata','feedback-clips.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(self.events,indent=2),encoding='utf-8')
            except Exception as exc:self.message(str(exc))
    def export_flags_csv(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Export flag history (latest 2000 this run)','feedback-flags.csv','CSV (*.csv)')
        if not path:return
        keys=['time','source','demo','channel','name','label','frequency','level','prominence','baseline_excess','growth_db_sec','frequency_spread','observed_seconds','event_id','recording_status']
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader()
                for flag in self.flags:
                    row=dict(flag)
                    for k,v in row.items():
                        if isinstance(v,str) and v.startswith(('=','+','-','@')):row[k]="'"+v
                    writer.writerow(row)
        except Exception as exc:self.message(str(exc))
    def export_audio(self):
        if self.clip is None:return self.message('Select a saved clip first.')
        path,_=W.QFileDialog.getSaveFileName(self,'Export selected source and playback filter (without replay attenuation)','feedback-review.wav','WAV (*.wav)')
        if not path:return
        try:
            audio=filtered_audio(self.playback_audio(),self.clip_rate,self.center.value(),self.bandwidth.value(),self.mode.currentText())
            wavfile.write(path,self.clip_rate,audio.astype(np.float32))
        except Exception as exc:self.message(str(exc))
    def export_bundle(self):
        path,_=W.QFileDialog.getSaveFileName(self,'Export up to 500 loaded clips and metadata','feedback-clips.zip','ZIP (*.zip)')
        if not path:return
        events=json.loads(json.dumps(self.events));flags=json.loads(json.dumps(self.flags))
        self.status.setText('Exporting loaded clips in the background; analysis continues…')
        def worker():
            try:
                with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                    for e in events:
                        for key in ('wav','mix_wav'):
                            if e.get(key):
                                p=Path(e[key]);relative='audio/'+p.name;z.write(p,relative);e[key]=relative
                    z.writestr('clips.json',json.dumps(events,indent=2));z.writestr('flags-this-run.json',json.dumps(flags,indent=2))
                    z.writestr('README.txt','Input clips and synchronized arithmetic-mean context mixes. Not the console main mix. Labels indicate suspected ringing. Metadata includes local device labels. Flags cover only this app run.\n')
                self.export_results.put((True,'Clip bundle exported.'))
            except Exception as exc:self.export_results.put((False,'Export failed: '+str(exc)))
        job=threading.Thread(target=worker,daemon=True);self.export_jobs.append(job);job.start()
    def export_chart(self):
        charts={'Live spectrum':self.live_spec,'Input levels':self.level_plot,'Clip waveform':self.wave,'Clip spectrum':self.review_spec,'Clip spectrogram':self.waterfall,
                'Clips by input':self.count_plot,'Frequency histogram':self.hist_plot,'Timeline':self.trend,'Flag types':self.type_plot,'Input-frequency heatmap':self.heat_plot}
        title,ok=W.QInputDialog.getItem(self,'Export chart','Chart',list(charts),0,False)
        if not ok:return
        path,kind=W.QFileDialog.getSaveFileName(self,'Export chart','feedback-chart.png','PNG (*.png);;SVG (*.svg)')
        if not path:return
        try:
            if path.lower().endswith('.svg'):
                widget=charts[title];generator=QtSvg.QSvgGenerator();generator.setFileName(path)
                generator.setSize(widget.size());generator.setViewBox(widget.rect())
                painter=QtGui.QPainter(generator)
                try:widget.render(painter)
                finally:painter.end()
            else:pg.exporters.ImageExporter(charts[title].plotItem).export(path)
        except Exception as exc:self.message(str(exc))

    def poll_exports(self):
        self.export_jobs=[job for job in self.export_jobs if job.is_alive()]
        try:ok,message=self.export_results.get_nowait()
        except queue.Empty:return
        self.status.setText(message)

    def prepare_review_flags(self,event):
        self.review_flag_selector.blockSignals(True);self.review_flag_selector.clear()
        for flag in event.get('flags',[]) or [event]:
            self.review_flag_selector.addItem(f"{flag.get('label','Legacy ringing')} • {flag['frequency']:.1f} Hz",flag)
        self.review_flag_selector.blockSignals(False)
        self.choose_review_flag()
    def choose_review_flag(self,*args):
        flag=self.review_flag_selector.currentData()
        if not flag:return
        self.center.setValue(flag['frequency'])
        e=self.selected_event
        self.review_note.setText(f"{flag.get('label','Legacy ringing')} • {'DEMO' if e['demo'] else 'LIVE'} • input {e['channel']} / {e['name']} • {flag['frequency']:.1f} Hz"+(' • partial clip' if not e.get('complete_postroll',True) else '')+(' • audio gap' if e.get('audio_gap') else ''))
        if 'baseline_excess' in flag:
            self.review_evidence.setText(f"Background emergence: {flag['baseline_excess']:.1f} dB • growth: {flag['growth_db_sec']:.1f} dB/sec • tracked spread: {flag['frequency_spread']:.1f} Hz. Diagnostic measurements, not feedback probabilities. Graphs show the flagged input.")
        else:self.review_evidence.setText('Graphs show the flagged input. Listening/export can use its unfiltered clip or the all-input context mix.')
