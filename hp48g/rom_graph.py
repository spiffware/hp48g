"""Mouse interaction with the ROM's PICT graphic and PPAR coordinate bounds."""
import math
from PySide6.QtCore import Qt,QPointF,QRect,QSize,Signal,QTimer
from PySide6.QtGui import QImage,QPainter,QColor,QPen
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QLineEdit,QFileDialog,QApplication,QComboBox,QDoubleSpinBox,QFormLayout,QCheckBox)
from .rom_codec import quote_text,quote_name
from .rom_graph_math import algebra,analysis_source


def grob_image(raw):
    if raw[:5]!='e1b20':raise ValueError('Expected a native graphics object')
    height=int(raw[10:15][::-1],16);width=int(raw[15:20][::-1],16)
    if width==0 or height==0:return QImage()
    stride=((width+7)//8)*2
    if width<1 or height<1 or width*height>4_000_000 or len(raw)<20+stride*height:raise ValueError('Invalid graphic dimensions')
    image=QImage(width,height,QImage.Format.Format_RGB32);image.fill(QColor('#c8d7b2'))
    dark=QColor('#193b32').rgb()
    for y in range(height):
        for x in range(width):
            if int(raw[20+y*stride+x//4],16)&(1<<(x%4)):image.setPixel(x,y,dark)
    return image


class GraphCanvas(QWidget):
    picked=Signal(float,float)
    boundsChanged=Signal(tuple)
    def __init__(self):
        super().__init__();self.setMinimumSize(393,240);self.image=QImage();self.bounds=(-6.5,6.5,-3.1,3.2);self.anchor=None;self.mark=None
        self.setMouseTracking(True)
    def image_rect(self):
        size=(self.image.size() if not self.image.isNull() else QSize(131,64)).scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())
    def coordinate(self,position):
        rect=self.image_rect();xmin,xmax,ymin,ymax=self.bounds
        x=max(0,min(1,(position.x()-rect.x())/max(1,rect.width()-1)))
        y=max(0,min(1,(position.y()-rect.y())/max(1,rect.height()-1)))
        return xmin+x*(xmax-xmin),ymax-y*(ymax-ymin)
    def set_bounds(self,bounds):
        xmin,xmax,ymin,ymax=bounds
        if not all(math.isfinite(v) for v in bounds) or xmin>=xmax or ymin>=ymax:raise ValueError('Invalid plot bounds')
        self.bounds=tuple(bounds);self.mark=None;self.update()
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.image_rect().contains(event.position().toPoint()):self.anchor=event.position()
    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or self.anchor is None:return
        start=self.anchor;self.anchor=None;end=event.position()
        if (end-start).manhattanLength()<5:
            self.mark=self.coordinate(end);self.picked.emit(*self.mark);self.update()
        else:
            a=self.coordinate(start);b=self.coordinate(end);dx=a[0]-b[0];dy=a[1]-b[1]
            xmin,xmax,ymin,ymax=self.bounds
            self.set_bounds((xmin+dx,xmax+dx,ymin+dy,ymax+dy));self.boundsChanged.emit(self.bounds)
    def wheelEvent(self,event):
        if not self.image_rect().contains(event.position().toPoint()):event.ignore();return
        steps=max(-5,min(5,event.angleDelta().y()/120));factor=.8**steps
        x,y=self.coordinate(event.position());xmin,xmax,ymin,ymax=self.bounds
        self.set_bounds((x+(xmin-x)*factor,x+(xmax-x)*factor,y+(ymin-y)*factor,y+(ymax-y)*factor))
        self.boundsChanged.emit(self.bounds);event.accept()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#e8eee8'))
        if not self.image.isNull():painter.drawImage(self.image_rect(),self.image)
        if self.mark:
            xmin,xmax,ymin,ymax=self.bounds;r=self.image_rect();x,y=self.mark
            px=r.x()+(x-xmin)/(xmax-xmin)*(r.width()-1);py=r.y()+(ymax-y)/(ymax-ymin)*(r.height()-1)
            painter.setPen(QPen(QColor('#c43f3f'),1));painter.drawLine(QPointF(px-6,py),QPointF(px+6,py));painter.drawLine(QPointF(px,py-6),QPointF(px,py+6))


class RomGraph(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Original HP graph tools');self.resize(760,530);self.drawing=False;self.pending=None
        layout=QVBoxLayout(self)
        self.expression=QLineEdit();self.expression.setPlaceholderText('Expressions separated by ;  e.g. SIN(X); COS(X)');layout.addWidget(self.expression)
        angles=QHBoxLayout();layout.addLayout(angles);angles.addWidget(QLabel('Calculator angle mode:'))
        self.angles=QComboBox();self.angles.addItems(['DEG','RAD','GRAD']);angles.addWidget(self.angles);angles.addStretch()
        options=QHBoxLayout();layout.addLayout(options)
        self.plot_type=QComboBox();self.plot_type.addItems(['FUNCTION','POLAR','PARAMETRIC','TRUTH','CONIC','DIFFEQ','SLOPEFIELD'])
        self.variable=QLineEdit('X');self.variable.setMaximumWidth(70)
        options.addWidget(QLabel('Plot type:'));options.addWidget(self.plot_type);options.addWidget(QLabel('Variable:'));options.addWidget(self.variable)
        bounds=QHBoxLayout();layout.addLayout(bounds);self.limits=[]
        for label,value in zip(['X min','X max','Y min','Y max'],self.canvas.bounds if hasattr(self,'canvas') else (-6.5,6.5,-3.1,3.2)):
            box=QDoubleSpinBox();box.setRange(-1e12,1e12);box.setDecimals(8);box.setValue(value);self.limits.append(box)
            bounds.addWidget(QLabel(label));bounds.addWidget(box)
        apply=QPushButton('Apply bounds');apply.clicked.connect(self.apply_bounds);bounds.addWidget(apply)
        row=QHBoxLayout();layout.addLayout(row)
        for label,callback in [('Plot expression',self.plot),('Load current PICT',self.load),('Export PNG…',self.export),('Copy image',self.copy_image)]:
            button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        self.canvas=GraphCanvas();layout.addWidget(self.canvas)
        self.status=QLabel('Click for coordinates. Drag to pan. Scroll to zoom. Changes update the calculator’s plot bounds.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.canvas.picked.connect(self.pick)
        analysis=QHBoxLayout();layout.addLayout(analysis)
        self.operation=QComboBox();self.operation.addItems(['Trace','Root','Intersection','Extremum','Integral'])
        self.curve=QComboBox();self.other_curve=QComboBox()
        self.a=QDoubleSpinBox();self.b=QDoubleSpinBox()
        for box,value in [(self.a,0),(self.b,1)]:box.setRange(-1e12,1e12);box.setDecimals(8);box.setValue(value)
        for widget in [self.operation,self.curve,self.other_curve,QLabel('x / from'),self.a,QLabel('to / guess'),self.b]:analysis.addWidget(widget)
        calculate=QPushButton('Analyze');calculate.clicked.connect(self.analyze);analysis.addWidget(calculate)
        self.expression.textChanged.connect(self.update_curves);self.update_curves()
        self.canvas.boundsChanged.connect(self.schedule_draw)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.timeout.connect(self.redraw)
        self.load()
    def query(self,source,callback):
        session=self.window.session
        if not session:self.status.setText('Start the calculator first.');return
        self.status.setText('Waiting for the calculator and processing…')
        def done(value,error):
            if error:self.status.setText(error+' Press ON to cancel a running calculation, then retry.');return
            try:callback(value)
            except Exception as exc:self.status.setText(str(exc))
        session.query(source,done)
    def fetched(self,value):
        lower,upper,grob,flags,*metadata=value
        if metadata:
            self.plot_type.setCurrentText(str(metadata[0]).strip("'"));self.variable.setText(str(metadata[1]).strip("'"))
        if len(metadata)>2:
            expressions=metadata[2] if isinstance(metadata[2],list) else [metadata[2]]
            self.expression.setText("; ".join(str(e).strip("'") for e in expressions))
        for box,limit in zip(self.limits,(lower.real,upper.real,lower.imag,upper.imag)):box.setValue(limit)
        self.angles.setCurrentText('RAD' if flags[0] else 'GRAD' if flags[1] else 'DEG')
        self.canvas.set_bounds((lower.real,upper.real,lower.imag,upper.imag));self.canvas.image=grob_image(grob['raw']);self.canvas.update()
        self.status.setText('Click for coordinates. Drag to pan. Scroll to zoom.')
    def fetch_source(self,include_expression=False):
        source="'PPAR' RCL 1 GET 'PPAR' RCL 2 GET PICT RCL -17 FS? -18 FS? 2 →LIST 'PPAR' RCL 6 GET →STR 'PPAR' RCL 3 GET IF DUP TYPE 5 == THEN 1 GET END →STR "
        if include_expression:source+="IFERR 'EQ' RCL IF DUP TYPE 5 == THEN 1 « →STR » DOLIST ELSE →STR END THEN DROP \"\" END "
        return source+('7 →LIST' if include_expression else '6 →LIST')
    def load(self):
        source="IFERR 'PPAR' RCL DROP THEN (-6.5,-3.1) PMIN (6.5,3.2) PMAX END "+self.fetch_source(include_expression=True)
        self.query(source,self.fetched)
    def expressions(self):return [s.strip() for s in self.expression.text().split(';') if s.strip()]
    def update_curves(self):
        for combo in (self.curve,self.other_curve):
            index=combo.currentIndex();combo.clear();combo.addItems(self.expressions());combo.setCurrentIndex(max(0,min(index,combo.count()-1)))
        if self.other_curve.count()>1 and self.other_curve.currentIndex()==0:self.other_curve.setCurrentIndex(1)
    def apply_bounds(self):
        try:
            bounds=tuple(box.value() for box in self.limits);self.canvas.set_bounds(bounds);self.schedule_draw(bounds)
        except ValueError as exc:self.status.setText(str(exc))
    def plot(self):
        try:
            expressions=self.expressions()
            if not expressions:return
            bounds=tuple(box.value() for box in self.limits);self.canvas.set_bounds(bounds)
            xmin,xmax,ymin,ymax=bounds
            objects=' '.join(algebra(e) for e in expressions)
            eq=objects if len(expressions)==1 else objects+f' {len(expressions)} →LIST'
            source=(eq+f" 'EQ' STO {self.angles.currentText()} {self.plot_type.currentText()} "
                    +quote_name(self.variable.text().strip())+f' INDEP ({xmin:.12g},{ymin:.12g}) PMIN ({xmax:.12g},{ymax:.12g}) PMAX ERASE DRAX DRAW '+self.fetch_source())
            self.query(source,self.fetched)
        except Exception as exc:self.status.setText(str(exc))
    def pick(self,x,y):
        self.a.setValue(x)
        if self.operation.currentText()=='Trace' and self.curve.count():self.analyze()
        else:self.status.setText(f'x = {x:.12g}    y = {y:.12g}')
    def analyze(self):
        try:
            if self.plot_type.currentText()!='FUNCTION':raise ValueError('Curve analysis currently requires FUNCTION mode.')
            kind=self.operation.currentText()
            source=analysis_source(kind,self.curve.currentText(),self.other_curve.currentText(),self.a.value(),self.b.value(),self.variable.text().strip())
            self.status.setText('Calculating with the HP ROM…')
            def done(value):
                if kind=='Extremum' and isinstance(value,list):
                    x,y,curvature=value
                    label='Minimum' if curvature>0 else 'Maximum' if curvature<0 else 'Stationary point (not classified)'
                    self.status.setText(f'{label}: x = {x}, y = {y}')
                    self.canvas.mark=(float(x),float(y));self.canvas.update()
                else:self.status.setText(f'{kind}: {value}')
                if kind=='Trace':
                    try:self.canvas.mark=(self.a.value(),float(value));self.canvas.update()
                    except (ValueError,TypeError):pass
            self.query(source,done)
        except Exception as exc:self.status.setText(str(exc))
    def schedule_draw(self,bounds):self.pending=bounds;self.debounce.start(200)
    def redraw(self):
        if self.pending is None:return
        if self.drawing or self.window.session.querying or self.window.session.transferring:self.debounce.start(150);return
        bounds=self.pending;self.pending=None;self.drawing=True;self.status.setText('Redrawing with the HP calculator…')
        xmin,xmax,ymin,ymax=bounds
        source=f'({xmin:.12g},{ymin:.12g}) PMIN ({xmax:.12g},{ymax:.12g}) PMAX ERASE DRAX DRAW '+self.fetch_source()
        def done(value,error):
            self.drawing=False
            if error:self.status.setText(error)
            elif self.pending is None:self.fetched(value)
            if self.pending is not None:self.debounce.start(150)
        self.window.session.query(source,done)
    def export(self):
        if self.canvas.image.isNull():return
        path,_=QFileDialog.getSaveFileName(self,'Export HP plot','plot.png','PNG image (*.png)')
        if path and not self.canvas.image.save(path,'PNG'):self.status.setText('Could not save image')
    def copy_image(self):
        if not self.canvas.image.isNull():QApplication.clipboard().setImage(self.canvas.image)
    def closeEvent(self,event):self.debounce.stop();self.pending=None;event.accept()
