"""Desktop tools for original ROM mode. All calculator operations run in ROM."""
from pathlib import Path
import re
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QColor,QSyntaxHighlighter,QTextCharFormat,QFontDatabase
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QPlainTextEdit,
    QFileDialog,QInputDialog,QTreeWidget,QTreeWidgetItem,QComboBox,QListWidget,QMessageBox)
from .rom_codec import quote_name,quote_text
from .rom_backups import atomic_bytes


def display_number(value):
    text=format(value,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def row_buttons(layout,items):
    row=QHBoxLayout();layout.addLayout(row)
    for label,callback in items:
        button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)


class RplHighlighter(QSyntaxHighlighter):
    def highlightBlock(self,text):
        for pattern,color in [(r'\b(IF|THEN|ELSE|END|IFERR|FOR|NEXT|STEP|START|WHILE|REPEAT|DO|UNTIL|CASE|HALT)\b','#075caa'),
                              (r'[«»{}]|→','#9d3e93'),(r'\b\d+(?:\.\d+)?\b','#986000'),
                              (r'"(?:[^"\\]|\\.)*"', '#25783c'),(r"'[^']*'",'#25783c')]:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color))
            for match in re.finditer(pattern,text):self.setFormat(match.start(),len(match.group()),fmt)


class RomProgramEditor(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.path=None
        self.setWindowTitle('Original HP program editor');self.resize(760,550)
        layout=QVBoxLayout(self)
        self.editor=QPlainTextEdit();self.editor.setDocument(window.editor.document())
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont));layout.addWidget(self.editor)
        self.highlighter=RplHighlighter(self.editor.document())
        self.status=QLabel('Source is saved as a draft automatically. Syntax checking uses the HP ROM.');self.status.setWordWrap(True);layout.addWidget(self.status)
        row_buttons(layout,[('Open…',self.open_file),('Save',self.save_file),('Save as…',lambda:self.save_file(True)),('Check syntax',self.check)])
        row_buttons(layout,[('Add to stack',self.add),('Run',self.run),('Source debugger',self.source_debug),('Debug on LCD',self.debug),('Step',self.step),('Continue',self.resume),('Stop',self.stop)])
    def program(self):
        source=self.editor.toPlainText().strip()
        if not source:raise ValueError('Enter a program first')
        return source if source.startswith('«') and source.endswith('»') else '«\n'+source+'\n»'
    def submitted(self,source):
        try:self.window.session.execute(source);self.status.setText('Submitted. Results, errors and debugging controls appear on the LCD.')
        except Exception as exc:self.status.setText(str(exc))
    def add(self):
        try:self.submitted(self.program())
        except Exception as exc:self.status.setText(str(exc))
    def run(self):
        try:self.submitted(self.program()+' EVAL')
        except Exception as exc:self.status.setText(str(exc))
    def source_debug(self):
        from .rom_debugger import SourceDebugger
        self.debugger=SourceDebugger(self.window,self.editor.toPlainText());self.debugger.show()
    def debug(self):
        try:
            self.window.session.execute(self.program()+' 41 MENU',lambda ok:self.window.session.tap(0) if ok else None)
            self.status.setText('Use Step or the LCD’s SST/SST↓ controls. Continue resumes the halted program.')
        except Exception as exc:self.status.setText(str(exc))
    def step(self):
        if self.window.session:self.window.session.tap(1)
    def resume(self):
        if self.window.session:
            self.window.session.tap(34);QTimer.singleShot(160,lambda:self.window.session.tap(44) if self.window.session else None)
    def stop(self):
        if self.window.session:
            self.window.session.tap(44)
            QTimer.singleShot(250,lambda:self.submitted('KILL') if self.window.session else None)
    def check(self):
        try:
            self.window.query(quote_text(self.program())+' STR→ DROP "Syntax OK"',
                              lambda value:self.status.setText(str(value)))
        except Exception as exc:self.status.setText(str(exc))
    def preserve_draft(self):self.window.save_draft(archive=True)
    def open_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Open HP source','','HP source (*.rpl *.txt);;All files (*)')
        if path:
            try:
                if Path(path).stat().st_size>100000:raise ValueError('Source exceeds 100 KB')
                text=Path(path).read_text(encoding='utf-8-sig');self.preserve_draft()
                self.editor.setPlainText(text);self.path=Path(path);self.status.setText(f'Opened {self.path.name}; not executed.')
            except Exception as exc:self.status.setText(str(exc))
    def save_file(self,save_as=False):
        path=self.path
        if save_as or path is None:
            selected,_=QFileDialog.getSaveFileName(self,'Save HP source',str(path or 'program.rpl'),'HP source (*.rpl *.txt)')
            if not selected:return
            path=Path(selected)
        try:
            atomic_bytes(path,self.editor.toPlainText().encode());self.path=path
            self.editor.document().setModified(False);self.status.setText(f'Saved {path.name}')
        except Exception as exc:self.status.setText(str(exc))
    def closeEvent(self,event):self.preserve_draft();event.accept()


class BackupDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Calculator backups');self.resize(660,400)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Automatic recovery points: every minute, newest 10 retained. Named backups are kept.'))
        self.list=QListWidget();layout.addWidget(self.list)
        row_buttons(layout,[('Create named backup…',self.create),('Restore selected',self.restore),('Import…',self.import_file),('Export…',self.export),('Refresh',self.refresh)])
        self.refresh()
    def refresh(self):
        self.list.clear()
        for path in self.window.backups.entries():self.list.addItem(path.name)
    def selected(self):
        item=self.list.currentItem()
        return self.window.backups.directory/item.text() if item else None
    def create(self):
        label,ok=QInputDialog.getText(self,'Name backup','Name:')
        if ok:self.window.make_backup(label or 'Snapshot',callback=lambda _:self.refresh())
    def restore(self):
        path=self.selected()
        if path:self.window.restore_backup(path)
    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Import backup','','Calculator backups (*.hp48state)')
        if path:
            try:self.window.backups.import_file(path);self.refresh()
            except Exception as exc:self.window.problem(str(exc))
    def export(self):
        source=self.selected()
        if not source:return
        path,_=QFileDialog.getSaveFileName(self,'Export backup',source.name,'Calculator backups (*.hp48state)')
        if path:
            try:atomic_bytes(path,self.window.backups.validated_bytes(source))
            except Exception as exc:self.window.problem(str(exc))


TYPES={0:'Real',1:'Complex',2:'String',3:'Real array',4:'Complex array',5:'List',6:'Name',8:'Program',
       9:'Algebraic',10:'Binary integer',11:'Graphic',12:'Tagged',13:'Unit',14:'Library command',15:'Directory',16:'Library',17:'Backup'}


