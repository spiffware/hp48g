"""Persistent solver inputs and cancellable computations with stack transfer."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QLabel,QTabWidget,QHBoxLayout
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .engine import format_value
from .serialization import encode,decode
from .jobs import JobRunner


class ToolsPanel(QTabWidget):
    changed=Signal()
    def __init__(self,context=None,push=None,asynchronous=True):
        super().__init__()
        self.context=context or (lambda:('RAD',{})); self.push=push or (lambda v:None)
        self.fields={}; self.results={}; self.values={}; self.runners={}; self.send_buttons={}
        self.asynchronous=asynchronous
        self.addTab(self.ode_panel(),'Differential equations')
        self.addTab(self.finance_panel(),'Finance')
        self.addTab(self.probability_panel(),'Probability')

    def panel(self,key,definitions,description):
        panel=QWidget(); layout=QVBoxLayout(panel); hint=QLabel(description); hint.setWordWrap(True); layout.addWidget(hint)
        form=QFormLayout(); fields={}
        for name,label,default in definitions:
            if isinstance(default,list): widget=QComboBox(); widget.addItems(default)
            else: widget=QLineEdit(default)
            fields[name]=widget; form.addRow(label,widget)
        self.fields[key]=fields; layout.addLayout(form)
        row=QHBoxLayout(); calculate=QPushButton('Calculate'); cancel=QPushButton('Cancel'); cancel.setEnabled(False); send=QPushButton('Send result to stack'); send.setEnabled(False)
        for button in (calculate,cancel,send): row.addWidget(button)
        layout.addLayout(row); result=QLabel(); result.setWordWrap(True); layout.addWidget(result)
        runner=JobRunner(self,self.asynchronous); self.runners[key]=runner; self.results[key]=result; self.send_buttons[key]=send
        def run():
            if runner.busy: return
            try: payload=self.payload(key)
            except Exception as exc: result.setText(f'Error: {exc}'); return
            submitted=self.field_values(key)
            calculate.setEnabled(False); cancel.setEnabled(True); send.setEnabled(False); result.setText('Calculating…')
            def finish(data):
                calculate.setEnabled(True); cancel.setEnabled(False)
                if submitted!=self.field_values(key) or (key=='ode' and self.payload(key)!=payload): result.setText('Inputs changed; calculate again for an updated result.'); return
                value=decode(data['value']); self.values[key]=value; send.setEnabled(True)
                result.setText(format_value(value,True))
                if key=='ode':
                    self.ode_figure.clear(); ax=self.ode_figure.add_subplot(111); ax.plot(data['x'],data['y'],color='#087f8c'); ax.set_xlabel('x'); ax.set_ylabel('y'); ax.grid(alpha=.25)
                    self.ode_figure.tight_layout(); self.ode_canvas.draw(); result.setText(f'y({data["x"][-1]:.10g}) = {format_value(value,True)}')
                if key=='finance':
                    target={'Periods':'n','Rate (%)':'rate','Present value':'pv','Payment':'pmt','Future value':'fv'}[fields['unknown'].currentText()]
                    fields[target].setText(str(float(value))); send.setEnabled(True)
                self.changed.emit()
            def fail(message):
                calculate.setEnabled(True); cancel.setEnabled(False); result.setText(f'Error: {message}')
            runner.start(key,payload,finish,fail)
        calculate.clicked.connect(run); cancel.clicked.connect(lambda:runner.cancel()); send.clicked.connect(lambda:self.push(self.values[key]))
        for field in fields.values():
            signal=field.textChanged if isinstance(field,QLineEdit) else field.currentTextChanged
            signal.connect(lambda *_,button=send:button.setEnabled(False))
        return panel,layout

    def ode_panel(self):
        panel,layout=self.panel('ode',[('source','dy/dx = f(x,y)','x-y'),('x0','Initial x','0'),('y0','Initial y','1'),('end','Final x','10')],
            'Solve one first-order initial value problem. Expressions use the calculator angle mode and stored variables.')
        self.ode_figure=Figure(figsize=(6,4)); self.ode_canvas=FigureCanvasQTAgg(self.ode_figure); layout.addWidget(self.ode_canvas,1)
        return panel

    def finance_panel(self):
        panel,layout=self.panel('finance',[(key,label,value) for key,label,value in [('n','Periods','12'),('rate','Rate (%)','1'),('pv','Present value','1000'),('pmt','Payment','0'),('fv','Future value','0'),
            ('unknown','Solve for',['Future value','Payment','Present value','Rate (%)','Periods'])]],
            'End-of-period payments. Use opposite signs for money paid and received. Interest is percent per payment period; the unknown field is ignored.')
        layout.addStretch(); return panel

    def probability_panel(self):
        panel,layout=self.panel('probability',[('distribution','Distribution',['Normal','Student t','Chi-square','Binomial','Poisson']),('operation','Operation',['CDF','Density / mass','Inverse CDF']),('x','x / probability','1.96'),('p1','Parameter 1','0'),('p2','Parameter 2','1')],
            'Normal: mean, standard deviation. Student t / Chi-square: degrees of freedom (parameter 1). Binomial: n, p. Poisson: mean (parameter 1).')
        layout.addStretch(); return panel

    def field_values(self,key):
        return {name:(widget.text() if isinstance(widget,QLineEdit) else widget.currentText()) for name,widget in self.fields[key].items()}

    def payload(self,key):
        fields=self.field_values(key)
        text_keys={'source','unknown','distribution','operation'}
        if key=='finance':
            target={'Periods':'n','Rate (%)':'rate','Present value':'pv','Payment':'pmt','Future value':'fv'}[fields['unknown']]
            fields[target]='0'
        payload={k:(v if k in text_keys else float(v)) for k,v in fields.items()}
        if key=='ode':
            angle,memory=self.context(); payload.update(angle=angle,memory={k:encode(v) for k,v in memory.items()})
        return payload

    def snapshot(self):
        return {'fields':{key:self.field_values(key) for key in self.fields},'tab':self.currentIndex(),
            'results':{key:label.text() if self.send_buttons[key].isEnabled() else '' for key,label in self.results.items()},'values':{key:encode(v) for key,v in self.values.items() if self.send_buttons[key].isEnabled()}}

    def restore(self,state):
        for key,fields in state.get('fields',{}).items():
            for name,value in fields.items():
                widget=self.fields[key][name]
                if isinstance(widget,QLineEdit): widget.setText(value)
                else: widget.setCurrentText(value)
        self.values={key:decode(v) for key,v in state.get('values',{}).items()}
        for key,label in self.results.items():
            label.setText(state.get('results',{}).get(key,'')); self.send_buttons[key].setEnabled(key in self.values)
        self.setCurrentIndex(state.get('tab',0))
