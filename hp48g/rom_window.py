"""Original HP 48GX ROM mode: Python/Qt UI around the Saturn subprocess."""
from pathlib import Path
import sys
import json
from PySide6.QtCore import Qt, QProcess, QStandardPaths, QRect, QSize, Signal, QTimer, QMimeData, QEvent
from PySide6.QtGui import QImage, QPainter, QColor, QAction
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QPlainTextEdit, QFileDialog, QMessageBox, QApplication, QInputDialog, QToolButton, QDockWidget)
from .rom_session import RomSession
from .rom_codec import import_binary, export_binary
from .rom_backups import Backups, atomic_bytes

SHIFT_LABELS = {6:('RAD','POLAR'),7:('', 'CHARS'),8:('', 'MODES'),9:('', 'MEMORY'),10:('', 'STACK'),11:('PREV','MENU'),
    12:('UPDIR','HOME'),13:('DEF','RCL'),14:('→NUM','UNDO'),15:('PICTURE',''),16:('VIEW',''),17:('SWAP',''),
    18:('ASIN','∂'),19:('ACOS','∫'),20:('ATAN','Σ'),21:('SQ','ROOT'),22:('10ˣ','LOG'),23:('eˣ','LN'),
    24:('EQUATION','MATRIX'),25:('EDIT','CMD'),26:('PURG','ARG'),27:('CLEAR',''),28:('DROP',''),29:('USER','ENTRY'),
    30:('SOLVE','SOLVE'),31:('PLOT','PLOT'),32:('SYMBOLIC','SYMBOLIC'),33:('( )','#'),35:('TIME','TIME'),
    36:('STAT','STAT'),37:('UNITS','UNITS'),38:('[ ]','_'),40:('I/O','I/O'),41:('LIBRARY','LIBRARY'),
    42:('EQ LIB','EQ LIB'),43:('« »','" "'),44:('CONT','OFF'),45:('=','→'),46:(',','↵'),47:('π','∠'),48:('{ }',': :')}

LABELS = ['A','B','C','D','E','F','MTH','PRG','CST','VAR','↑','NXT',"'",'STO','EVAL','←','↓','→',
          'SIN','COS','TAN','√','yˣ','1/x','ENTER','+/−','EEX','DEL','⌫','α','7','8','9','÷',
          '⇧ left','4','5','6','×','⇧ right','1','2','3','−','ON','0','.','SPC','+']


def default_directory():
    from .data_paths import data_directory
    return data_directory()/'original-hp48'