class MemoryBrowser(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Calculator memory');self.resize(750,550)
        layout=QVBoxLayout(self);self.location=QLabel();layout.addWidget(self.location)
        self.scope=QComboBox();self.scope.addItems(['Current directory','Port 0','Port 1','Port 2']);layout.addWidget(self.scope)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['Name','Type','Bytes']);layout.addWidget(self.tree)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);self.preview.setMaximumHeight(110);layout.addWidget(self.preview)
        row_buttons(layout,[('Refresh',self.refresh),('HOME',lambda:self.navigate('HOME')),('Up',lambda:self.navigate('UPDIR')),
                            ('Enter directory',self.enter),('New directory…',self.new_directory)])
        row_buttons(layout,[('View',self.view),('Recall to stack',self.recall),('Edit source',self.edit),('Store level 1…',self.store),('Rename…',self.rename),('Delete',self.delete)])
        row_buttons(layout,[('Install library from level 1…',self.install_library),('Attach library…',lambda:self.library_action('ATTACH')),('Detach library…',lambda:self.library_action('DETACH'))])
        self.tree.itemDoubleClicked.connect(lambda *_:self.view());self.scope.currentIndexChanged.connect(self.refresh)
        self.refresh()
    def query(self,source,callback):self.window.query(source,callback)
    def refresh(self):
        if self.scope.currentIndex()==0:
            source='PATH →STR VARS 1 « DUP RCL DUP TYPE SWAP BYTES SWAP DROP 3 →LIST » DOLIST LIBS MEM 4 →LIST'
            def show(value):
                path,rows,libraries,free=value;self.location.setText(f'{path} — {display_number(free)} bytes free')
                self.tree.clear()
                for name,kind,size in rows:
                    item=QTreeWidgetItem([str(name),TYPES.get(int(kind),str(kind)),display_number(size)]);item.setData(0,Qt.ItemDataRole.UserRole,int(kind));self.tree.addTopLevelItem(item)
                self.preview.setPlainText('Attached libraries: '+str(libraries) if libraries else 'No libraries attached to this directory.')
        else:
            port=self.scope.currentIndex()-1
            source=f'{port} PVARS SWAP 1 « →STR » DOLIST SWAP 2 →LIST'
            def show(value):
                rows,free=value;self.location.setText(f'Port {port} — {free}');self.tree.clear()
                for name in rows:self.tree.addTopLevelItem(QTreeWidgetItem([name,'Port object','']))
        self.query(source,show)
    def selected(self):
        item=self.tree.currentItem()
        if not item:raise ValueError('Select an object first')
        name=item.text(0)
        if self.scope.currentIndex():
            if not re.fullmatch(r':[012]:[A-Za-z0-9_]+',name):raise ValueError('Use the calculator to address this port object')
            return name
        return quote_name(name)
    def guarded(self,action):
        try:action()
        except Exception as exc:self.window.problem(str(exc))
    def navigate(self,source):
        self.scope.blockSignals(True);self.scope.setCurrentIndex(0);self.scope.blockSignals(False);self.action(source)
    def target(self,name):
        literal=quote_name(name)
        return f':{self.scope.currentIndex()-1}:{name}' if self.scope.currentIndex() else literal
    def action(self,source):self.query(source+' "OK"',lambda _:self.refresh())
    def enter(self):
        def perform():
            item=self.tree.currentItem()
            if item is None or item.data(0,Qt.ItemDataRole.UserRole)!=15:raise ValueError('Select a directory')
            self.action(self.selected()+' EVAL')
        self.guarded(perform)
    def new_directory(self):
        name,ok=QInputDialog.getText(self,'Create directory','Name:')
        if ok:self.guarded(lambda:self.navigate(quote_name(name)+' CRDIR'))
    def view(self):self.guarded(lambda:self.query(self.selected()+' RCL →STR',lambda text:self.preview.setPlainText(text)))
    def recall(self):self.guarded(lambda:self.window.session.execute(self.selected()+' RCL'))
    def edit(self):
        def show(text):self.window.save_draft(archive=True);self.window.editor.setPlainText(text);self.window.open_program_editor()
        self.guarded(lambda:self.query(self.selected()+' RCL →STR',show))
    def store(self):
        name,ok=QInputDialog.getText(self,'Store stack level 1','Variable name:')
        if ok:
            def perform():
                target=self.target(name)
                self.window.make_backup('Before store',lambda ok:self.query(lambda saved:f'{saved} DUP SIZE GET {target} STO "OK"',lambda _:self.refresh()) if ok else None)
            self.guarded(perform)
    def rename(self):
        name,ok=QInputDialog.getText(self,'Rename variable','New name:')
        if ok:
            def perform():
                old=self.selected();new=self.target(name)
                listing=f'{self.scope.currentIndex()-1} PVARS DROP' if self.scope.currentIndex() else 'VARS'
                self.action(f'IF {listing} {new} POS THEN "Name already exists" DOERR END {old} RCL {new} STO {old} PURGE')
            self.guarded(perform)
    def delete(self):
        def perform():
            target=self.selected()
            self.window.make_backup('Before delete',lambda ok:self.action(target+' PURGE') if ok else None)
        self.guarded(perform)

    def install_library(self):
        port,ok=QInputDialog.getInt(self,'Install library from level 1','Port (0 = main memory, 1/2 = RAM cards):',max(0,self.scope.currentIndex()-1),0,2)
        if ok:
            self.window.make_backup('Before library install',lambda saved:self.query(
                lambda stack:f'{stack} DUP SIZE GET IF DUP TYPE 16 ≠ THEN "Level 1 must be a library" DOERR END {port} STO "OK"',
                lambda _:self.refresh()) if saved else None)
    def library_action(self,command):
        number,ok=QInputDialog.getInt(self,command.title()+' library','Library number:',0,0,2047)
        if ok:self.action(f'{number} {command}')
