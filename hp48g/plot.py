"""Graph workspace: persistent views, selected-curve analysis, cancellable jobs."""
import copy
import numpy as np
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QLabel,QPlainTextEdit
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
from matplotlib.figure import Figure
from .engine import format_value,CalculatorError
from .serialization import encode,decode
from .jobs import JobRunner

EXAMPLES={'Function':('sin(x)',''), 'Polar':('2*cos(3*t)',''), 'Parametric':('cos(t)','sin(t)'),
          'Implicit':('x^2+y^2-4',''), '3D surface':('sin(sqrt(x^2+y^2))',''),
          'Slope field':('x-y',''), 'Histogram':('1,2,2,3,3,3,4,5',''), 'Scatter':('1,2,3,4','2,3,5,4')}


class PlotPanel(QWidget):
    def __init__(self,context=None,push=None,asynchronous=True):
        super().__init__()
        self.context=context or (lambda:('RAD',{})); self.push=push or (lambda value:None)
        self.runner=JobRunner(self,asynchronous); self.last_value=None
        self._states={}; self._active_mode='Function'; self._drawn_mode=None; self._drawn_domain=None
        layout=QVBoxLayout(self)
        heading=QLabel('GRAPH & ANALYZE'); heading.setObjectName('section'); layout.addWidget(heading)
        self.mode=QComboBox(); self.mode.addItems(list(EXAMPLES))
        self.expr=QLineEdit('sin(x)'); self.expr.setPlaceholderText('Separate additional curves with ;')
        self.second=QLineEdit(); self.expr_label=QLabel(); self.second_label=QLabel()
        form=QFormLayout(); form.addRow('Plot type',self.mode); form.addRow(self.expr_label,self.expr); form.addRow(self.second_label,self.second)
        self.low=QLineEdit('-10'); self.high=QLineEdit('10'); bounds=QHBoxLayout()
        bounds.addWidget(self.low); bounds.addWidget(QLabel('to')); bounds.addWidget(self.high); form.addRow('Domain / analysis [a, b]',bounds)
        self.ymin=QLineEdit(); self.ymax=QLineEdit(); self.ymin.setPlaceholderText('Automatic'); self.ymax.setPlaceholderText('Automatic')
        ybounds=QHBoxLayout(); ybounds.addWidget(self.ymin); ybounds.addWidget(QLabel('to')); ybounds.addWidget(self.ymax); form.addRow('Y limits',ybounds)
        self.angles=QComboBox(); self.angles.addItems(['Calculator','RAD','DEG','GRAD']); form.addRow('Angles',self.angles)
        layout.addLayout(form)
        row=QHBoxLayout(); self.draw_button=QPushButton('Draw graph'); self.draw_button.setObjectName('primary'); self.draw_button.clicked.connect(self.draw); row.addWidget(self.draw_button)
        reset=QPushButton('Reset view'); reset.clicked.connect(self.reset_view); row.addWidget(reset)
        self.cancel_button=QPushButton('Cancel'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(lambda:self.runner.cancel()); row.addWidget(self.cancel_button); layout.addLayout(row)
        analysis=QHBoxLayout(); self.curve=QComboBox(); self.other_curve=QComboBox()
        self.operation=QComboBox(); self.operation.addItems(['Root','Integral','Minimum','Maximum','Derivative at a','Value at a','Intersection','Value table'])
        analysis.addWidget(self.curve); analysis.addWidget(self.operation); analysis.addWidget(self.other_curve)
        self.calculate_button=QPushButton('Analyze'); self.calculate_button.clicked.connect(self.calculate); analysis.addWidget(self.calculate_button); layout.addLayout(analysis)
        self.other_curve.setToolTip('Second curve for intersection'); self.other_curve.setVisible(False)
        self.operation.currentTextChanged.connect(lambda text:self.other_curve.setVisible(text=='Intersection'))
        self.hint=QLabel(); self.hint.setWordWrap(True); layout.addWidget(self.hint)
        self.figure=Figure(figsize=(7,5),facecolor='#fafbf8'); self.canvas=FigureCanvasQTAgg(self.figure)
        self.toolbar=NavigationToolbar2QT(self.canvas,self); layout.addWidget(self.toolbar); layout.addWidget(self.canvas,1)
        self.result=QLabel('Ready'); self.result.setWordWrap(True); layout.addWidget(self.result)
        self.table=QPlainTextEdit(); self.table.setReadOnly(True); self.table.setMaximumHeight(130); self.table.hide(); layout.addWidget(self.table)
        self.send_button=QPushButton('Send result to stack'); self.send_button.setEnabled(False); self.send_button.clicked.connect(lambda:self.push(self.last_value)); layout.addWidget(self.send_button)
        self.mode.currentTextChanged.connect(self.mode_changed)
        self.expr.textChanged.connect(self.update_curves); self.second.textChanged.connect(self.update_curves)
        self.canvas.mpl_connect('motion_notify_event',self.trace)
        for field in (self.low,self.high,self.ymin,self.ymax): field.textChanged.connect(self.invalidate_result)
        for combo in (self.curve,self.other_curve,self.operation,self.angles): combo.currentTextChanged.connect(self.invalidate_result)
        self.update_fields(); self.update_curves(); self.draw()

    def invalidate_result(self,*_):
        self.last_value=None; self.send_button.setEnabled(False)

    def context_values(self):
        angle,memory=self.context()
        return (angle if self.angles.currentText()=='Calculator' else self.angles.currentText()),{k:encode(v) for k,v in memory.items()}

    def update_curves(self):
        names=[part.strip() for field in (self.expr.text(),self.second.text()) for part in field.split(';') if part.strip()]
        for combo in (self.curve,self.other_curve):
            previous=combo.currentText(); combo.clear(); combo.addItems(names)
            if previous in names: combo.setCurrentText(previous)
        if self.other_curve.count()>1 and self.other_curve.currentIndex()==self.curve.currentIndex(): self.other_curve.setCurrentIndex(1)
        self.last_value=None; self.send_button.setEnabled(False)

    def update_fields(self):
        mode=self.mode.currentText()
        labels={'Function':('First function y(x)','Second function (optional)'), 'Parametric':('x(t)','y(t)'), 'Scatter':('x values','y values')}
        first,second=labels.get(mode,('Expression / data',''))
        self.expr_label.setText(first); self.second_label.setText(second)
        self.second.setVisible(mode in labels); self.second_label.setVisible(mode in labels)
        self.second.setPlaceholderText('Optional, e.g. cos(x)' if mode=='Function' else second)
        self.curve.setEnabled(mode=='Function'); self.operation.setEnabled(mode=='Function'); self.calculate_button.setEnabled(mode=='Function')
        self.hint.setText('Choose a curve to analyze. Move over its graph to trace it. Angle selection applies to all expressions. Stored variables are available.')

    def current_fields(self):
        return {name:getattr(self,name).text() for name in ('expr','second','low','high','ymin','ymax')} | {'angle':self.angles.currentText()}

    def capture_view(self):
        if self._drawn_mode and self.figure.axes:
            ax=self.figure.axes[0]
            view={'x':list(map(float,ax.get_xlim())),'y':list(map(float,ax.get_ylim())),'domain':list(map(float,self._drawn_domain))}
            if self._drawn_mode=='3D surface': view.update(z=list(map(float,ax.get_zlim())),elev=float(ax.elev),azim=float(ax.azim))
            self._states.setdefault(self._drawn_mode,{})['view']=view

    def remember(self):
        self.capture_view(); self._states.setdefault(self._active_mode,{}).update(self.current_fields())

    def mode_changed(self,mode):
        if self.runner.busy: self.runner.cancel()
        self.remember(); self._active_mode=mode
        if mode not in self._states:
            expr,second=EXAMPLES[mode]; self._states[mode]={'expr':expr,'second':second,'low':'0' if mode in ('Polar','Parametric') else '-10',
                'high':'6.28318530718' if mode in ('Polar','Parametric') else '10','ymin':'','ymax':'','angle':'RAD' if mode in ('Polar','Parametric') else 'Calculator'}
        state=self._states[mode]
        for name in ('expr','second','low','high','ymin','ymax'): getattr(self,name).setText(state[name])
        self.angles.setCurrentText(state['angle']); self.update_fields(); self.update_curves()
        self.result.setText('Inputs restored. Click Draw graph.'); self.table.hide()

    def bounds(self):
        a,b=float(self.low.text()),float(self.high.text())
        if not np.isfinite([a,b]).all() or a>=b: raise CalculatorError('Domain must be finite with a < b')
        return a,b

    def ylimits(self):
        if not self.ymin.text().strip() and not self.ymax.text().strip(): return None
        values=float(self.ymin.text()),float(self.ymax.text())
        if not np.isfinite(values).all() or values[0]>=values[1]: raise CalculatorError('Y limits must be finite with min < max')
        return values

    def busy(self,value):
        self.draw_button.setEnabled(not value); self.calculate_button.setEnabled(not value and self.mode.currentText()=='Function'); self.cancel_button.setEnabled(value)

    def error(self,message):
        self.busy(False); self.result.setText(f'Graph error: {message}')

    def draw(self):
        if self.runner.busy: return
        try:
            a,b=self.bounds(); self.ylimits(); angle,memory=self.context_values(); self.remember()
            request={'mode':self.mode.currentText(),'expr':self.expr.text(),'second':self.second.text(),'domain':[a,b],'angle':angle,'memory':memory}
            fields=self.current_fields()
        except Exception as exc: self.error(str(exc)); return
        self.busy(True); self.result.setText('Drawing…'); self.table.hide()
        def done(data):
            self.busy(False)
            if fields!=self.current_fields() or request['mode']!=self.mode.currentText() or self.context_values()!=(request['angle'],request['memory']):
                self.result.setText('Inputs changed during calculation. Click Draw graph again.'); return
            try: self.render(data)
            except Exception as exc: self.error(str(exc))
        self.runner.start('plot',request,done,self.error)

    def render(self,data):
        mode=data['mode']; a,b=data['domain']
        # The live Qt canvas may already be scaled for a Retina display. Match
        # its physical dimensions/DPI so replacing a figure fills the canvas.
        figure=Figure(figsize=self.figure.get_size_inches(),dpi=self.figure.dpi,facecolor='#fafbf8')
        figure._original_dpi=self.figure._original_dpi
        ax=figure.add_subplot(111,projection='3d' if mode=='3D surface' else 'polar' if mode=='Polar' else None)
        ax.set_facecolor('#fafbf8'); ax.grid(True,alpha=.22)
        if mode in ('Function','Polar','Parametric'):
            for index,curve in enumerate(data['series']): ax.plot(curve['x'],curve['y'],lw=1.8,label=curve['label'],color=['#087f8c','#b46e33','#7c66a6'][index%3])
            if mode=='Function':
                ax.legend(); ax.set_xlim(a,b); ax.set_ylim(a,b); ax.axhline(0,color='#65736a',lw=.6); ax.axvline(0,color='#65736a',lw=.6)
            elif mode=='Parametric': ax.set_aspect('equal',adjustable='box')
        elif mode in ('Implicit','3D surface','Slope field'):
            X,Y,Z=(np.array(data[key]) for key in ('x','y','z'))
            if mode=='Implicit': ax.contour(X,Y,Z,levels=[0],colors=['#087f8c'])
            elif mode=='3D surface': ax.plot_surface(X,Y,Z,cmap='viridis',linewidth=0)
            else:
                length=np.hypot(1,Z); ax.quiver(X,Y,1/length,Z/length,pivot='middle',headwidth=0,headlength=0,color='#087f8c')
        elif mode=='Histogram': ax.hist(data['x'],bins='auto',color='#087f8c',edgecolor='white')
        elif mode=='Scatter': ax.scatter(data['x'],data['y'],color='#087f8c')
        view=self._states.get(mode,{}).get('view')
        if view:
            if mode!='Function' or view['domain']==[a,b]: ax.set_xlim(view['x'])
            ax.set_ylim(view['y'])
            if mode=='3D surface': ax.set_zlim(view['z']); ax.view_init(view['elev'],view['azim'])
        if self.ylimits(): ax.set_ylim(self.ylimits())
        figure.tight_layout()
        old=self.figure
        # Matplotlib stores canvas callbacks on the figure. Preserve toolbar,
        # tracing and autosave connections when committing the staged figure,
        # but rebind the two artist-picking callbacks to the new figure.
        callbacks=old._canvas_callbacks
        callbacks.disconnect(old._button_pick_id); callbacks.disconnect(old._scroll_pick_id)
        figure._canvas_callbacks=callbacks; figure._mouse_key_ids=old._mouse_key_ids
        figure._button_pick_id=callbacks.connect('button_press_event',figure.pick)
        figure._scroll_pick_id=callbacks.connect('scroll_event',figure.pick)
        try:
            self.canvas.figure=figure; figure.set_canvas(self.canvas); self.canvas.draw()
        except Exception:
            callbacks.disconnect(figure._button_pick_id); callbacks.disconnect(figure._scroll_pick_id)
            old._button_pick_id=callbacks.connect('button_press_event',old.pick)
            old._scroll_pick_id=callbacks.connect('scroll_event',old.pick)
            self.canvas.figure=old; old.set_canvas(self.canvas); self.canvas.draw(); raise
        self.figure=figure; self._drawn_mode=mode; self._drawn_domain=(a,b); self._data=data
        def y_changed(axis):
            if self._drawn_mode==self._active_mode:
                lo,hi=axis.get_ylim(); self.ymin.setText(f'{lo:.12g}'); self.ymax.setText(f'{hi:.12g}')
        ax.callbacks.connect('ylim_changed',y_changed)
        self.toolbar.update(); self.toolbar.push_current(); self.capture_view()
        self.result.setText('Graph ready. Pan/zoom with the toolbar; Reset view restores the domain. Sampling is approximate.')

    def reset_view(self):
        if self.runner.busy: self.runner.cancel()
        self._drawn_mode=None; self._states.setdefault(self._active_mode,{}).pop('view',None)
        self.ymin.clear(); self.ymax.clear(); self.draw()

    def calculate(self):
        if self.runner.busy: return
        try:
            if self.mode.currentText()!='Function': raise CalculatorError('Analysis requires a function of x')
            a,b=self.bounds(); angle,memory=self.context_values()
            request={'source':self.curve.currentText(),'operation':self.operation.currentText(),'a':a,'b':b,'angle':angle,'memory':memory,'other':self.other_curve.currentText()}
        except Exception as exc: self.error(str(exc)); return
        submitted_bounds=(self.low.text(),self.high.text())
        self.busy(True); self.send_button.setEnabled(False); self.result.setText('Analyzing…')
        def done(data):
            self.busy(False)
            if self.mode.currentText()!='Function' or self.curve.currentText()!=request['source'] or self.operation.currentText()!=request['operation'] or self.other_curve.currentText()!=request['other'] or self.context_values()!=(request['angle'],request['memory']) or self.low.text()!=submitted_bounds[0] or self.high.text()!=submitted_bounds[1]:
                self.result.setText('Inputs changed; analyze again for an updated result.'); return
            self.last_value=decode(data['value']); self.send_button.setEnabled(True)
            self.result.setText(f'{request["operation"]} · {request["source"]}: {format_value(self.last_value,True)}')
            if request['operation']=='Value table':
                self.table.setPlainText('x\ty\n'+'\n'.join(f'{float(x):.10g}\t{float(y):.10g}' for x,y in self.last_value)); self.table.show()
        self.runner.start('analysis',request,done,self.error)

    def trace(self,event):
        if event.inaxes is None or self._drawn_mode!='Function' or self.runner.busy: return
        curves=getattr(self,'_data',{}).get('series',[])
        name=self.curve.currentText()
        curve=next((v for v in curves if v['label']==name),None)
        if curve:
            x=np.asarray(curve['x']); index=int(np.argmin(abs(x-event.xdata))); y=curve['y'][index]
            self.result.setText(f'Trace {name}: x ≈ {x[index]:.9g}, y ≈ {y:.9g} (sampled)')

    def snapshot(self):
        self.remember()
        return {'mode':self.mode.currentText(),'states':copy.deepcopy(self._states),'curve':self.curve.currentIndex(),'operation':self.operation.currentText(),'other':self.other_curve.currentIndex()}

    def restore(self,state):
        self.runner.cancel(); self._states=copy.deepcopy(state['states']); mode=state['mode']
        self.mode.blockSignals(True); self.mode.setCurrentText(mode); self.mode.blockSignals(False); self._active_mode=mode; self._drawn_mode=None
        fields=self._states[mode]
        for name in ('expr','second','low','high','ymin','ymax'): getattr(self,name).setText(fields[name])
        self.angles.setCurrentText(fields['angle']); self.update_fields(); self.update_curves()
        self.curve.setCurrentIndex(state.get('curve',0)); self.operation.setCurrentText(state.get('operation','Root')); self.other_curve.setCurrentIndex(state.get('other',0))
        self.draw()