class LCD(QWidget):
    menuActivated = Signal(int)
    choiceActivated = Signal(int)
    choiceScrolled = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(393,192)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.pixels = bytes(1088)
        self.powered = False
        self._pressed_menu = None
        self.choice=None;self._pressed_choice=None

    def update_frame(self, data):
        self.pixels = bytes.fromhex(data['frame'])
        self.powered = data['on']
        from .rom_menu import choice_list
        self.choice=choice_list(self.pixels) if self.powered else None
        if not self.powered:
            self._pressed_menu = None
            self.unsetCursor()
            self.setToolTip('')
        self.update()

    def display_rect(self):
        size = QSize(131,64).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width()-size.width())//2,(self.height()-size.height())//2,
                     size.width(),size.height())

    def menu_at(self, position):
        rect = self.display_rect()
        if not self.powered or not rect.contains(position.toPoint()):
            return None
        x = (position.x()-rect.x())*131/rect.width()
        y = (position.y()-rect.y())*64/rect.height()
        # HP's six soft-key labels occupy the bottom seven LCD pixel rows.
        if 0 <= x < 131 and 57 <= y < 64:
            return min(int(x//22),5)
        return None

    def choice_at(self,position):
        rect=self.display_rect()
        if not self.choice or not rect.contains(position.toPoint()):return None
        return self.choice.row_at((position.x()-rect.x())*131/rect.width(),(position.y()-rect.y())*64/rect.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_menu = self.menu_at(event.position())
            row=self.choice_at(event.position())
            self._pressed_choice=(self.choice,row) if row is not None else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            menu = self.menu_at(event.position())
            if menu is not None and menu == self._pressed_menu:
                self.menuActivated.emit(menu)
            row=self.choice_at(event.position())
            if row is not None and self._pressed_choice==(self.choice,row):
                self.choiceActivated.emit(row-self.choice.selected)
            self._pressed_menu = None;self._pressed_choice=None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        menu = self.menu_at(event.position())
        row=self.choice_at(event.position())
        if row is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click to choose this option; scroll to browse the list")
        elif menu is None:
            self.unsetCursor()
            self.setToolTip('')
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f'Click to select menu {chr(65+menu)}')
        super().mouseMoveEvent(event)

    def wheelEvent(self,event):
        if self.choice and self.choice_at(event.position()) is not None:
            delta=event.angleDelta().y()
            if delta:self.choiceScrolled.emit(-1 if delta>0 else 1)
            event.accept();return
        super().wheelEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self); painter.fillRect(self.rect(), QColor('#a5b394'))
        image = QImage(self.pixels,131,64,17,QImage.Format.Format_Mono)
        image.setColorTable([QColor('#a5b394').rgba(),QColor('#34483e').rgba()])
        painter.drawImage(self.display_rect(),image)


class RomWindow(QMainWindow):
    def __init__(self, directory=None, parent=None):
        super().__init__(parent)
        self.directory = Path(directory or default_directory()).resolve(); self.directory.mkdir(parents=True,exist_ok=True)
        self.backups=Backups(self.directory);self.pending_restore=None
        self.session = None; self.done = False; self.setup = None; self.held = set()
        self.setWindowTitle('HP 48GX · Original ROM R')
        from .rom_skin import CASE_STYLE,key_cell,PrintedLogo
        central=QWidget();central.setObjectName('calculatorCase');central.setStyleSheet(CASE_STYLE)
        self.setCentralWidget(central)
        shell=QVBoxLayout(central);shell.setContentsMargins(13,13,13,13)
        face=QWidget();face.setObjectName('faceplate');shell.addWidget(face)
        layout=QVBoxLayout(face);self.face_layout=layout;layout.setContentsMargins(18,14,18,12);layout.setSpacing(6)
        header=QHBoxLayout();layout.addLayout(header)
        brand=PrintedLogo(Path(__file__).parent/'assets'/'hp-logo.png');brand.setObjectName('brand');header.addWidget(brand)
        self.title=QLabel('48GX');self.title.setObjectName('model');header.addWidget(self.title)
        header.addStretch()
        badge=QLabel('▰ ▰\nSCIENTIFIC GRAPHING');badge.setObjectName('badge');badge.setAlignment(Qt.AlignmentFlag.AlignRight);header.addWidget(badge)
        bezel=QWidget();bezel.setObjectName('screenBezel');screen=QVBoxLayout(bezel);screen.setContentsMargins(11,10,11,13);screen.setSpacing(0)
        self.ann=QLabel('');self.ann.setObjectName('annunciators');self.ann.setFixedHeight(15);screen.addWidget(self.ann)
        self.lcd=LCD();screen.addWidget(self.lcd);layout.addWidget(bezel)
        self.lcd.choiceActivated.connect(self.select_lcd_choice)
        self.lcd.choiceScrolled.connect(lambda steps:self.select_lcd_choice(steps,False))
        self.selecting_choice=False
        self.lcd.menuActivated.connect(lambda index:self.session.tap(index) if self.session else None)
        grid=QGridLayout();grid.setHorizontalSpacing(7);grid.setVerticalSpacing(2);layout.addLayout(grid);self.buttons=[]
        for col in range(30):grid.setColumnStretch(col,1)
        for index,label in enumerate(LABELS):
            alpha=chr(65+index) if index<24 else {25:'Y',26:'Z'}.get(index,'')
            left,right=SHIFT_LABELS.get(index,('',''))
            # Keep legends visible even while the selected shift changes the key action.
            shown={34:'↰',39:'↱',10:'▲',15:'◀',16:'▼',17:'▶'}.get(index,'' if index<6 else label)
            cell,button=key_cell(index,shown,left.replace('<','&lt;'),right.replace('<','&lt;'),alpha)
            button.setAccessibleName(label)
            button.setToolTip(f'{label} · Left shift: {left or "—"} · Right shift: {right or "—"} · Alpha: {alpha or "—"}')
            button.pressed.connect(lambda i=index:self.session.key(i,True) if self.session else None)
            button.released.connect(lambda i=index:self.session.key(i,False) if self.session else None)
            if index<24:row,col,span=index//6,(index%6)*5,5
            elif index<29:row,col,span=4,(0 if index==24 else (index-23)*5),(10 if index==24 else 5)
            else:row,col,span=5+(index-29)//5,((index-29)%5)*6,6
            grid.addWidget(cell,row,col,1,span);self.buttons.append(button)
        self.status=QLabel('Preparing original calculator…');self.status.setObjectName('calculatorStatus');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.entry_toggle=QToolButton();self.entry_toggle.setObjectName('entryToggle');self.entry_toggle.setText('Source entry & file transfer')
        self.entry_toggle.setCheckable(True);self.entry_toggle.setArrowType(Qt.ArrowType.RightArrow);self.entry_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);layout.addWidget(self.entry_toggle)
        self.entry_panel=QWidget();entry_layout=QVBoxLayout(self.entry_panel);entry_layout.setContentsMargins(0,0,0,0)
        self.editor=QPlainTextEdit();self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.editor.setObjectName('sourceEntry');self.editor.setPlaceholderText('HP source, for example: 0 1 10 FOR i i + NEXT\nUse « » for programs.');self.editor.setMaximumHeight(85)
        entry_layout.addWidget(self.editor)
        controls=QHBoxLayout();entry_layout.addLayout(controls)
        for label,action in [('Run text',self.run_text),('Import object',self.import_object),('Export level 1',self.export_object),('Save memory',self.save)]:
            button=QPushButton(label);button.clicked.connect(action);controls.addWidget(button)
        layout.addWidget(self.entry_panel);self.entry_panel.hide()
        self.entry_toggle.toggled.connect(self.toggle_entry)
        menu=self.menuBar().addMenu('File')
        menu.addAction('Open another ROM profile…',self.open_profile)
        menu.addAction('Use local HP48 ROM…',self.choose_rom)
        menu.addAction('Download ROM revision…',self.download_revision)
        menu.addAction('Load HP source…',self.load_source)
        menu.addAction('Keyboard help',self.help)
        tools=self.menuBar().addMenu('Tools')
        tools.addAction('Enhanced tools',self.open_enhanced)
        tools.addAction('Program editor…',self.open_program_editor)
        tools.addAction('Memory browser…',self.open_memory)
        tools.addAction('Graph tools…',self.open_graph)
        tools.addAction('Backups and restore…',self.open_backups)
        tools.addAction('Memory cards…',self.open_cards)
        tools.addAction('Background alarms and reminders…',lambda:self.background.dialog())
        tools.addAction('Emulator speed…',self.set_speed)
        clipboard=self.menuBar().addMenu('Clipboard')
        clipboard.addAction('Copy stack level 1',self.copy_stack)
        clipboard.addAction('Paste into editor',self.paste_editor)
        clipboard.addAction('Paste copied HP object to stack',self.paste_object)
        clipboard.addAction('Copy LCD image',self.copy_lcd)
        sound=self.menuBar().addMenu('Sound')
        from .rom_audio import RomAudio
        self.audio=RomAudio(self);self.audio.unavailable.connect(self.status.setText)
        self.sound_action=sound.addAction('Enable sound');self.sound_action.setCheckable(True);self.sound_action.setChecked(True)
        self.sound_action.toggled.connect(self.set_sound)
        sound.addAction('Volume…',self.set_volume)
        sound.addAction('Test sound',lambda:self.audio.play({'frequency':440,'duration':.25}))
        help_menu=self.menuBar().addMenu('Help')
        about_action=QAction('About HP 48GX Calculator',self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.about)
        help_menu.addAction(about_action)
        self.autosave_timer=QTimer(self);self.autosave_timer.setInterval(60000);self.autosave_timer.timeout.connect(self.autosave)
        from .rom_background import BackgroundService
        self.background=BackgroundService(self)
        self.draft_timer=QTimer(self);self.draft_timer.setSingleShot(True);self.draft_timer.setInterval(750);self.draft_timer.timeout.connect(self.save_draft)
        draft=self.directory/'editor-draft.rpl'
        if draft.exists():self.editor.setPlainText(draft.read_text(encoding='utf-8'))
        self.editor.textChanged.connect(lambda:self.draft_timer.start())
        self.speed=0
        prefs={}
        try:
            prefs=json.loads((self.directory/'desktop.json').read_text())
            self.speed=prefs.get('speed',0) if prefs.get('speed',0) in (0,250000,500000,1000000) else 0
            try:self.background.set_enabled(bool(prefs.get('background',False)))
            except ValueError:pass
            self.sound_action.blockSignals(True)
            self.sound_action.setChecked(bool(prefs.get('sound',True)))
            self.audio.set_enabled(self.sound_action.isChecked());self.audio.set_volume(float(prefs.get('volume',.35)))
            self.sound_action.blockSignals(False)
        except (OSError,ValueError,TypeError):self.sound_action.blockSignals(False)
        self.entry_toggle.setChecked(bool(prefs.get('entry_panel',False)))
        self.entry_toggle.toggled.connect(self.save_entry_preference)
        self.fit_calculator()
        self.prepare()
        QTimer.singleShot(0,self.fit_calculator)
        if prefs.get("enhanced_tools",False):QTimer.singleShot(0,self.open_enhanced)

    def toggle_entry(self,visible):
        self.entry_panel.setVisible(visible)
        self.entry_toggle.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        if visible:self.editor.setFocus()
        else:self.lcd.setFocus()
        if hasattr(self,"audio"):self.fit_calculator()

    def fit_calculator(self):
        """Fit the complete case, never a scrollable slice of the keypad."""
        from .rom_skin import CASE_STYLE
        case=self.centralWidget();case.ensurePolished()
        available=self.screen().availableGeometry()
        limit=max(400,available.height()-45)
        self.setMinimumSize(0,0)
        # Compact only when necessary for the current display or open editor.
        for compact in range(25):
            case.setStyleSheet(CASE_STYLE+f"QPushButton#hpKey {{ font-size: {max(11,18-compact//2)}px; }} QLabel#keyLegend {{ font-size: {max(8,10-compact//4)}px; }} QPushButton#hpKey[shift] {{ font-size: {max(16,25-compact)}px; }}")
            for button in self.buttons:button.setMinimumHeight(max(18,32-compact))
            for label in case.findChildren(QLabel,"keyLegend"):label.setFixedHeight(max(10,13-compact//3))
            for label in case.findChildren(QLabel,"alphaLegend"):label.setFixedHeight(10)
            self.lcd.setMinimumSize(393,max(100,192-compact*5))
            self.face_layout.setContentsMargins(18,max(5,14-compact),18,max(5,12-compact))
            self.face_layout.setSpacing(max(2,6-compact//3))
            logo=case.findChild(QLabel,'brand');logo.setFixedSize(max(129,174-compact*4),max(40,54-compact))
            self.editor.setFixedHeight(max(44,85-compact*4))
            case.layout().setContentsMargins(max(6,13-compact),max(6,13-compact),max(6,13-compact),max(6,13-compact))
            case.layout().invalidate();case.layout().activate();self.layout().invalidate();self.layout().activate()
            QApplication.sendPostedEvents(None,QEvent.Type.LayoutRequest)
            required=self.minimumSizeHint()
            if required.height()<=limit:break
        self.setMinimumSize(required)
        self.resize(max(560,required.width()),required.height())

    def save_entry_preference(self,_):
        try:self.save_preferences()
        except OSError as exc:self.status.setText(str(exc))

    def download_revision(self):
        from .rom_setup import ROM_CATALOG
        revision,ok=QInputDialog.getItem(self,'Download calculator ROM','Model and revision:',sorted(ROM_CATALOG),sorted(ROM_CATALOG).index('gxrom-r'),False)
        if ok:self.prepare(download=True,revision=revision)

    def prepare(self, download=False, source=None,revision='gxrom-r'):
        if self.session or (self.setup and self.setup.state()!=QProcess.ProcessState.NotRunning): return
        if not (self.directory/'rom').exists() and not download and source is None:
            self.status.setText('Choose “File → Download ROM revision…” or use a local ROM to begin.');return
        self.status.setText('Preparing Saturn core…')
        self.setup=QProcess(self)
        args=(['--setup-rom'] if getattr(sys,'frozen',False) else ['-m','hp48g.rom_setup'])+['--directory',str(self.directory)]
        if source: args+=['--rom',source]
        elif download: args+=['--download-rom','--revision',revision]
        self.setup.finished.connect(self.prepared)
        self.setup.errorOccurred.connect(lambda _:self.problem(self.setup.errorString()))
        self.setup.start(sys.executable,args)

    def prepared(self,code,status):
        if code:
            self.problem(bytes(self.setup.readAllStandardError()).decode(errors='replace')[-3000:]);return
        try: self.session=RomSession(self.directory,self)
        except Exception as exc: self.problem(str(exc));return
        self.session.frame.connect(self.show_frame);self.session.error.connect(self.problem)
        self.title.setText('48'+self.session.model)
        self.setWindowTitle('HP 48'+self.session.model+' · '+self.session.revision.upper())
        self.session.audio.connect(self.audio.play)
        self.session.audio.connect(self.background.sound)
        self.session.soundStopped.connect(self.audio.stop)
        self.session.ready.connect(self.autosave_timer.start)
        self.session.ready.connect(lambda:self.session.request('SPEED',str(self.speed)))
        self.session.ready.connect(lambda:self.status.setText('First start: press ON if the screen is blank, then F (NO) at “Try To Recover Memory?”.' if self.session.fresh else 'Memory restored.'))
        self.session.ready.connect(self.cards_restored)
        self.session.stopped.connect(self.closed)
        from .rom_instance import install_server
        if not getattr(self,'instance_server',None):self.instance_server=install_server(self)

    def cards_restored(self):
        pending=self.directory/'cards-pending'
        session=self.session
        def refreshed():
            if hasattr(self,'card_manager'):
                self.card_manager.setEnabled(True);self.card_manager.refresh()
        if not pending.exists():refreshed();return
        self.status.setText('Initializing updated memory card…')
        def scanned(value,error):
            if error:
                refreshed();self.problem('Card initialization needs retry: '+error);return
            def saved(ok):
                if ok:
                    pending.unlink(missing_ok=True)
                    self.status.setText('Memory card configured and saved.')
                refreshed()
            session.save(saved)
        session.rescan_cards(scanned)

    def select_lcd_choice(self,steps,activate=True):
        session=self.session
        if not session or self.selecting_choice or session.closing:return
        self.selecting_choice=True
        keys=[16 if steps>0 else 10]*abs(steps)+([24] if activate else [])
        def next_key():
            if self.session is not session or session.closing:
                self.selecting_choice=False;return
            if not keys:self.selecting_choice=False;return
            session.tap(keys.pop(0))
            QTimer.singleShot(180,next_key)
        next_key()

    def show_frame(self,data):
        self.lcd.update_frame(data)
        ann=data['annunciators']
        for i,button in enumerate(self.buttons):
            left,right=SHIFT_LABELS.get(i,('',''))
            alpha=chr(65+i) if i<24 else {25:'Y',26:'Z'}.get(i,'')
            button.setText((alpha if ann&4 else right if ann&2 else left if ann&1 else '') or {34:'↰',39:'↱',10:'▲',15:'◀',16:'▼',17:'▶'}.get(i,'' if i<6 else LABELS[i]))
        self.ann.setText('  '.join(label for bit,label in [(1,'LEFT SHIFT'),(2,'RIGHT SHIFT'),(4,'α'),(8,'LOW BATTERY'),(16,'BUSY'),(32,'I/O')] if ann&bit))

    def problem(self,message):
        self.status.setText(message)
        QMessageBox.warning(self,'Original calculator',message)

    def run_text(self):
        if self.session:
            try: self.session.execute(self.editor.toPlainText());self.status.setText('Sent to HP parser. Results and HP errors appear on the LCD.')
            except Exception as exc: self.problem(str(exc))

    def load_source(self):
        path,_=QFileDialog.getOpenFileName(self,'Load HP source','','Text (*.txt *.rpl);;All files (*)')
        if path:
            try:self.save_draft(archive=True);self.editor.setPlainText(Path(path).read_text(encoding='utf-8'));self.entry_toggle.setChecked(True)
            except Exception as exc:self.problem(str(exc))

    def choose_rom(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose HP 48 ROM','','ROM or ZIP (*)')
        if path:self.prepare(source=path)

    def import_object(self):
        if not self.session:return
        path,_=QFileDialog.getOpenFileName(self,'Import HP binary object','','HP objects (*)')
        if path:
            try:self.session.push(import_binary(Path(path).read_bytes()))
            except Exception as exc:self.problem(str(exc))

    def export_object(self):
        if not self.session:return
        path,_=QFileDialog.getSaveFileName(self,'Export stack level 1','','HP objects (*.hp)')
        if not path:return
        def exported(result):
            try:
                if not result.get('ok'):raise ValueError(result.get('message','Export failed'))
                Path(path).write_bytes(export_binary(result['object']));self.status.setText('Object exported.')
            except Exception as exc:self.problem(str(exc))
        self.session.request('EXPORT','1',exported)

    def save(self):
        if self.session and (self.session.querying or self.session.transferring):
            self.status.setText('Wait for the desktop operation to finish before saving.');return
        if self.session:self.session.save(lambda ok:self.status.setText('Calculator memory saved.') if ok else None)

    def query(self,source,callback):
        if not self.session:self.status.setText('Start the calculator first');return
        def completed(value,error):
            if error:self.problem(error)
            else:
                try:callback(value)
                except Exception as exc:self.problem(str(exc))
        self.session.query(source,completed)

    def open_program_editor(self):
        from .rom_tools import RomProgramEditor
        if not hasattr(self,'program_editor'):self.program_editor=RomProgramEditor(self)
        self.program_editor.show();self.program_editor.raise_()

    def open_memory(self):
        from .rom_tools import MemoryBrowser
        if self.session:
            self.memory_browser=MemoryBrowser(self);self.memory_browser.show()

    def open_graph(self):
        from .rom_graph import RomGraph
        if self.session:
            if not hasattr(self,'graph_tools'):self.graph_tools=RomGraph(self)
            self.graph_tools.show();self.graph_tools.raise_()

    def open_enhanced(self):
        from .enhanced_tools import EnhancedTools
        if not hasattr(self,'enhanced_tools'):
            self.enhanced_dock=QDockWidget('Enhanced tools',self)
            self.enhanced_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
            self.enhanced_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
            self.enhanced_tools=EnhancedTools(self)
            self.enhanced_dock.setWidget(self.enhanced_tools)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.enhanced_dock)
            self.enhanced_dock.visibilityChanged.connect(self.enhanced_visibility)
        self.enhanced_dock.show();self.enhanced_dock.raise_()
        self.enhanced_visibility(True)
        if self.session and self.session.process.state()==QProcess.ProcessState.Starting:
            self.session.ready.connect(self.enhanced_tools.refresh_context)
        else:self.enhanced_tools.refresh_context()

    def enhanced_visibility(self,visible):
        self.save_preferences()
        if visible:
            self.centralWidget().setMaximumWidth(560)
            self.resize(min(self.screen().availableGeometry().width(),1400),self.height())
        else:
            self.centralWidget().setMaximumWidth(16777215)
            self.enhanced_tools.save()
            QTimer.singleShot(0,self.fit_calculator)

    def open_backups(self):
        from .rom_tools import BackupDialog
        self.backup_dialog=BackupDialog(self);self.backup_dialog.show()

    def save_draft(self,archive=False):
        try:
            path=self.directory/'editor-draft.rpl';data=self.editor.toPlainText().encode()
            if archive and data:
                import time
                recovery=self.directory/'source-recovery'
                atomic_bytes(recovery/f'{time.time_ns()}.rpl',data)
                for old in sorted(recovery.glob('*.rpl'),reverse=True)[10:]:old.unlink()
            if path.exists() and path.read_bytes()!=data:atomic_bytes(self.directory/'editor-previous.rpl',path.read_bytes())
            atomic_bytes(path,data)
            return True
        except Exception as exc:self.problem('Could not save editor draft: '+str(exc));return False

    def make_backup(self,label='Snapshot',callback=None,automatic=False):
        if not self.session or self.session.closing or self.session.querying or self.session.transferring:
            if callback:callback(False)
            return
        destination=self.backups.destination(label,automatic)
        def saved(ok):
            if ok:
                try:
                    if automatic:
                        atomic_bytes(self.directory/'calculator.hp48state',destination.read_bytes());self.backups.prune()
                    self.status.setText('Recovery point saved.' if automatic else 'Backup saved: '+destination.name)
                except Exception as exc:ok=False;self.problem(str(exc))
            if callback:callback(ok)
        self.session.save(saved,destination)

    def autosave(self):
        if self.session and not self.session.closing:self.make_backup(automatic=True)

    def restart_checkpoint(self,data):
        import tempfile
        from .rom_session import restore_checkpoint
        # Validate against the active ROM before stopping the existing core.
        with tempfile.TemporaryDirectory() as directory:
            import shutil
            shutil.copyfile(self.directory/'rom',Path(directory)/'rom')
            path=Path(directory)/'checkpoint';path.write_bytes(data);restore_checkpoint(path,directory)
        self.autosave_timer.stop();self.pending_restore=data
        self.session.closing=True;self.session.request('QUIT')

    def open_cards(self):
        from .rom_cards import CardManager
        if self.session:self.card_manager=CardManager(self);self.card_manager.show()

    def set_speed(self):
        choices=['Maximum speed','500,000 instructions/second','250,000 instructions/second','1,000,000 instructions/second']
        label,ok=QInputDialog.getItem(self,'Emulator speed','Instruction pacing (not cycle-accurate):',choices,0,False)
        if ok and self.session:
            self.speed=[0,500000,250000,1000000][choices.index(label)];self.session.request('SPEED',str(self.speed));self.save_preferences()

    def open_profile(self):
        directory=QFileDialog.getExistingDirectory(self,'Choose a separate calculator profile folder')
        if directory:
            self.other_profile=RomWindow(directory);self.other_profile.show()

    def restore_backup(self,path):
        try:data=self.backups.validated_bytes(path)
        except Exception as exc:self.problem(str(exc));return
        def saved(ok):
            if not ok:self.status.setText('Wait until the calculator is idle before restoring.');return
            try:self.restart_checkpoint(data)
            except Exception as exc:self.problem(str(exc))
        self.make_backup('Before restore',saved)

    def copy_stack(self):
        if not self.session:return
        def exported(reply):
            if not reply.get('ok'):self.problem(reply.get('message','No stack object'));return
            native=export_binary(reply['object'])
            def copied(text):
                mime=QMimeData();mime.setText(text);mime.setData('application/x-hp48-object',native)
                QApplication.clipboard().setMimeData(mime);self.status.setText('Copied level 1 as text and a native HP object.')
            self.query(lambda saved:f'{saved} DUP SIZE GET →STR',copied)
        self.session.request('EXPORT','1',exported)

    def paste_editor(self):
        self.entry_toggle.setChecked(True)
        self.editor.insertPlainText(QApplication.clipboard().text());self.editor.setFocus()

    def paste_object(self):
        if not self.session:return
        mime=QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat('application/x-hp48-object'):
            self.paste_editor();self.status.setText('Pasted text into the editor for review. Use Run text to execute it.');return
        try:self.session.push(import_binary(bytes(mime.data('application/x-hp48-object'))))
        except Exception as exc:self.problem(str(exc))

    def copy_lcd(self):
        image=QImage(self.lcd.pixels,131,64,17,QImage.Format.Format_Mono)
        image.setColorTable([QColor('#a5b394').rgba(),QColor('#34483e').rgba()])
        QApplication.clipboard().setImage(image.copy());self.status.setText('LCD image copied.')

    def save_preferences(self):
        atomic_bytes(self.directory/'desktop.json',json.dumps({'sound':self.audio.enabled,'volume':self.audio.volume,'background':self.background.enabled,'speed':self.speed,'entry_panel':self.entry_toggle.isChecked(),'enhanced_tools':hasattr(self,'enhanced_dock') and not self.enhanced_dock.isHidden()}).encode())

    def set_sound(self,enabled):
        self.audio.set_enabled(enabled)
        try:self.save_preferences()
        except OSError as exc:self.status.setText(str(exc))

    def set_volume(self):
        volume,ok=QInputDialog.getInt(self,'Sound volume','Volume (%)',round(self.audio.volume*100),0,100)
        if ok:self.audio.set_volume(volume/100);self.save_preferences()

    def about(self):
        from . import __version__
        from .platform_ui import DISPLAY_NAME,application_icon
        dialog=QMessageBox(self)
        dialog.setWindowTitle('About '+DISPLAY_NAME)
        dialog.setIconPixmap(application_icon().pixmap(128,128))
        dialog.setText(DISPLAY_NAME)
        dialog.setInformativeText(f'Created by Spiffware\nMichael Rice\nVersion {__version__}\nOctober 17, 2026')
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def help(self):
        QMessageBox.information(self,'Original HP keyboard','The buttons are the original physical keys. A–F select the LCD menus; you can also click their labels directly on the screen.\nUse the left/right shift keys and α as on the calculator. ON cancels an operation.\nComputer keys: digits/operators, arrows, Enter, Backspace and Escape (ON). F1–F6 select menus; F7/F8 shift; F9 alpha. Letters press their corresponding physical keys. Click the LCD to leave the text editor.\nText is parsed by HP’s ROM; use original HP syntax and « » program delimiters. Binary imports go to stack level 1.\nMemory saves automatically when this window closes. This calculator has its own stack, settings, directories and two 128 KB RAM cards. The enhanced Python workspace is separate.')

    def keyPressEvent(self,event):
        if self.editor.hasFocus() or event.isAutoRepeat(): return super().keyPressEvent(event)
        mapping={Qt.Key.Key_Return:24,Qt.Key.Key_Enter:24,Qt.Key.Key_Escape:44,
                 Qt.Key.Key_Backspace:28,Qt.Key.Key_Delete:27,Qt.Key.Key_Space:47,
                 Qt.Key.Key_Left:15,Qt.Key.Key_Down:16,Qt.Key.Key_Right:17,Qt.Key.Key_Up:10,
                 Qt.Key.Key_F7:34,Qt.Key.Key_F8:39,Qt.Key.Key_F9:29}
        mapping.update({int(Qt.Key.Key_F1)+i:i for i in range(6)})
        numeric={'0':45,'1':40,'2':41,'3':42,'4':35,'5':36,'6':37,'7':30,'8':31,'9':32,
                 '.':46,'+':48,'-':43,'*':38,'/':33}
        index=mapping.get(event.key(),numeric.get(event.text()))
        letter=event.text().upper()
        if len(letter)==1 and 'A'<=letter<='Z':index=ord(letter)-65 if letter<='X' else 25 if letter=='Y' else 26
        if index is not None and self.session:
            self.held.add((event.key(),index));self.session.key(index,True);event.accept()
        else:super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if event.isAutoRepeat():return
        for key,index in list(self.held):
            if key==event.key():
                if self.session:self.session.key(index,False)
                self.held.discard((key,index));event.accept();return
        super().keyReleaseEvent(event)

    def focusOutEvent(self,event):
        for _,index in self.held:
            if self.session:self.session.key(index,False)
        self.held.clear();super().focusOutEvent(event)

    def closed(self):
        self.autosave_timer.stop();self.audio.stop();self.session=None
        if self.pending_restore is not None:
            try:atomic_bytes(self.directory/'calculator.hp48state',self.pending_restore)
            except Exception as exc:self.problem('Restore failed; the previous checkpoint is still available: '+str(exc))
            self.pending_restore=None;self.prepare();return
        if getattr(self,'instance_server',None):self.instance_server.close();self.instance_server.deleteLater();self.instance_server=None
        self.done=True;self.close()

    def closeEvent(self,event):
        if hasattr(self,'enhanced_tools'):
            if not self.enhanced_tools.save():event.ignore();return
            self.enhanced_tools.shutdown()
        if self.background.enabled and not self.background.exiting and not self.done:
            if not self.save_draft():event.ignore();return
            event.ignore();self.hide();self.background.notify('Calculator running in background','Alarms remain active. Use the tray menu to reopen or Save and quit.');return
        if not self.save_draft():event.ignore();return
        if self.session and self.session.querying:
            event.ignore();QTimer.singleShot(250,self.close);return
        self.autosave_timer.stop();self.draft_timer.stop();self.audio.stop()
        if self.session and not self.done:
            event.ignore();self.status.setText('Saving calculator memory…');self.session.close()
        else:
            if self.setup and self.setup.state()!=QProcess.ProcessState.NotRunning:self.setup.kill();self.setup.waitForFinished(1000)
            event.accept()
