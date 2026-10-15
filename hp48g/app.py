"""HP 48G inspired Qt6 desktop application."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import sympy as s
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,
    QLabel,QPushButton,QLineEdit,QPlainTextEdit,QTabWidget,QComboBox,QFormLayout,QFileDialog,
    QSplitter,QListWidget,QMessageBox)
from .engine import Calculator,CalculatorError,Program,expression,format_value
from .analysis import UNITS,convert,statistics
from .plot import PlotPanel
from .tools_panel import ToolsPanel

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


def encode(value):
    if isinstance(value,Program): return {'program':value.source}
    if isinstance(value,s.MatrixBase): return {'matrix':[[encode(v) for v in row] for row in value.tolist()]}
    if isinstance(value,list): return {'list':[encode(v) for v in value]}
    return {'expr':str(value)}


def decode(value):
    if not isinstance(value,dict) or len(value)!=1: raise CalculatorError('Invalid session value')
    if 'program' in value: return Program(value['program'])
    if 'matrix' in value: return s.Matrix([[decode(v) for v in row] for row in value['matrix']])
    if 'list' in value: return [decode(v) for v in value['list']]
    if 'expr' in value: return expression(value['expr'])
    raise CalculatorError('Unknown session value')


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.calc=Calculator(); self.shift=False
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
        soft=QHBoxLayout()
        for label,index in [('MATH',0),('PLOT',1),('STAT',2),('UNITS',3)]:
            b=QPushButton(label); b.clicked.connect(lambda checked=False,i=index:self.open_tools(i)); soft.addWidget(b)
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
        self.plot=PlotPanel(); self.tabs.addTab(self.plot,'Graph & analyze')
        self.tabs.addTab(self.stats_panel(),'Statistics'); self.tabs.addTab(self.units_panel(),'Units')
        self.tabs.addTab(ToolsPanel(),'Solvers'); self.tabs.addTab(self.help_panel(),'Guide')
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
        self.refresh(); self.entry.setFocus()

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
        label=QLabel('Enter arguments first, then choose a command. Level 1 is the top of the stack.\nExpressions may be quoted; lists use [1,2,3], matrices use [[1,2],[3,4]].'); label.setWordWrap(True); layout.addWidget(label)
        modes=QHBoxLayout(); self.angles=QComboBox(); self.angles.addItems(['DEG','RAD','GRAD']); self.angles.currentTextChanged.connect(self.set_angle)
        modes.addWidget(QLabel('Angle mode')); modes.addWidget(self.angles)
        self.display=QComboBox(); self.display.addItems(['Exact','Decimal']); self.display.currentIndexChanged.connect(self.set_display); modes.addWidget(self.display); layout.addLayout(modes)
        search=QLineEdit(); search.setPlaceholderText('Find a command…'); layout.addWidget(search)
        self.command_list=QListWidget()
        self.command_list.addItems(sorted(self.calc.commands))
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
        button=QPushButton('Calculate statistics'); button.clicked.connect(self.calculate_stats); layout.addWidget(button)
        self.stats_result=QPlainTextEdit(); self.stats_result.setReadOnly(True); layout.addWidget(self.stats_result)
        return panel

    def units_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel)
        title=QLabel('UNIT CONVERSIONS'); title.setObjectName('section'); layout.addWidget(title)
        form=QFormLayout(); self.unit_value=QLineEdit('1'); self.unit_from=QComboBox(); self.unit_to=QComboBox()
        self.unit_from.addItems(list(UNITS)); self.unit_to.addItems(list(UNITS)); self.unit_to.setCurrentText('ft')
        form.addRow('Value',self.unit_value); form.addRow('From',self.unit_from); form.addRow('To',self.unit_to); layout.addLayout(form)
        button=QPushButton('Convert'); button.clicked.connect(self.convert_unit); layout.addWidget(button)
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
Programs support straight-line RPN commands and nested calls.

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
Graph expressions always use radians; keypad trig follows angle mode.
The domain initially sets both axes for function plots; zoom with the toolbar.

SESSION FILES
Save/Open preserves stack, variables, programs, and modes in JSON.

COMPATIBILITY
This is an independent HP 48G inspired implementation, not a ROM
emulator or a complete User RPL implementation. Exact symbolic
results and the desktop workspace differ from the original device.
See README.md for supported features and known compatibility gaps.
'''); return panel

    def set_angle(self,value): self.calc.angle=value; self.refresh()
    def set_display(self,index): self.calc.numeric=bool(index); self.refresh()

    def refresh(self):
        self.mode_label.setText(f'{{ HOME }}     {self.calc.angle}     {"DECIMAL" if self.calc.numeric else "EXACT"}     RPN')
        values=self.calc.stack[-8:]
        self.lcd.setPlainText('\n'.join(f'{len(values)-i}:  {format_value(value,self.calc.numeric)}' for i,value in enumerate(values)) or '4:\n3:\n2:\n1:')
        self.lcd.verticalScrollBar().setValue(self.lcd.verticalScrollBar().maximum())
        self.memory.clear()
        for name,value in sorted(self.calc.variables.items()):
            self.memory.addItem(f'{name}   {format_value(value)}'); self.memory.item(self.memory.count()-1).setData(Qt.ItemDataRole.UserRole,name)
        self.angles.blockSignals(True); self.angles.setCurrentText(self.calc.angle); self.angles.blockSignals(False)
        self.display.blockSignals(True); self.display.setCurrentIndex(int(self.calc.numeric)); self.display.blockSignals(False)

    def run(self,command=''):
        source=' '.join(x for x in (self.entry.text().strip(),command) if x)
        if not source: return
        try:
            self.calc.execute(source); self.entry.clear(); self.status.setText(f'OK · {command or "Entry accepted"}'); self.refresh()
        except CalculatorError as exc: self.status.setText(f'Error · {exc}')
        self.entry.setFocus()

    def enter(self): self.run('' if self.entry.text().strip() else 'DUP')
    def undo(self): self.calc.undo(); self.status.setText('Previous state restored'); self.refresh()

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
        try: self.stats_result.setPlainText(statistics(self.data.toPlainText())[0])
        except Exception as exc: self.stats_result.setPlainText(f'Error: {exc}')

    def convert_unit(self):
        try:
            result=convert(float(self.unit_value.text()),self.unit_from.currentText(),self.unit_to.currentText())
            self.unit_result.setText(f'{result:.12g} {self.unit_to.currentText()}')
        except Exception as exc: self.unit_result.setText(f'Error: {exc}')

    def save_session(self):
        path,_=QFileDialog.getSaveFileName(self,'Save session','','Calculator session (*.json)')
        if path:
            try:
                data={'version':1,'stack':[encode(v) for v in self.calc.stack], 'variables':{k:encode(v) for k,v in self.calc.variables.items()},'angle':self.calc.angle,'numeric':self.calc.numeric}
                Path(path).write_text(json.dumps(data,indent=2)); self.status.setText('Session saved')
            except Exception as exc: QMessageBox.warning(self,'Save failed',str(exc))

    def load_session(self):
        path,_=QFileDialog.getOpenFileName(self,'Open session','','Calculator session (*.json)')
        if path:
            try:
                if Path(path).stat().st_size>2_000_000: raise CalculatorError('Session file too large')
                data=json.loads(Path(path).read_text())
                if data['version']!=1 or data['angle'] not in ('DEG','RAD','GRAD') or type(data['numeric']) is not bool: raise CalculatorError('Invalid session format')
                stack=[decode(v) for v in data['stack']]; variables={k:decode(v) for k,v in data['variables'].items()}
                self.calc.stack=stack; self.calc.variables=variables; self.calc.angle=data['angle']; self.calc.numeric=data['numeric']; self.calc.history.clear(); self.entry.clear(); self.refresh(); self.status.setText('Session loaded')
            except Exception as exc: QMessageBox.warning(self,'Open failed',str(exc))


def main():
    app=QApplication(sys.argv); app.setApplicationName('HP48G Desktop'); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    window=MainWindow(); window.show(); sys.exit(app.exec())
