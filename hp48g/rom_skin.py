"""HP 48-style case and keycaps, using native Qt widgets and scalable text."""
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QFont,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QPushButton,QStyle,QStyleOptionButton,QStylePainter

CASE_STYLE = '''
QWidget#calculatorCase { background: #292d2e; border: 3px solid #191c1d; border-radius: 24px; }
QWidget#faceplate { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #626c6c,stop:0.5 #505b5d,stop:1 #414c4e); border: 1px solid #818987; border-radius: 17px; }
QLabel#brand { color: #f3f0e5; font-size: 13px; font-weight: bold; letter-spacing: 1px; }
QLabel#model { color: #f3f0e5; font-size: 25px; font-weight: bold; font-style: italic; }
QLabel#badge { color: #8ad7d7; font-size: 10px; font-weight: bold; }
QWidget#screenBezel { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #20292a,stop:0.18 #414c49,stop:0.9 #a4aaa0,stop:1 #d0ccb6); border: 2px solid #374242; border-radius: 12px; }
QLabel#annunciators { color: #334b42; background: #a5b394; font-size: 10px; }
QLabel#keyLegend { background: transparent; border: none; font-size: 10px; font-weight: bold; }
QLabel#alphaLegend { color: #eee8d6; background: transparent; border: none; font-size: 9px; }
QLabel#calculatorStatus { color: #dedfcf; background: transparent; font-size: 10px; }
QPushButton#hpKey { color: #f4f0df; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #606665,stop:0.13 #414749,stop:0.75 #303537,stop:1 #24282a); border: 1px solid #242829; border-top: 2px solid #969c96; border-bottom: 3px solid #1b2021; border-radius: 7px; font-size: 18px; font-weight: bold; padding: 1px; }
QPushButton#hpKey:hover { border-top-color: #d0d5c9; background: #4c5657; }
QPushButton#hpKey:pressed { background: #22292a; border-top: 3px solid #172021; border-bottom: 1px solid #79827e; padding-top: 3px; }
QPushButton#hpKey[soft="true"] { background: #ece8d8; color: #3c4545; border: 5px solid #303738; border-top-color: #747b76; font-size: 11px; }
QPushButton#hpKey[shift="left"] { color: #252b31; background: #b6a0d8; font-size: 25px; }
QPushButton#hpKey[shift="right"] { color: #253638; background: #83ccce; font-size: 25px; }
QToolButton#entryToggle { color: #d3ded8; background: transparent; border: none; font-size: 11px; padding: 5px; }
QPlainTextEdit#sourceEntry { color: #e5eee4; background: #293638; border: 1px solid #84938b; border-radius: 5px; font-size: 12px; }
'''


class CalculatorKey(QPushButton):
    """Size the key for its base legend; fit alternate labels only when painting."""
    def __init__(self,label):
        super().__init__(label)
        self.base_label=label

    def sizeHint(self):
        self.ensurePolished()
        option=QStyleOptionButton();self.initStyleOption(option)
        option.text=self.base_label
        content=self.fontMetrics().size(Qt.TextFlag.TextShowMnemonic,self.base_label)+QSize(8,4)
        return self.style().sizeFromContents(QStyle.ContentsType.CT_PushButton,option,content,self)

    def minimumSizeHint(self):
        return self.sizeHint()

    def label_rect(self,option):
        return self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,option,self).adjusted(4,1,-4,-1)

    def fitted_font(self,rect):
        font=QFont(self.font())
        # This does not change widget fonts or invalidate the keypad layout.
        while QFontMetrics(font).horizontalAdvance(self.text())>rect.width():
            if font.pixelSize()>0:
                if font.pixelSize()<=8:break
                font.setPixelSize(font.pixelSize()-1)
            else:
                if font.pointSizeF()<=6:break
                font.setPointSizeF(max(6,font.pointSizeF()-.5))
        return font

    def paintEvent(self,event):
        option=QStyleOptionButton();self.initStyleOption(option)
        rect=self.label_rect(option)
        option.text=''
        painter=QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton,option)
        painter.setFont(self.fitted_font(rect))
        if self.isDown():rect.translate(0,1)
        self.style().drawItemText(painter,rect,Qt.AlignmentFlag.AlignCenter,option.palette,
                                  self.isEnabled(),self.text(),self.foregroundRole())


def key_cell(index,label,left,right,alpha):
    if left==right:left=""
    cell=QWidget();layout=QVBoxLayout(cell);layout.setContentsMargins(1,0,1,0);layout.setSpacing(1)
    legend=QLabel(f'<span style="color:#cbb3ee">{left}</span> <span style="color:#8bdfdf">{right}</span>')
    legend.setObjectName('keyLegend');legend.setAlignment(Qt.AlignmentFlag.AlignCenter);legend.setFixedHeight(13)
    layout.addWidget(legend)
    button=CalculatorKey(label);button.setObjectName('hpKey');button.setMinimumHeight(32)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setAccessibleName(label)
    button.setProperty('soft',index<6)
    if index in (34,39):button.setProperty('shift','left' if index==34 else 'right')
    layout.addWidget(button)
    letter=QLabel(alpha);letter.setObjectName('alphaLegend');letter.setFixedHeight(10);letter.setAlignment(Qt.AlignmentFlag.AlignRight)
    layout.addWidget(letter)
    return cell,button


class PrintedLogo(QLabel):
    """Render photographed light ink directly over the case's own shading."""
    def __init__(self,path):
        from PySide6.QtGui import QImage,QColor,QPixmap
        super().__init__()
        source=QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32)
        # The screenshot's gray case is not part of the printed mark. Extract
        # its light ink as coverage, retaining the original letter contours.
        for y in range(source.height()):
            for x in range(source.width()):
                pixel=source.pixelColor(x,y)
                light=min(pixel.red(),pixel.green(),pixel.blue())
                alpha=round(255*max(0,min(1,(light-165)/70)))
                source.setPixelColor(x,y,QColor(243,240,229,alpha))
        self.setPixmap(QPixmap.fromImage(source))
        self.setScaledContents(True)
        self.setFixedSize(174,54)
        self.setAccessibleName('Hewlett Packard')
