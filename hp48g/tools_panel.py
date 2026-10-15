"""Additional analysis tools: ODE, time value of money, distributions."""
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QLabel,QTabWidget,QPlainTextEdit
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .analysis import solve_ode,tvm,probability


class ToolsPanel(QTabWidget):
    def __init__(self):
        super().__init__()
        self.addTab(self.ode_panel(),'Differential equations')
        self.addTab(self.finance_panel(),'Finance')
        self.addTab(self.probability_panel(),'Probability')

    def ode_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel); form=QFormLayout()
        fields=[QLineEdit(v) for v in ['x-y','0','1','10']]
        for label,field in zip(['dy/dx = f(x,y)','Initial x','Initial y','Final x'],fields): form.addRow(label,field)
        layout.addLayout(form); button=QPushButton('Solve initial value problem'); layout.addWidget(button)
        figure=Figure(figsize=(6,4)); canvas=FigureCanvasQTAgg(figure); layout.addWidget(canvas,1); result=QLabel(); layout.addWidget(result)
        def calculate():
            try:
                x,y=solve_ode(fields[0].text(),*(float(v.text()) for v in fields[1:])); figure.clear(); ax=figure.add_subplot(111)
                ax.plot(x,y,color='#087f8c'); ax.set_xlabel('x'); ax.set_ylabel('y'); ax.grid(alpha=.25); figure.tight_layout(); canvas.draw()
                result.setText(f'y({x[-1]:.10g}) = {y[-1]:.12g}')
            except Exception as exc: result.setText(f'Error: {exc}')
        button.clicked.connect(calculate); return panel

    def finance_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel)
        hint=QLabel('End-of-period payments. Use opposite signs for money paid and received.\nInterest is percent per payment period. The selected unknown field is ignored.'); hint.setWordWrap(True); layout.addWidget(hint)
        form=QFormLayout(); names=['Periods','Rate (%)','Present value','Payment','Future value']; fields=[QLineEdit(v) for v in ['12','1','1000','0','0']]
        for name,field in zip(names,fields): form.addRow(name,field)
        unknown=QComboBox(); unknown.addItems(names); unknown.setCurrentIndex(4); form.addRow('Solve for',unknown); layout.addLayout(form)
        button=QPushButton('Solve cash flows'); layout.addWidget(button); result=QLabel(); result.setWordWrap(True); layout.addWidget(result); layout.addStretch()
        def calculate():
            try:
                values=[0 if i==unknown.currentIndex() else float(v.text()) for i,v in enumerate(fields)]
                value=tvm(*values,unknown.currentText()); fields[unknown.currentIndex()].setText(f'{value:.12g}'); result.setText(f'{unknown.currentText()} = {value:.12g}')
            except Exception as exc: result.setText(f'Error: {exc}')
        button.clicked.connect(calculate); return panel

    def probability_panel(self):
        panel=QWidget(); layout=QVBoxLayout(panel); form=QFormLayout()
        distribution=QComboBox(); distribution.addItems(['Normal','Student t','Chi-square','Binomial','Poisson'])
        operation=QComboBox(); operation.addItems(['CDF','Density / mass','Inverse CDF'])
        x=QLineEdit('1.96'); p1=QLineEdit('0'); p2=QLineEdit('1')
        for name,field in [('Distribution',distribution),('Operation',operation),('x / probability',x),('Parameter 1',p1),('Parameter 2',p2)]: form.addRow(name,field)
        layout.addLayout(form)
        hint=QLabel('Normal: mean, standard deviation\nStudent t / Chi-square: degrees of freedom (parameter 1)\nBinomial: n, p\nPoisson: mean (parameter 1)'); hint.setWordWrap(True); layout.addWidget(hint)
        button=QPushButton('Calculate'); layout.addWidget(button); result=QLabel(); result.setWordWrap(True); layout.addWidget(result); layout.addStretch()
        def calculate():
            try: result.setText(f'{probability(distribution.currentText(),operation.currentText(),float(x.text()),float(p1.text()),float(p2.text())):.12g}')
            except Exception as exc: result.setText(f'Error: {exc}')
        button.clicked.connect(calculate); return panel
