"""Host mathematics attached to the ROM calculator; no second calculator stack."""
from pathlib import Path
from decimal import Decimal
import sympy as s
from PySide6.QtCore import QTimer, QStandardPaths
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,QPlainTextEdit,QComboBox,QSpinBox,QFileDialog
from .app import MainWindow
from .engine import Calculator,format_value
from .serialization import encode,decode,calculator_state,read_calculator,read_json,write_json
from .jobs import JobRunner
from .plot import PlotPanel
from .tools_panel import ToolsPanel
from .rom_codec import quote_text,decode_value,decode_real,number_nibbles


def host_value(value):
    if isinstance(value,Decimal):return s.Float(str(value),12)
    if isinstance(value,list):return [host_value(v) for v in value]
    if isinstance(value,dict) and value.get('type')==0x29e8:
        raw=value['raw'];kind=int(raw[10:15][::-1],16);rank=int(raw[15:20][::-1],16)
        if rank not in (1,2) or kind not in (0x2933,0x2977):raise ValueError('Unsupported HP array type')
        shape=[int(raw[20+5*i:25+5*i][::-1],16) for i in range(rank)]
        count=shape[0]*(shape[1] if rank==2 else 1);width=16 if kind==0x2933 else 32;start=20+5*rank
        if len(raw)!=start+width*count:raise ValueError('Invalid HP array length')
        values=[host_value(decode_value({'type':kind,'raw':number_nibbles(kind)+raw[start+i*width:start+(i+1)*width]})) for i in range(count)]
        return values if rank==1 else s.Matrix(shape[0],shape[1],values)
    if isinstance(value,dict):raise ValueError('This native object cannot be inspected by Python. Use the ROM tools for this object.')
    if isinstance(value,complex):return s.Float(value.real)+s.I*s.Float(value.imag)
    return value


def hp_source(value):
    """Serialize data only; never send a Python program to the HP interpreter."""
    if isinstance(value,str):return quote_text(value)
    if isinstance(value,s.MatrixBase):
        return '['+' '.join('['+' '.join(hp_source(value[r,c]) for c in range(value.cols))+']' for r in range(value.rows))+']'
    if isinstance(value,(list,tuple)):return '{ '+' '.join(hp_source(v) for v in value)+' }'
    value=s.sympify(value)
    if value.is_number:
        if value.is_finite is not True:raise ValueError('The HP stack cannot represent an infinite or undefined result.')
        def real(v):
            if v==0:return '0'
            exponent=int(s.floor(s.log(abs(v),10)))
            if not -499<=exponent<=499:raise ValueError('Result exceeds the HP real-number range; it remains in Enhanced tools.')
            return str(s.N(v,12)).replace('e','E')
        if value.is_real:return real(value)
        return '('+real(s.re(value))+','+real(s.im(value))+')'
    # Only arithmetic algebraics are exported; unsupported exact objects stay here.
    from sympy.printing.str import StrPrinter
    functions={s.sin:'SIN',s.cos:'COS',s.tan:'TAN',s.asin:'ASIN',s.acos:'ACOS',s.atan:'ATAN',
               s.sinh:'SINH',s.cosh:'COSH',s.tanh:'TANH',s.exp:'EXP',s.log:'LN',s.Abs:'ABS'}
    class HPPrinter(StrPrinter):
        def _print_Pow(self,expr):return '('+self._print(expr.base)+')^('+self._print(expr.exp)+')'
        def _print_Function(self,expr):return functions[expr.func]+'('+','.join(self._print(a) for a in expr.args)+')'
        def _print_Pi(self,expr):return 'π'
        def _print_Exp1(self,expr):return 'EXP(1)'
        def _print_Abs(self,expr):return self._print_Function(expr)
        def _print_exp(self,expr):return self._print_Function(expr)
        def _print_log(self,expr):return self._print_Function(expr)
    if any(not isinstance(node,(s.Add,s.Mul,s.Pow,s.Symbol,s.Number)) and node not in (s.pi,s.E) and node.func not in functions for node in s.preorder_traversal(value)):
        raise ValueError('This exact result is not an HP algebraic; copy or export it from Enhanced tools.')
    from .rom_codec import quote_name
    for symbol in value.free_symbols:quote_name(symbol.name)
    return "'"+HPPrinter().doprint(value)+"'"


