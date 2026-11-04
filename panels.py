from PySide6 import QtCore,QtWidgets as W

class DetachedPanel(W.QDialog):
    def __init__(self,owner,page,title,placeholder):
        super().__init__(owner,QtCore.Qt.WindowType.Window)
        self.owner=owner;self.page=page;self.placeholder=placeholder
        self.setWindowTitle(title+' — WING Feedback Watch');self.resize(1100,800)
        layout=W.QVBoxLayout(self);layout.addWidget(page)
    def closeEvent(self,event):
        index=self.owner.tabs.indexOf(self.placeholder)
        if index>=0:
            self.layout().removeWidget(self.page)
            title=self.owner.tabs.tabText(index);self.owner.tabs.removeTab(index)
            self.owner.tabs.insertTab(index,self.page,title);self.owner.tabs.setCurrentIndex(index)
        self.owner.detached.pop(self.placeholder,None)
        event.accept()

class FlagPanel(W.QDialog):
    def __init__(self,owner,kind):
        super().__init__(owner,QtCore.Qt.WindowType.Window)
        self.setWindowTitle(kind+' — WING Feedback Watch');self.resize(850,380)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        layout=W.QVBoxLayout(self)
        layout.addWidget(W.QLabel(kind+' • suspected ringing, not confirmed feedback. Double-click to review its saved clip.'))
        self.table=W.QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(['Time','Input / name','Frequency Hz','Tone dBFS','Recording'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(lambda row,col:owner.review_flag(self.table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.table)
    def add_flag(self,flag):
        self.table.insertRow(0)
        vals=[flag['time'],f"{flag['channel']} / {flag['name']}",f"{flag['frequency']:.1f}",f"{flag['level']:.1f}",flag.get('recording_status','unknown')]
        for col,value in enumerate(vals):self.table.setItem(0,col,W.QTableWidgetItem(str(value)))
        self.table.item(0,0).setData(QtCore.Qt.ItemDataRole.UserRole,flag)
        if self.table.rowCount()>500:self.table.removeRow(500)
    def saved(self,event):
        for row in range(self.table.rowCount()):
            flag=self.table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole)
            if flag.get('event_id')==event['id']:self.table.item(row,4).setText('Saved')
