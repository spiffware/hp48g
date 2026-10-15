"""Direct LCD menu selection must follow the scaled image, not the window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from hp48g.rom_window import LCD, RomWindow


@pytest.mark.parametrize('size',[(550,192),(393,400),(786,384)])
def test_lcd_menu_clicks_respect_scaling_and_margins(size):
    app=QApplication.instance() or QApplication([])
    lcd=LCD();lcd.resize(*size);lcd.show()
    lcd.update_frame({'frame':'00'*1088,'on':True})
    app.processEvents()
    selected=[];lcd.menuActivated.connect(selected.append)
    rect=lcd.display_rect()
    def point(x,y):
        return QPoint(round(rect.x()+x*rect.width()/131),round(rect.y()+y*rect.height()/64))
    for index in range(6):
        QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(index*22+10,60))
    assert selected==list(range(6))
    # Stack, letterbox, and right clicks do not operate calculator keys.
    QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(10,40))
    QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=QPoint(1,1))
    QTest.mouseClick(lcd,Qt.MouseButton.RightButton,pos=point(10,60))
    QTest.mousePress(lcd,Qt.MouseButton.LeftButton,pos=point(10,60))
    QTest.mouseRelease(lcd,Qt.MouseButton.LeftButton,pos=point(32,60))
    assert selected==list(range(6))
    QTest.mouseMove(lcd,point(10,60))
    assert lcd.cursor().shape()==Qt.CursorShape.PointingHandCursor
    lcd.update_frame({'frame':'00'*1088,'on':False})
    QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(10,60))
    assert selected==list(range(6))
    lcd.close()


def test_lcd_selection_uses_rom_key_tap(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=RomWindow(tmp_path);window.show();app.processEvents()
    class Session:
        def __init__(self):self.keys=[]
        def tap(self,index):self.keys.append(index)
    session=Session();window.session=session
    window.lcd.update_frame({'frame':'00'*1088,'on':True})
    rect=window.lcd.display_rect()
    QTest.mouseClick(window.lcd,Qt.MouseButton.LeftButton,
                    pos=QPoint(rect.x()+rect.width()*120//131,rect.y()+rect.height()*60//64))
    assert session.keys==[5]
    window.session=None;window.close()
