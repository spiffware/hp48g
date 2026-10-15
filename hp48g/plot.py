"""Qt graphing workspace with interactive Matplotlib navigation."""
import numpy as np
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QLabel
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from .analysis import sample,function,analyze


class PlotPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self)
        heading=QLabel('GRAPH & ANALYZE'); heading.setObjectName('section'); layout.addWidget(heading)
        self.mode=QComboBox(); self.mode.addItems(['Function','Polar','Parametric','Implicit','3D surface','Slope field','Histogram','Scatter'])
        self.expr=QLineEdit('sin(x)'); self.expr.setPlaceholderText('sin(x); cos(x) — separate curves with ;')
        self.second=QLineEdit(); self.second.setPlaceholderText('Optional, e.g. cos(x)')
        form=QFormLayout(); form.addRow('Plot type',self.mode)
        self.expr_label=QLabel('First function y(x)'); self.second_label=QLabel('Second function (optional)')
        form.addRow(self.expr_label,self.expr); form.addRow(self.second_label,self.second)
        self.low=QLineEdit('-10'); self.high=QLineEdit('10')
        bounds=QHBoxLayout(); bounds.addWidget(self.low); bounds.addWidget(QLabel('to')); bounds.addWidget(self.high)
        form.addRow('Domain',bounds); layout.addLayout(form)
        row=QHBoxLayout(); draw=QPushButton('Draw graph'); draw.setObjectName('primary'); draw.clicked.connect(self.draw); row.addWidget(draw)
        self.operation=QComboBox(); self.operation.addItems(['Root','Integral','Minimum','Maximum','Derivative at a']); row.addWidget(self.operation)
        calculate=QPushButton('Analyze [a, b]'); calculate.clicked.connect(self.calculate); row.addWidget(calculate); layout.addLayout(row)
        self.hint=QLabel('Graph expressions use radians. Domain also supplies the analysis interval.'); self.hint.setWordWrap(True); layout.addWidget(self.hint)
        self.figure=Figure(figsize=(7,5),facecolor='#fafbf8'); self.canvas=FigureCanvasQTAgg(self.figure)
        self.toolbar=NavigationToolbar2QT(self.canvas,self)
        layout.addWidget(self.toolbar); layout.addWidget(self.canvas,1)
        self._drawn_mode=None
        self._drawn_domain=None
        self.result=QLabel('Ready'); self.result.setWordWrap(True); layout.addWidget(self.result)
        self.mode.currentTextChanged.connect(self.mode_changed)
        self.update_fields()
        self.draw()

    def update_fields(self):
        mode=self.mode.currentText()
        labels={
            'Function':('First function y(x)','Second function (optional)','Optional, e.g. cos(x)'),
            'Parametric':('x(t)','y(t)','e.g. sin(t)'),
            'Scatter':('x values','y values','e.g. 2,3,5,4'),
        }
        first,second,placeholder=labels.get(mode,('Expression / data','',''))
        self.expr_label.setText(first); self.second_label.setText(second)
        self.second.setPlaceholderText(placeholder)
        self.second.setVisible(mode in labels); self.second_label.setVisible(mode in labels)
        instructions={
            'Function':'Draw graph plots both function fields. Separate additional curves with ;. Analysis uses the first function.',
            'Parametric':'Draw graph combines x(t) and y(t) into one parametric curve.',
            'Scatter':'Enter matching lists of x and y values, then click Draw graph.',
        }
        self.hint.setText(instructions.get(mode,'Enter an expression or data, then click Draw graph.')+' Graph expressions use radians.')

    def mode_changed(self,mode):
        examples={'Function':('sin(x)',''), 'Polar':('2*cos(3*t)',''), 'Parametric':('cos(t)','sin(t)'),
                  'Implicit':('x^2+y^2-4',''), '3D surface':('sin(sqrt(x^2+y^2))',''),
                  'Slope field':('x-y',''), 'Histogram':('1,2,2,3,3,3,4,5',''), 'Scatter':('1,2,3,4','2,3,5,4')}
        self.expr.setText(examples[mode][0]); self.second.setText(examples[mode][1])
        if mode in ('Polar','Parametric'): self.low.setText('0'); self.high.setText('6.28318530718')
        else: self.low.setText('-10'); self.high.setText('10')
        self.update_fields()

    def bounds(self):
        a,b=float(self.low.text()),float(self.high.text())
        if not np.isfinite([a,b]).all() or a>=b: raise ValueError('Domain must be finite with a < b')
        return a,b

    def draw(self):
        try:
            a,b=self.bounds(); mode=self.mode.currentText(); source=self.expr.text()
            previous_view=None
            if mode=='Function' and self._drawn_mode==mode and self.figure.axes:
                old_ax=self.figure.axes[0]
                previous_view=(old_ax.get_xlim(),old_ax.get_ylim())
            x=np.linspace(a,b,1600)
            if mode=='Function':
                parts=[part.strip() for field in (source,self.second.text()) for part in field.split(';') if part.strip()]
                if not parts: raise ValueError('Enter at least one function')
                # Validate curves before replacing the graph so a typo also
                # leaves the current view and navigation history intact.
                curves=[(part,sample(part,x)) for part in parts]
            self.figure.clear()
            self._drawn_mode=None
            ax=self.figure.add_subplot(111,projection='3d' if mode=='3D surface' else 'polar' if mode=='Polar' else None)
            ax.set_facecolor('#fafbf8'); ax.grid(True,alpha=.22)
            if mode=='Function':
                for index,(part,y) in enumerate(curves):
                    # Split large jumps so poles are not joined by vertical lines.
                    jumps=np.abs(np.diff(y))>max(50,10*(b-a))
                    y[1:][jumps]=np.nan
                    ax.plot(x,y,lw=1.8,label=part.strip(),color=['#087f8c','#b46e33','#7c66a6'][index%3])
                ax.legend()
                # Expression edits retain the user's toolbar limits. A domain edit
                # changes the horizontal range without replacing the vertical range.
                ax.set_xlim(previous_view[0] if previous_view and self._drawn_domain==(a,b) else (a,b))
                ax.set_ylim(previous_view[1] if previous_view else (a,b))
                ax.axhline(0,color='#65736a',lw=.6); ax.axvline(0,color='#65736a',lw=.6)
            elif mode=='Polar': ax.plot(x,sample(source,x,'t'),color='#087f8c')
            elif mode=='Parametric': ax.plot(sample(source,x,'t'),sample(self.second.text(),x,'t')); ax.set_aspect('equal',adjustable='datalim')
            elif mode in ('Implicit','3D surface','Slope field'):
                grid=np.linspace(a,b,24 if mode=='Slope field' else 100); X,Y=np.meshgrid(grid,grid)
                with np.errstate(all='ignore'): Z=np.broadcast_to(function(source,('x','y'))(X,Y),X.shape)
                if mode=='Implicit': ax.contour(X,Y,Z,levels=[0],colors=['#087f8c'])
                elif mode=='3D surface': ax.plot_surface(X,Y,Z,cmap='viridis',linewidth=0)
                else:
                    length=np.sqrt(1+Z**2); ax.quiver(X,Y,1/length,Z/length,pivot='middle',headwidth=0,headlength=0,color='#087f8c')
            elif mode=='Histogram': ax.hist([float(v) for v in source.replace(',',' ').split()],bins='auto',color='#087f8c',edgecolor='white')
            elif mode=='Scatter': ax.scatter([float(v) for v in source.replace(',',' ').split()],[float(v) for v in self.second.text().replace(',',' ').split()],color='#087f8c')
            self.figure.tight_layout(); self.canvas.draw()
            self._drawn_mode=mode; self._drawn_domain=(a,b)
            # Old navigation entries refer to axes replaced by figure.clear().
            self.toolbar.update(); self.toolbar.push_current()
            self.result.setText('Drag to pan, scroll/toolbar to zoom. Use the toolbar to save a plot.')
        except Exception as exc: self.result.setText(f'Graph error: {exc}')

    def calculate(self):
        try:
            if self.mode.currentText()!='Function': raise ValueError('Analysis requires a function of x')
            a,b=self.bounds(); result=analyze(self.expr.text().split(';')[0],self.operation.currentText(),a,b)
            self.result.setText(f'{self.operation.currentText()}: {result}')
        except Exception as exc: self.result.setText(f'Analysis error: {exc}')
