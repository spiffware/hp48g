"""HP 48G inspired Qt6 desktop application."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
import sympy as s
from PySide6.QtCore import Qt,QTimer,QStandardPaths,QSize
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,
    QLabel,QPushButton,QLineEdit,QPlainTextEdit,QTabWidget,QComboBox,QFormLayout,QFileDialog,
    QSplitter,QListWidget,QMessageBox,QDialog,QDialogButtonBox,QInputDialog)
from .engine import Calculator,CalculatorError,Program,expression,format_value
from .analysis import UNITS,convert,statistics
from .plot import PlotPanel
from .tools_panel import ToolsPanel
from .serialization import encode,decode,calculator_state,read_calculator,read_rpl,write_json,read_json
from .workspace import validate_session
from .jobs import JobRunner

STYLE='''
QMainWindow { background: #e9ede8; }
QWidget { font-family: "Avenir Next", "Segoe UI", sans-serif; font-size: 13px; color: #243b37; }
QWidget#body { background: #263c42; border-radius: 20px; }
QLabel#brand { color: #f5f4e9; font-size: 25px; font-weight: 700; }
QLabel#subtitle { color: #b2c6c7; font-size: 11px; }
QLabel#section { font-size: 17px; font-weight: 700; padding: 8px 0; }
QLabel#status { color: #e3c68d; padding: 5px; }
QPlainTextEdit#lcd { background: #c9d6b6; color: #233329; border: 5px solid #172c31;
  border-radius: 9px; font-family: Menlo, Consolas, monospace; font-size: 19px; padding: 10px; }
QLineEdit { background: #fffef9; border: 1px solid #b9c8bd; border-radius: 5px; padding: 8px; }
QLineEdit#entry { background: #e0e8cf; color: #203127; font-family: Menlo, Consolas, monospace; font-size: 17px; }
QPushButton { background: #f8faf5; border: 1px solid #bfccc3; border-radius: 6px; padding: 9px; }
QPushButton:hover { background: #dfebe4; }
QPushButton:disabled { color: #7c8984; background: #e7ece6; border-color: #d3dcd3; }
QPushButton:pressed { background: #b9d9cd; }
QPushButton#key { background: #3d535b; border: 1px solid #60737a; border-bottom: 3px solid #162a30; color: white; font-weight: 600; font-size: 15px; }
QPushButton#key:hover { background: #506d75; }
QPushButton#primary { background: #087f8c; color: white; border: 0; font-weight: 600; }
QTabWidget::pane { background: #fafbf8; border: 1px solid #cbd6cd; border-radius: 8px; }
QTabBar::tab { background: #dde5dc; padding: 11px 16px; }
QTabBar::tab:selected { background: #fafbf8; color: #087f8c; }
QPlainTextEdit,QListWidget { background: #fffefb; border: 1px solid #c8d3c9; padding: 8px; }
QComboBox { padding: 6px; background: #fffefb; border: 1px solid #bdcabe; border-radius: 4px; }
'''


class MainWindow(QMainWindow):
    def __init__(self,asynchronous=True,auto_path=None,interactive=True):
        super().__init__(); self.calc=Calculator(); self.shift=False
        self.asynchronous=asynchronous; self.interactive=interactive; self.auto_path=Path(auto_path) if auto_path else None
        self._restoring=False; self._saved_fingerprint=None; self.session_file=None
        self.runner=JobRunner(self,asynchronous); self.stats_runner=JobRunner(self,asynchronous); self.unit_runner=JobRunner(self,asynchronous)
        self.stats_value=None; self.converted_value=None
        self.setWindowTitle('HP 48G · Scientific RPN'); self.resize(1280,880)
        splitter=QSplitter(); self.splitter=splitter; self.setCentralWidget(splitter)
        body=QWidget(); body.setObjectName('body'); body.setMinimumWidth(370); body.setMaximumWidth(520)
        left=QVBoxLayout(body); left.setContentsMargins(22,22,22,22); left.setSpacing(10)
        brand=QLabel('hp  48G'); brand.setObjectName('brand'); left.addWidget(brand)
        subtitle=QLabel('SCIENTIFIC GRAPHING CALCULATOR  /  PYTHON EDITION'); subtitle.setObjectName('subtitle'); left.addWidget(subtitle)
        self.mode_label=QLabel(); self.mode_label.setObjectName('subtitle'); left.addWidget(self.mode_label)
        self.lcd=QPlainTextEdit(); self.lcd.setObjectName('lcd'); self.lcd.setReadOnly(True); self.lcd.setMinimumHeight(220); left.addWidget(self.lcd,1)
        self.entry=QLineEdit(); self.entry.setObjectName('entry'); self.entry.setPlaceholderText("2 3 +  or  'x^2' x DIFF"); self.entry.returnPressed.connect(self.enter); left.addWidget(self.entry)
        self.status=QLabel('Ready · Enter values, then an operation'); self.status.setObjectName('status'); self.status.setWordWrap(True); left.addWidget(self.status)
        self.cancel_calc=QPushButton('Cancel calculation'); self.cancel_calc.hide(); self.cancel_calc.clicked.connect(lambda:self.runner.cancel()); left.addWidget(self.cancel_calc)
        soft=QHBoxLayout()
        for label,index in [('MATH',0),('PLOT',1),('STAT',2),('UNITS',3)]:
            b=QPushButton(label); b.clicked.connect(lambda checked=False,i=index:self.open_tools(i)); soft.addWidget(b)
        stack_button=QPushButton('STACK'); stack_button.clicked.connect(self.browse_stack); soft.addWidget(stack_button)
        left.addLayout(soft)
        grid=QGridLayout(); grid.setSpacing(8)
        keys=[['ENTER','SWAP','DROP','UNDO','CLEAR'],['SIN','COS','TAN','SQRT','^'],['LN','LOG','INV','SQ','/'],['7','8','9','(', '*'],['4','5','6',')','-'],['1','2','3','NEG','+'],['SHIFT','0','.','π','EVAL']]
        self.key_buttons={}
        for row,labels in enumerate(keys):
            for col,label in enumerate(labels):
                button=QPushButton(label); button.setObjectName('primary' if label=='ENTER' else 'key'); button.setMinimumHeight(46)
                button.clicked.connect(lambda checked=False,key=label:self.key(key)); grid.addWidget(button,row,col); self.key_buttons[label]=button
        left.addLayout(grid); splitter.addWidget(body)
        self.tabs=QTabWidget(); splitter.addWidget(self.tabs); splitter.setSizes([410,870])
        self.tabs.addTab(self.math_panel(),'Math & memory')
        self.plot=PlotPanel(self.tool_context,self.push_value,asynchronous); self.tabs.addTab(self.plot,'Graph & analyze')
        self.tabs.addTab(self.stats_panel(),'Statistics'); self.tabs.addTab(self.units_panel(),'Units')
        self.solvers=ToolsPanel(self.tool_context,self.push_value,asynchronous); self.tabs.addTab(self.solvers,'Solvers'); self.tabs.addTab(self.help_panel(),'Guide')
        self.hide_tools_button=QPushButton('×')
        self.hide_tools_button.setToolTip('Hide tools panel')
        self.hide_tools_button.setAccessibleName('Hide tools panel')
        self.hide_tools_button.clicked.connect(lambda:self.tools_action.setChecked(False))
        self.tabs.setCornerWidget(self.hide_tools_button)
        self.tools_action=QAction('Show tools panel',self)
        self.tools_action.setCheckable(True); self.tools_action.setChecked(True)
        self.tools_action.toggled.connect(self.set_tools_visible)
        self.menuBar().addMenu('View').addAction(self.tools_action)
        menu=self.menuBar().addMenu('Session')
        for text,shortcut,callback in [('Save…','Ctrl+S',self.save_session),('Open…','Ctrl+O',self.load_session),('Undo','Ctrl+Z',self.undo)]:
            action=QAction(text,self); action.setShortcut(QKeySequence(shortcut)); action.triggered.connect(callback); menu.addAction(action)
        self.menuBar().addMenu('Calculator').addAction('Original HP 48GX (ROM)…',self.open_original)
        rpl_menu=self.menuBar().addMenu('Programs')
        rpl_menu.addAction('UserRPL editor…',self.open_program_editor)
        rpl_menu.addAction('HP command compatibility…',self.open_compatibility)
        self.refresh(); self.entry.setFocus()
        self.autosave_timer=QTimer(self); self.autosave_timer.setSingleShot(True); self.autosave_timer.setInterval(750)
        self.autosave_timer.timeout.connect(self.autosave)
        for field in self.findChildren(QLineEdit): field.textChanged.connect(self.queue_autosave)
        for combo in self.findChildren(QComboBox): combo.currentIndexChanged.connect(self.queue_autosave)
        self.data.textChanged.connect(self.queue_autosave)
        self.solvers.changed.connect(self.queue_autosave)
        self.tabs.currentChanged.connect(self.queue_autosave); self.tools_action.toggled.connect(self.queue_autosave)
        self.plot.canvas.mpl_connect('draw_event',lambda event:self.queue_autosave())
        if self.auto_path and self.auto_path.exists():
            try: self.apply_session(read_json(self.auto_path)); self.status.setText('Previous workspace restored')
            except Exception as exc: self.status.setText(f'Could not restore workspace: {exc}')
        self._saved_fingerprint=self.fingerprint()

    def open_original(self):
        from .rom_window import RomWindow
        if not hasattr(self,'original_window') or self.original_window.done:
            self.original_window=RomWindow()
        self.original_window.show(); self.original_window.raise_(); self.original_window.activateWindow()

    def open_program_editor(self):
        from .rpl_editor import ProgramEditor
        if not hasattr(self,'program_editor'):
            self.program_editor=ProgramEditor(self)
            if hasattr(self,'rpl_source'): self.program_editor.editor.setPlainText(self.rpl_source)
            self.program_editor.editor.textChanged.connect(self.queue_autosave)
        self.program_editor.show(); self.program_editor.raise_(); self.program_editor.activateWindow()

    def open_compatibility(self):
        from .rpl_editor import show_coverage
        self.compatibility_dialog=show_coverage(self)

    def set_tools_visible(self,visible):
        if visible:
            self.tabs.show()
            QTimer.singleShot(0,self._restore_tools_size)
        else:
            self._expanded_size=self.size()
            self._expanded_split=self.splitter.sizes()
            self.tabs.hide()
            # Hiding a populated tab posts layout updates. Resize after those
            # updates so the window does not retain the two-panel minimum.
            QTimer.singleShot(0,self._fit_calculator)
        self.entry.setFocus()

    def _fit_calculator(self):
        if self.tabs.isHidden():
            self.splitter.refresh()
            self.layout().invalidate()
            self.layout().activate()
            self.setMinimumWidth(self.splitter.minimumSizeHint().width())
            self.resize(self._expanded_split[0],self.height())

    def _restore_tools_size(self):
        if not self.tabs.isHidden() and hasattr(self,'_expanded_size'):
            self.splitter.refresh()
            self.layout().invalidate()
            self.layout().activate()
            self.setMinimumWidth(self.splitter.minimumSizeHint().width())
            self.resize(self._expanded_size)
            self.splitter.setSizes(self._expanded_split)

    def open_tools(self,index):
        self.tools_action.setChecked(True)
        self.tabs.setCurrentIndex(index)

    def math_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel)
        title=QLabel('THE STACK IS YOUR WORKSPACE'); title.setObjectName('section'); layout.addWidget(title)
        label=QLabel('Enter arguments first, then choose a command. Level 1 is the top of the stack.\nHP lists use { 1 2 3 }; vectors use [1 2 3]; matrices use [[1 2] [3 4]].'); label.setWordWrap(True); layout.addWidget(label)
        modes=QHBoxLayout(); self.angles=QComboBox(); self.angles.addItems(['DEG','RAD','GRAD']); self.angles.currentTextChanged.connect(self.set_angle)
        modes.addWidget(QLabel('Angle mode')); modes.addWidget(self.angles)
        self.display=QComboBox(); self.display.addItems(['Exact','Decimal']); self.display.currentIndexChanged.connect(self.set_display); modes.addWidget(self.display); layout.addLayout(modes)
        search=QLineEdit(); search.setPlaceholderText('Find a command…'); layout.addWidget(search)
        self.command_list=QListWidget()
        from .engine import STACK_COMMANDS
        self.command_list.addItems(sorted(set(self.calc.commands)|STACK_COMMANDS))
        self.command_list.itemDoubleClicked.connect(lambda item:self.run(item.text())); layout.addWidget(self.command_list,1)
        search.textChanged.connect(lambda text:[self.command_list.item(i).setHidden(text.upper() not in self.command_list.item(i).text()) for i in range(self.command_list.count())])
        execute=QPushButton('Run selected command'); execute.clicked.connect(lambda:self.run(self.command_list.currentItem().text()) if self.command_list.currentItem() else None); layout.addWidget(execute)
        label=QLabel('VARIABLES & PROGRAMS'); label.setObjectName('section'); layout.addWidget(label)
        self.memory=QListWidget(); self.memory.setMaximumHeight(150); self.memory.itemDoubleClicked.connect(lambda item:self.run(item.data(Qt.ItemDataRole.UserRole))); layout.addWidget(self.memory)
        hint=QLabel("Store: 42 'a' STO  ·  Recall: a\nProgram: « DUP * » 'square' STO  ·  Run: 7 square"); hint.setWordWrap(True); layout.addWidget(hint)
        return panel

    def stats_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel)
        title=QLabel('DATA & REGRESSION'); title.setObjectName('section'); layout.addWidget(title)
        layout.addWidget(QLabel('One value per line, or x,y pairs for a linear fit.'))
        self.data=QPlainTextEdit('1,2\n2,4\n3,5\n4,8'); layout.addWidget(self.data)
        self.stats_button=QPushButton('Calculate statistics'); self.stats_button.clicked.connect(self.calculate_stats); layout.addWidget(self.stats_button)
        self.stats_cancel=QPushButton('Cancel'); self.stats_cancel.setEnabled(False); self.stats_cancel.clicked.connect(lambda:self.stats_runner.cancel()); layout.addWidget(self.stats_cancel)
        self.stats_kind=QComboBox(); self.stats_kind.addItems(['Data','Count','Sum','Mean','Median','Sample deviation','Sample variance','Slope','Intercept','Correlation r','r²']); layout.addWidget(self.stats_kind)
        self.stats_send=QPushButton('Send selected result to stack'); self.stats_send.setEnabled(False); self.stats_send.clicked.connect(self.send_statistic); layout.addWidget(self.stats_send)
        self.data.textChanged.connect(lambda:self.stats_send.setEnabled(False))
        self.stats_result=QPlainTextEdit(); self.stats_result.setReadOnly(True); layout.addWidget(self.stats_result)
        return panel

    def units_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel)
        title=QLabel('UNIT CONVERSIONS'); title.setObjectName('section'); layout.addWidget(title)
        form=QFormLayout(); self.unit_value=QLineEdit('1'); self.unit_from=QComboBox(); self.unit_to=QComboBox()
        self.unit_from.addItems(list(UNITS)); self.unit_to.addItems(list(UNITS)); self.unit_to.setCurrentText('ft')
        form.addRow('Value',self.unit_value); form.addRow('From',self.unit_from); form.addRow('To',self.unit_to); layout.addLayout(form)
        button=QPushButton('Convert'); button.clicked.connect(self.convert_unit); layout.addWidget(button)
        self.unit_send=QPushButton('Send result to stack'); self.unit_send.setEnabled(False); self.unit_send.clicked.connect(lambda:self.push_value(self.converted_value)); layout.addWidget(self.unit_send)
        self.unit_value.textChanged.connect(lambda:self.unit_send.setEnabled(False))
        self.unit_from.currentTextChanged.connect(lambda:self.unit_send.setEnabled(False)); self.unit_to.currentTextChanged.connect(lambda:self.unit_send.setEnabled(False))
        self.unit_result=QLabel(''); self.unit_result.setWordWrap(True); layout.addWidget(self.unit_result); layout.addStretch()
        return panel

    def help_panel(self):
        panel=QPlainTextEdit(); panel.setReadOnly(True)
        panel.setPlainText('''QUICK START

2 3 + → 5
ENTER commits input; empty ENTER duplicates level 1.
SHIFT changes SIN/COS/TAN to their inverses, LN to EXP,
LOG to ALOG, SQRT to SQ, and π to i.
Type complete RPN sequences into the input line.
Errors roll back the entire sequence. Undo restores the last state.

SYMBOLIC MATH
'x^3-2*x' x DIFF
'x^2' x 0 3 DINT
'x^2-2' x SOLVE
'cos(x)-x' x 1 ROOT
'x^2-1' FACTOR
'x^2+y' [x,3] SUBST

MATRICES & COMPLEX NUMBERS
[[1,2],[3,4]] DET
[[2,0],[0,4]] [6,8] LSOLVE
[1,2,3] [4,5,6] DOT
(2+3*i) CONJ
[1,2,3,4] MEAN

MEMORY & PROGRAMS
42 'answer' STO
answer
'answer' RCL
« DUP * » 'square' STO
7 square
'answer' PURGE
Programs support IF / CASE, FOR / START, WHILE / DO, local variables, and IFERR.
Use Programs → UserRPL editor for multi-line programs; see HP command compatibility for limits.
Quote new multi-letter symbolic names; unknown commands report errors.
Flat lists support vector addition/subtraction and scalar scaling.
Use STACK to browse/edit every level; n PICK copies level n, n ROLL moves it.

GRAPHING
Function: sin(x) and cos(x) in the two function fields
Click Draw graph to plot both; semicolons add further curves.
Polar: 2*cos(3*t)
Parametric: cos(t), sin(t) in separate fields
Implicit: x^2+y^2-4 (the zero contour)
3D: sin(sqrt(x^2+y^2))
Slope field: x-y for dy/dx
Root requires an interval that brackets a sign change.
Minimum/maximum find a local bounded optimum.
Typed expressions and keypad trig follow calculator angle mode.
Graphs can follow Calculator mode or use their explicit angle selector.
Choose a curve before analysis. Intersection uses the second selector.
Each plot mode keeps its inputs and view. Reset view clears custom limits.
Send result to stack transfers the most recent analysis result.
The domain initially sets both axes for function plots; zoom with the toolbar.

SESSION FILES
Save/Open preserves the complete workspace, including mathematical objects,
graph views, statistics data, solver inputs, unfinished entry and panel layout.
The desktop app automatically saves/restores your previous workspace.
Calculations can be cancelled; they time out after 30 seconds without
changing the stack. Opening a session validates it before replacing work.

COMPATIBILITY
This enhanced workspace uses Python and exact symbolic arithmetic.
For original HP commands, menus, numeric behavior and native programs,
open Calculator → Original HP 48GX (ROM). Each mode has separate memory.
See README.md for supported features and known compatibility gaps.
'''); return panel

    def set_angle(self,value):
        self.calc.angle=value; self.refresh(); self.queue_autosave()
    def set_display(self,index):
        self.calc.numeric=bool(index); self.refresh(); self.queue_autosave()

    def refresh(self):
        if hasattr(self,'plot'):
            context=json.dumps({'angle':self.calc.angle,'variables':{k:encode(v) for k,v in self.calc.visible_variables().items()}},sort_keys=True)
            if getattr(self,'_context_fingerprint',context)!=context:
                self.plot.invalidate_result()
                self.solvers.send_buttons['ode'].setEnabled(False)
            self._context_fingerprint=context
        self.mode_label.setText(f'{{ {" ".join(["HOME"]+self.calc.rpl_state["path"])} }}     {self.calc.angle}     {"DECIMAL" if self.calc.numeric else "EXACT"}     RPN')
        values=self.calc.stack
        self.lcd.setPlainText('\n'.join(f'{len(values)-i}:  {format_value(value,self.calc.numeric)}' for i,value in enumerate(values)) or '4:\n3:\n2:\n1:')
        self.lcd.verticalScrollBar().setValue(self.lcd.verticalScrollBar().maximum())
        self.memory.clear()
        for name,value in sorted(self.calc.variables.items()):
            self.memory.addItem(f'{name}   {format_value(value)}'); self.memory.item(self.memory.count()-1).setData(Qt.ItemDataRole.UserRole,name)
        self.angles.blockSignals(True); self.angles.setCurrentText(self.calc.angle); self.angles.blockSignals(False)
        self.display.blockSignals(True); self.display.setCurrentIndex(int(self.calc.numeric)); self.display.blockSignals(False)

    def tool_context(self): return self.calc.angle,self.calc.visible_variables()

    def checkpoint(self):
        self.calc.history.append(self.calc.snapshot())
        self.calc.history=self.calc.history[-100:]

    def push_value(self,value):
        if value is None: return
        if self.runner.busy:
            self.status.setText('Wait for the calculation or cancel it before changing the stack'); return
        if len(self.calc.stack)>=10000: self.status.setText('Stack size limit exceeded'); return
        self.checkpoint(); self.calc.stack.append(copy.deepcopy(value)); self.refresh(); self.queue_autosave(); self.status.setText('Result added to stack')

    def calculator_busy(self,busy):
        self.entry.setEnabled(not busy); self.angles.setEnabled(not busy); self.display.setEnabled(not busy)
        for button in self.key_buttons.values(): button.setEnabled(not busy)
        self.cancel_calc.setVisible(busy)

    def run(self,command=''):
        if self.runner.busy: return
        source=' '.join(x for x in (self.entry.text().strip(),command) if x)
        if not source: return
        self.execute_source(source,command)

    def execute_source(self,source,command='',replace=None):
        if self.runner.busy: return
        self.calculator_busy(True); self.status.setText('Calculating…')
        try: state=calculator_state(self.calc)
        except Exception as exc: self.calculator_busy(False); self.status.setText(f'Error · {exc}'); return
        def done(data):
            self.calculator_busy(False)
            try: values=read_calculator(data)
            except Exception as exc: self.status.setText(f'Error · {exc}'); return
            self.checkpoint(); self.calc.stack,self.calc.variables,self.calc.angle,self.calc.numeric=values; self.calc.rpl_state=read_rpl(data)
            if replace is None: self.entry.clear()
            self.status.setText(f'OK · {command or "Entry accepted"}'); self.refresh(); self.queue_autosave(); self.entry.setFocus()
        def failed(message):
            self.calculator_busy(False); self.status.setText(f'Error · {message}'); self.entry.setFocus()
        self.runner.start('engine',{'state':state,'source':source,'replace':replace},done,failed)

    def enter(self): self.run('' if self.entry.text().strip() else 'DUP')

    def undo(self):
        if self.runner.busy: return
        self.calc.undo(); self.status.setText('Previous state restored'); self.refresh(); self.queue_autosave()

    def browse_stack(self):
        if self.runner.busy: return
        dialog=QDialog(self); dialog.setWindowTitle('Stack · level 1 is the top'); dialog.resize(650,450)
        layout=QVBoxLayout(dialog); listing=QListWidget(); layout.addWidget(listing)
        def fill():
            listing.clear()
            for level,value in enumerate(reversed(self.calc.stack),1): listing.addItem(f'{level}: {format_value(value,self.calc.numeric)}')
        fill(); row=QHBoxLayout(); layout.addLayout(row)
        def act(action):
            index=listing.currentRow()
            if index<0 or self.runner.busy: return
            position=len(self.calc.stack)-1-index; value=self.calc.stack[position]
            if action=='Copy': self.push_value(value)
            else:
                replacement=None
                if action=='Edit':
                    text,ok=QInputDialog.getMultiLineText(dialog,'Edit stack value','Mathematical value (no commands):',format_value(value))
                    if not ok: return
                    dialog.accept(); self.execute_source(text,'Stack value edited',replace=position); return
                self.checkpoint()
                if action=='Move to top': self.calc.stack.append(self.calc.stack.pop(position))
                elif action=='Delete': self.calc.stack.pop(position)
                else: self.calc.stack[position]=replacement
                self.refresh(); self.queue_autosave()
            fill()
        for name in ('Copy','Move to top','Edit','Delete'):
            button=QPushButton(name); button.clicked.connect(lambda checked=False,n=name:act(n)); row.addWidget(button)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        dialog.exec()

    def key(self,key):
        shifted={'SIN':'ASIN','COS':'ACOS','TAN':'ATAN','LN':'EXP','LOG':'ALOG','SQRT':'SQ','π':'i'}
        if key=='SHIFT':
            self.shift=not self.shift
            for original,target in shifted.items(): self.key_buttons[original].setText(target if self.shift else original)
            self.status.setText('Shift active' if self.shift else 'Ready'); return
        if self.shift:
            key=shifted.get(key,key); self.shift=False
            for original in shifted: self.key_buttons[original].setText(original)
        if key=='ENTER': self.enter()
        elif key=='UNDO': self.undo()
        elif key in '0123456789.()' or key in ('π','i'):
            self.entry.insert('pi' if key=='π' else key); self.entry.setFocus()
        elif key=='CLEAR': self.entry.clear(); self.run('CLEAR')
        else: self.run(key)

    def calculate_stats(self):
        if self.stats_runner.busy: return
        source=self.data.toPlainText(); self.stats_button.setEnabled(False); self.stats_cancel.setEnabled(True); self.stats_send.setEnabled(False)
        def done(data):
            self.stats_button.setEnabled(True); self.stats_cancel.setEnabled(False)
            if source!=self.data.toPlainText(): self.stats_result.setPlainText('Data changed; calculate again.'); return
            self.stats_value=decode(data['value']); self.stats_result.setPlainText(data['text']); self.stats_send.setEnabled(True); self.queue_autosave()
        def failed(message):
            self.stats_button.setEnabled(True); self.stats_cancel.setEnabled(False); self.stats_result.setPlainText(f'Error: {message}')
        self.stats_runner.start('statistics',{'source':source},done,failed)

    def send_statistic(self):
        if self.stats_value is None: return
        name=self.stats_kind.currentText()
        if name not in self.stats_value: self.stats_result.appendPlainText(f'{name} is unavailable for this dataset.'); return
        self.push_value(self.stats_value[name])

    def convert_unit(self):
        try:
            result=convert(float(self.unit_value.text()),self.unit_from.currentText(),self.unit_to.currentText())
            self.converted_value=s.Float(result); self.unit_result.setText(f'{result:.12g} {self.unit_to.currentText()}'); self.unit_send.setEnabled(True); self.queue_autosave()
        except Exception as exc: self.unit_send.setEnabled(False); self.unit_result.setText(f'Error: {exc}')

    def session_data(self):
        expanded_size=self._expanded_size if self.tabs.isHidden() and hasattr(self,'_expanded_size') else self.size()
        split=self._expanded_split if self.tabs.isHidden() and hasattr(self,'_expanded_split') else self.splitter.sizes()
        return {'version':2,**calculator_state(self.calc),'workspace':{
            'rpl_source':self.program_editor.editor.toPlainText() if hasattr(self,'program_editor') else getattr(self,'rpl_source',''),
            'inputs':{'entry':self.entry.text(),'statistics':self.data.toPlainText(),'unit_value':self.unit_value.text(),
                      'unit_from':self.unit_from.currentText(),'unit_to':self.unit_to.currentText(),'stats_result':self.stats_result.toPlainText(),'stats_choice':self.stats_kind.currentText(),'unit_result':self.unit_result.text()},
            'graph':self.plot.snapshot(),'solvers':self.solvers.snapshot(),
            'stats_value':encode(self.stats_value) if self.stats_send.isEnabled() else None,
            'unit_value':encode(self.converted_value) if self.unit_send.isEnabled() else None,
            'layout':{'size':[expanded_size.width(),expanded_size.height()],'split':[max(1,v) for v in split],
                      'visible':not self.tabs.isHidden(),'tab':self.tabs.currentIndex()}}}

    def fingerprint(self):
        return json.dumps(self.session_data(),sort_keys=True,allow_nan=False)

    def queue_autosave(self,*_):
        if not self._restoring and hasattr(self,'autosave_timer'): self.autosave_timer.start()

    def autosave(self):
        if self.auto_path and not self._restoring:
            try: write_json(self.auto_path,self.session_data())
            except Exception as exc: self.status.setText(f'Automatic save failed: {exc}')

    def save_to(self,path):
        data=self.session_data(); validate_session(data); write_json(path,data)
        self.session_file=Path(path); self._saved_fingerprint=self.fingerprint(); self.status.setText('Workspace saved')

    def save_session(self):
        path,_=QFileDialog.getSaveFileName(self,'Save workspace',str(self.session_file or ''),'Calculator session (*.json)')
        if not path: return False
        try: self.save_to(path); return True
        except Exception as exc: QMessageBox.warning(self,'Save failed',str(exc)); return False

    def confirm_replace(self):
        if not self.interactive or self._saved_fingerprint==self.fingerprint(): return True
        choice=QMessageBox.question(self,'Save your work?','Save the current workspace before replacing it?',
            QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        return choice==QMessageBox.StandardButton.Discard or (choice==QMessageBox.StandardButton.Save and self.save_session())

    def apply_session(self,data):
        # Decode and validate every panel before changing the live calculator.
        values,workspace=validate_session(data)
        self.cancel_jobs(); self._restoring=True
        try:
            self.calc.stack,self.calc.variables,self.calc.angle,self.calc.numeric=values; self.calc.rpl_state=read_rpl(data); self.calc.history.clear(); self.refresh()
            if workspace:
                self.rpl_source=workspace.get('rpl_source','')
                if hasattr(self,'program_editor'): self.program_editor.editor.setPlainText(self.rpl_source)
                inputs=workspace['inputs']; self.entry.setText(inputs['entry']); self.data.setPlainText(inputs['statistics'])
                self.unit_value.setText(inputs['unit_value']); self.unit_from.setCurrentText(inputs['unit_from']); self.unit_to.setCurrentText(inputs['unit_to'])
                self.stats_result.setPlainText(inputs['stats_result']); self.stats_kind.setCurrentText(inputs.get('stats_choice','Data')); self.unit_result.setText(inputs['unit_result'])
                self.stats_value=decode(workspace['stats_value']) if workspace.get('stats_value') is not None else None
                self.converted_value=decode(workspace['unit_value']) if workspace.get('unit_value') is not None else None
                self.stats_send.setEnabled(self.stats_value is not None); self.unit_send.setEnabled(self.converted_value is not None)
                self.solvers.restore(workspace['solvers']); self.plot.restore(workspace['graph'])
                layout=workspace['layout']; self._expanded_size=QSize(*layout['size']); self._expanded_split=layout['split']
                self.tabs.setCurrentIndex(layout['tab']); self.tools_action.blockSignals(True); self.tools_action.setChecked(layout['visible']); self.tools_action.blockSignals(False)
                self.tabs.setVisible(layout['visible'])
                QTimer.singleShot(0,self._restore_tools_size if layout['visible'] else self._fit_calculator)
            else: self.entry.clear()
            self._saved_fingerprint=self.fingerprint()
        finally: self._restoring=False
        self.queue_autosave()

    def load_session(self):
        path,_=QFileDialog.getOpenFileName(self,'Open workspace','','Calculator session (*.json)')
        if not path: return
        try:
            data=read_json(path); validate_session(data)
            if not self.confirm_replace(): return
            self.apply_session(data); self.session_file=Path(path); self.status.setText('Workspace loaded')
        except Exception as exc: QMessageBox.warning(self,'Open failed',str(exc))

    def cancel_jobs(self):
        for runner in (self.runner,self.stats_runner,self.unit_runner,self.plot.runner,*self.solvers.runners.values()): runner.cancel()

    def resizeEvent(self,event):
        super().resizeEvent(event); self.queue_autosave()

    def closeEvent(self,event):
        # Desktop sessions are restored automatically; failed saves must not silently lose work.
        if self.auto_path:
            try: write_json(self.auto_path,self.session_data())
            except Exception as exc:
                if self.interactive:
                    choice=QMessageBox.warning(self,'Could not save workspace',f'{exc}\nClose without saving?',QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
                    if choice!=QMessageBox.StandardButton.Discard: event.ignore(); return
        elif not self.confirm_replace(): event.ignore(); return
        self.cancel_jobs(); self.autosave_timer.stop(); event.accept()


def main():
    if '--schedule-wake' in sys.argv:
        sys.argv.remove('--schedule-wake')
        from .rom_wake import main as wake_main
        return wake_main()
    if '--setup-rom' in sys.argv:
        sys.argv.remove('--setup-rom')
        from .rom_setup import main as setup_main
        return setup_main()
    app=QApplication(sys.argv); app.setApplicationName('HP48G Desktop'); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    auto_path=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))/'workspace.json'
    if '--rom' in sys.argv:
        from .rom_window import RomWindow
        directory=None
        if '--rom-directory' in sys.argv:
            directory=sys.argv[sys.argv.index('--rom-directory')+1]
        from .rom_window import default_directory
        from .rom_instance import send_existing
        directory=directory or default_directory()
        command='quit' if '--quit-rom' in sys.argv else 'background' if '--background' in sys.argv else 'show'
        if send_existing(directory,command):return
        if command=='quit':return
        window=RomWindow(directory)
    else: window=MainWindow(auto_path=auto_path)
    if '--background' in sys.argv and hasattr(window,'background'):
        try:window.background.set_enabled(True)
        except ValueError:window.show()
    else:window.show()
    sys.exit(app.exec())