class EnhancedTools(QWidget):
    # Shared panel implementations contain no keypad or independent stack.
    stats_panel=MainWindow.stats_panel
    units_panel=MainWindow.units_panel
    calculate_stats=MainWindow.calculate_stats
    send_statistic=MainWindow.send_statistic
    convert_unit=MainWindow.convert_unit

    def __init__(self,window,asynchronous=True):
        super().__init__(window);self.window=window;self.path=window.directory/'enhanced-tools.json'
        self.angle='DEG';self.memory={};self.results=[];self.result_labels=[];self.stats_value=None;self.converted_value=None;self.restoring=True;self.save_blocked=False
        self.runner=JobRunner(self,asynchronous);self.stats_runner=JobRunner(self,asynchronous)
        self.autosave_timer=QTimer(self);self.autosave_timer.setSingleShot(True);self.autosave_timer.setInterval(500);self.autosave_timer.timeout.connect(self.save)
        layout=QVBoxLayout(self)
        note=QLabel('Enhanced mathematics · results stay here until you send them to the HP stack. Numeric transfers use HP precision.');note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('HP stack level:'));self.level=QSpinBox();self.level.setRange(1,1000);row.addWidget(self.level)
        read=QPushButton('Copy to tool');read.clicked.connect(self.read_stack);row.addWidget(read)
        sync=QPushButton('Refresh HP context');sync.clicked.connect(self.refresh_context);row.addWidget(sync)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        math=QWidget();ml=QVBoxLayout(math)
        help=QLabel("Enter an enhanced calculation, for example: 'x^3-2*x' x DIFF. This is a tool input, not the ROM program editor.");help.setWordWrap(True);ml.addWidget(help)
        self.source=QLineEdit();self.source.setPlaceholderText("'x^3-2*x' x DIFF");ml.addWidget(self.source)
        commands=QHBoxLayout();ml.addLayout(commands)
        self.command=QComboBox();self.command.setEditable(True)
        from .engine import STACK_COMMANDS
        self.command.addItems(sorted(set(Calculator().commands)|STACK_COMMANDS));commands.addWidget(self.command)
        append=QPushButton('Append command');append.clicked.connect(lambda:self.source.setText((self.source.text()+' '+self.command.currentText()).strip()));commands.addWidget(append)
        buttons=QHBoxLayout();ml.addLayout(buttons)
        self.math_run=QPushButton('Calculate');self.math_run.clicked.connect(self.calculate);buttons.addWidget(self.math_run)
        self.math_cancel=QPushButton('Cancel');self.math_cancel.setEnabled(False);self.math_cancel.clicked.connect(lambda:self.runner.cancel());buttons.addWidget(self.math_cancel)
        self.output=QPlainTextEdit();self.output.setReadOnly(True);ml.addWidget(self.output)
        self.selection=QComboBox();ml.addWidget(self.selection)
        send=QPushButton('Send selected result to HP stack');send.clicked.connect(self.send_selected);ml.addWidget(send)
        export=QPushButton('Save results…');export.clicked.connect(self.export_results);ml.addWidget(export)
        self.tabs.addTab(math,'Math')
        self.plot=PlotPanel(self.tool_context,self.push_value,asynchronous);self.tabs.addTab(self.plot,'Graph && Analyze')
        self.tabs.addTab(self.stats_panel(),'Statistics');self.tabs.addTab(self.units_panel(),'Units')
        self.solvers=ToolsPanel(self.tool_context,self.push_value,asynchronous);self.tabs.addTab(self.solvers,'Solvers')
        self.status=QLabel('Ready');self.status.setWordWrap(True);layout.addWidget(self.status)
        for field in self.findChildren(QLineEdit):field.textChanged.connect(self.queue_autosave)
        for field in self.findChildren(QPlainTextEdit):field.textChanged.connect(self.queue_autosave)
        for field in self.findChildren(QComboBox):field.currentIndexChanged.connect(self.queue_autosave)
        self.tabs.currentChanged.connect(self.queue_autosave);self.solvers.changed.connect(self.queue_autosave)
        try:
            if self.path.exists():self.restore(read_json(self.path))
            else:self.import_legacy()
        except Exception as exc:
            self.save_blocked=self.path.exists()
            self.status.setText('Saved tools could not be restored and will not be overwritten: '+str(exc))
        self.restoring=False

    def tool_context(self):return self.angle,self.memory
    def queue_autosave(self,*_):
        if not self.restoring:self.autosave_timer.start()
    def show_results(self,values,labels=None):
        self.result_labels=list(labels or [f'Result {i+1}' for i in range(len(values))])
        self.results=values;self.output.setPlainText('\n'.join(format_value(v) for v in values));self.selection.clear()
        self.selection.addItems([f'{self.result_labels[i]}: {format_value(v)[:80]}' for i,v in enumerate(values)]);self.queue_autosave()
    def calculate(self):
        if self.runner.busy:return
        calc=Calculator();calc.angle=self.angle;calc.variables=dict(self.memory)
        self.status.setText('Calculating…')
        self.source.setEnabled(False);self.math_run.setEnabled(False);self.math_cancel.setEnabled(True)
        def finished(message):
            self.source.setEnabled(True);self.math_run.setEnabled(True);self.math_cancel.setEnabled(False);self.status.setText(message)
        def done(data):
            self.show_results(read_calculator(data)[0]);finished('Result ready; HP stack unchanged.')
        self.runner.start('engine',{'state':calculator_state(calc),'source':self.source.text()},done,finished)
    def export_results(self):
        path,_=QFileDialog.getSaveFileName(self,'Save exact results','results.json','JSON (*.json)')
        if path:
            try:write_json(path,{'version':1,'results':[encode(v) for v in self.results]});self.status.setText('Exact results saved.')
            except Exception as exc:self.status.setText(str(exc))
    def send_selected(self):
        if 0<=self.selection.currentIndex()<len(self.results):self.push_value(self.results[self.selection.currentIndex()])
    def refresh_context(self):
        session=self.window.session
        if not session:self.status.setText('Start the ROM calculator first.');return
        def done(value,error):
            if error:self.status.setText(error);return
            self.angle='RAD' if value[0] else 'GRAD' if value[1] else 'DEG'
            self.memory={str(row[0]):host_value(row[1]) for row in value[2] if len(row)==2}
            self.plot.invalidate_result();self.status.setText(f'HP context refreshed: {self.angle}, {len(self.memory)} numeric variables.')
            self.queue_autosave()
        session.query('-17 FS? -18 FS? VARS 1 « DUP RCL DUP TYPE DUP 0 == SWAP 1 == OR IF THEN 2 →LIST ELSE DROP DROP { } END » DOLIST 3 →LIST',done)
    def read_stack(self):
        session=self.window.session
        if not session:return
        if session.querying or session.transferring:
            self.status.setText('Wait for the current desktop operation to finish before copying the HP stack.');return
        def done(reply):
            try:
                if not reply.get('ok'):raise ValueError(reply.get('message','Could not read HP stack'))
                value=host_value(decode_value(reply['value']))
                if self.tabs.currentIndex()==2:
                    rows=value.tolist() if isinstance(value,s.MatrixBase) else value if isinstance(value,(list,tuple)) else [value]
                    self.data.setPlainText('\n'.join(','.join(str(v) for v in row) if isinstance(row,(list,tuple)) else str(row) for row in rows))
                elif self.tabs.currentIndex()==3:self.unit_value.setText(str(value))
                else:
                    self.tabs.setCurrentIndex(0);self.source.setText(format_value(value));self.show_results([value])
                self.status.setText('Copied from HP stack; original value unchanged.')
            except Exception as exc:self.status.setText(str(exc))
        session.request('EXPORT',str(self.level.value()),done)
    def push_value(self,value):
        session=self.window.session
        if not session:self.status.setText('Start the ROM calculator first.');return
        try:source=hp_source(value)
        except Exception as exc:self.status.setText(str(exc));return
        self.status.setText('Sending result to HP stack…')
        session.query(quote_text(source)+' STR→',lambda value,error:self.status.setText(error or 'Result added to HP stack (HP numeric precision).'),keep_result=True)
    def snapshot(self):
        return {'version':1,'source':self.source.text(),'results':[encode(v) for v in self.results],'result_labels':self.result_labels, 'angle':self.angle,'stats_value':encode(self.stats_value) if self.stats_send.isEnabled() else None,'converted_value':encode(self.converted_value) if self.unit_send.isEnabled() else None,
                'stats_result':self.stats_result.toPlainText(),'stats_choice':self.stats_kind.currentText(),'unit_result':self.unit_result.text(),'statistics':self.data.toPlainText(),'unit_value':self.unit_value.text(),'unit_from':self.unit_from.currentText(),'unit_to':self.unit_to.currentText(),
                'graph':self.plot.snapshot(),'solvers':self.solvers.snapshot(),'tab':self.tabs.currentIndex()}
    def restore(self,data):
        if data.get('version')!=1:raise ValueError('Unsupported tools file version')
        self.source.setText(data.get('source',''));self.show_results([decode(v) for v in data.get('results',[])],data.get('result_labels'))
        self.angle=data.get('angle','DEG');self.data.setPlainText(data.get('statistics',''))
        self.unit_value.setText(data.get('unit_value','1'));self.unit_from.setCurrentText(data.get('unit_from','m'));self.unit_to.setCurrentText(data.get('unit_to','ft'))
        if 'graph' in data:self.plot.restore(data['graph'])
        if 'solvers' in data:self.solvers.restore(data['solvers'])
        self.tabs.setCurrentIndex(data.get('tab',0))
        self.stats_value=decode(data['stats_value']) if data.get('stats_value') else None
        self.converted_value=decode(data['converted_value']) if data.get('converted_value') else None
        self.stats_send.setEnabled(self.stats_value is not None);self.unit_send.setEnabled(self.converted_value is not None)
        self.stats_result.setPlainText(data.get('stats_result',''));self.stats_kind.setCurrentText(data.get('stats_choice','Data'));self.unit_result.setText(data.get('unit_result',''))
    def import_legacy(self):
        from .data_paths import data_directory,legacy_directory
        path=data_directory()/'workspace.json'
        if not path.exists():path=legacy_directory()/'workspace.json'
        if not path.exists():return
        from .workspace import validate_session
        data=read_json(path);values,workspace=validate_session(data)
        recovered=list(values[0])+list(values[1].values())
        labels=[f'Previous stack level {len(values[0])-i}' for i in range(len(values[0]))]+[f'Previous variable {name}' for name in values[1]]
        if workspace:
            inputs=workspace['inputs']
            self.restore({'version':1,'source':inputs['entry'],'results':[encode(v) for v in recovered],'result_labels':labels,
                          'angle':values[2],'statistics':inputs['statistics'],'unit_value':inputs['unit_value'],
                          'unit_from':inputs['unit_from'],'unit_to':inputs['unit_to'],'graph':workspace['graph'],'solvers':workspace['solvers']})
        else:self.show_results(recovered,labels)
        self.status.setText('Previous Python workspace inputs and values recovered. Original workspace.json is unchanged; HP memory is unchanged.')
    def save(self):
        if self.save_blocked:return True  # Preserve the unreadable original for recovery.
        try:write_json(self.path,self.snapshot());return True
        except Exception as exc:self.status.setText('Could not save enhanced tools: '+str(exc));return False
    def shutdown(self):
        for runner in (self.runner,self.stats_runner,self.plot.runner,*self.solvers.runners.values()):runner.cancel()
        self.autosave_timer.stop()
