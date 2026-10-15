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


@pytest.mark.parametrize('width',[500,560,700])
def test_shifted_labels_fit_without_moving_keypad(tmp_path,width):
    from PySide6.QtWidgets import QStyleOptionButton
    from PySide6.QtGui import QFontMetrics
    app=QApplication.instance() or QApplication([])
    window=RomWindow(tmp_path);window.resize(width,1100);window.show();app.processEvents()
    geometry=[button.geometry() for button in window.buttons]
    hints=[button.sizeHint() for button in window.buttons]
    positions=[button.mapTo(window,button.rect().topLeft()) for button in window.buttons]
    try:
        for annunciators in (2,1,4,0,2,0):
            window.show_frame({'frame':'00'*1088,'annunciators':annunciators,'on':True})
            app.processEvents()
            assert [button.geometry() for button in window.buttons]==geometry
            assert [button.sizeHint() for button in window.buttons]==hints
            assert [button.mapTo(window,button.rect().topLeft()) for button in window.buttons]==positions
            for button in window.buttons:
                option=QStyleOptionButton();button.initStyleOption(option)
                rect=button.label_rect(option)
                assert QFontMetrics(button.fitted_font(rect)).horizontalAdvance(button.text())<=rect.width()
    finally:window.close()


@pytest.mark.parametrize('size',[(550,192),(393,400),(786,384)])
def test_popup_choice_clicks_follow_scaled_rows(size):
    import json
    from pathlib import Path
    app=QApplication.instance() or QApplication([])
    lcd=LCD();lcd.resize(*size);lcd.show()
    frame=json.loads((Path(__file__).parent/'fixtures'/'solve-menu.json').read_text())
    lcd.update_frame(frame);app.processEvents()
    assert lcd.choice is not None and lcd.choice.rows==5 and lcd.choice.selected==0
    selected=[];lcd.choiceActivated.connect(selected.append)
    rect=lcd.display_rect()
    point=lambda x,y:QPoint(round(rect.x()+x*rect.width()/131),round(rect.y()+y*rect.height()/64))
    for row in range(5):QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(60,9+9*row))
    assert selected==[0,1,2,3,4]
    QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(5,20))
    QTest.mouseClick(lcd,Qt.MouseButton.RightButton,pos=point(60,18))
    QTest.mousePress(lcd,Qt.MouseButton.LeftButton,pos=point(60,9))
    QTest.mouseRelease(lcd,Qt.MouseButton.LeftButton,pos=point(60,18))
    assert len(selected)==5
    lcd.update_frame({'frame':frame['frame'],'on':False})
    QTest.mouseClick(lcd,Qt.MouseButton.LeftButton,pos=point(60,18));assert len(selected)==5
    lcd.close()


@pytest.mark.parametrize('name,rows',[('solve',5),('symbolic',5),('time',3),('stat',4),('choose',4)])
def test_choice_layout_detection_across_rom_menus(name,rows):
    import json
    from pathlib import Path
    from hp48g.rom_menu import choice_list
    frame=json.loads((Path(__file__).parent/'fixtures'/f'{name}-menu.json').read_text())
    menu=choice_list(bytes.fromhex(frame['frame']))
    assert menu and menu.rows==rows
    assert menu.row_at(menu.left+10,menu.first_y+4)==0
    assert menu.row_at(menu.left+10,menu.first_y+9*(rows-1)+4)==rows-1
    assert menu.row_at(menu.left-1,menu.first_y+4) is None
