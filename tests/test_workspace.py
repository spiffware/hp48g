import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('MPLCONFIGDIR','/tmp/hp48g-matplotlib')
import copy
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from hp48g.app import MainWindow,STYLE
from hp48g.serialization import read_json,calculator_state
from hp48g.jobs import JobRunner
from hp48g.engine import Calculator,CalculatorError

@pytest.fixture
def window():
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE)
    w=MainWindow(asynchronous=False,interactive=False); w.show(); app.processEvents()
    yield w
    w.close(); app.processEvents()


def wait_until(predicate,timeout=8):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:
        QApplication.processEvents(); time.sleep(.005)
    assert predicate(),'Timed out waiting for a calculation'


def test_full_workspace_roundtrip(window,tmp_path):
    w=window
    w.calc.execute("'sin(x^x)' x INT 2 'a' STO")
    w.plot.expr.setText('a*x'); w.plot.angles.setCurrentText('RAD'); w.plot.draw()
    w.plot.figure.axes[0].set_ylim(-3,7)
    w.plot.mode.setCurrentText('Polar'); w.plot.expr.setText('3*cos(t)'); w.plot.draw()
    w.solvers.fields['finance']['pv'].setText('12345')
    w.data.setPlainText('10\n20\n30'); w.calculate_stats()
    w.unit_value.setText('12'); w.convert_unit()
    w.entry.setText('unfinished entry')
    w.hide_tools_button.click(); QApplication.processEvents()
    path=tmp_path/'work.json'; w.save_to(path)
    expected=w.session_data()
    w.calc.execute('CLEAR'); w.data.clear(); w.plot.expr.setText('99')
    w.apply_session(read_json(path)); QApplication.processEvents()
    assert w.session_data()==expected
    w.plot.mode.setCurrentText('Function'); w.plot.draw()
    assert w.plot.expr.text()=='a*x'
    assert w.plot.figure.axes[0].get_ylim()==pytest.approx((-3,7))
    assert 'Integral' in str(w.calc.stack[0])


def test_invalid_workspace_does_not_modify_live_state(window):
    state=window.session_data(); broken=copy.deepcopy(state)
    broken['stack']=[]; broken['workspace']['graph']['mode']='bad'
    with pytest.raises((CalculatorError,KeyError,ValueError)): window.apply_session(broken)
    assert window.session_data()==state


def test_legacy_sessions(window):
    window.apply_session({'version':1,'stack':[{'expr':'Integral(sin(x**x), x)'}],'variables':{},'angle':'RAD','numeric':False})
    assert 'Integral' in str(window.calc.stack[0])


def test_all_stack_entries_are_accessible(window):
    window.calc.execute(' '.join(str(i) for i in range(25)))
    window.refresh(); assert '25:  0' in window.lcd.toPlainText() and '1:  24' in window.lcd.toPlainText()


def test_graph_selected_curve_and_transfer(window):
    p=window.plot; p.angles.setCurrentText('RAD'); p.expr.setText('x'); p.second.setText('x^2')
    p.low.setText('1'); p.high.setText('3'); p.curve.setCurrentText('x^2'); p.operation.setCurrentText('Integral'); p.calculate()
    p.send_button.click(); assert float(window.calc.stack[-1])==pytest.approx(26/3)
    window.undo(); assert window.calc.stack==[]
    p.low.setText('0'); assert not p.send_button.isEnabled()


def test_plot_errors_preserve_previous_graph_in_every_mode(window):
    p=window.plot
    for mode in ('Function','Polar','Parametric','Implicit','3D surface','Slope field','Histogram','Scatter'):
        p.mode.setCurrentText(mode); p.draw(); previous=p.figure
        p.expr.setText('invalid('); p.draw()
        assert p.figure is previous
        assert 'error' in p.result.text().lower()


def test_tool_results_reach_stack(window):
    window.calculate_stats(); window.stats_send.click(); assert list(map(float,window.calc.stack[-1]))==[2,4,5,8]
    window.convert_unit(); window.unit_send.click(); assert float(window.calc.stack[-1])==pytest.approx(3.28083989501312)


def test_autosave_and_restore(window,tmp_path):
    path=tmp_path/'autosave.json'; window.auto_path=path
    window.calc.execute('42'); window.entry.setText('draft'); window.autosave()
    other=MainWindow(asynchronous=False,auto_path=path,interactive=False)
    try: assert other.calc.stack==[42] and other.entry.text()=='draft'
    finally: other.close()


def test_worker_is_async_and_returns_results(window):
    runner=JobRunner(window); values=[]; failures=[]; ticks=[]
    QTimer.singleShot(10,lambda:ticks.append(True))
    runner.start('engine',{'state':calculator_state(Calculator()),'source':'2 3 +'},values.append,failures.append)
    assert runner.busy
    wait_until(lambda:values or failures)
    assert ticks and not failures and values[0]['stack']==[{'integer':'5'}]


def test_cancel_and_timeout_do_not_change_stack(window):
    runner=JobRunner(window); values=[]; failures=[]
    request={'state':calculator_state(window.calc),'source':'2 3 +'}
    runner.start('engine',request,values.append,failures.append); runner.cancel()
    wait_until(lambda:bool(failures)); assert not values and window.calc.stack==[]
    failures.clear(); runner.start('engine',request,values.append,failures.append); runner.timer.start(1)
    wait_until(lambda:bool(failures)); assert 'timed out' in failures[-1] and not values
    # Let terminated QProcesses finish before the owning window is destroyed.
    end=time.monotonic()+.1
    while time.monotonic()<end: QApplication.processEvents(); time.sleep(.005)


def test_redraw_keeps_physical_canvas_dimensions(window):
    p=window.plot; window.open_tools(1); QApplication.processEvents()
    before=p.canvas.get_width_height(physical=True); original_dpi=p.figure._original_dpi
    p.second.setText('cos(x)'); p.draw()
    assert p.canvas.get_width_height(physical=True)==before
    assert p.figure._original_dpi==original_dpi
    assert len(p.figure.axes)==1


def test_selected_statistics_result_and_stale_solver_values(window):
    from PySide6.QtWidgets import QPushButton
    window.calculate_stats(); window.stats_kind.setCurrentText('Mean'); window.stats_send.click()
    assert float(window.calc.stack[-1])==pytest.approx(4.75)
    panel=window.solvers.widget(2)
    next(button for button in panel.findChildren(QPushButton) if button.text()=='Calculate').click()
    assert window.solvers.send_buttons['probability'].isEnabled()
    window.solvers.fields['probability']['x'].setText('2')
    saved=window.solvers.snapshot()
    assert 'probability' not in saved['values']
    window.solvers.restore(saved)
    assert not window.solvers.send_buttons['probability'].isEnabled()


def test_stack_edit_uses_transaction_and_can_be_undone(window):
    window.calc.execute('5 6'); window.entry.setText('pending')
    window.execute_source('sin(90)','Stack value edited',replace=0)
    assert window.calc.stack==[1,6] and window.entry.text()=='pending'
    window.undo(); assert window.calc.stack==[5,6]
    window.execute_source('1/0','Stack value edited',replace=0)
    assert window.calc.stack==[5,6] and 'Error' in window.status.text()


def test_trace_and_toolbar_pan_work_after_redraw(window):
    from matplotlib.backend_bases import MouseEvent,MouseButton
    p=window.plot; window.open_tools(1); QApplication.processEvents()
    callbacks=p.canvas.callbacks
    p.angles.setCurrentText('RAD'); p.expr.setText('x'); p.second.clear(); p.draw()
    assert p.canvas.callbacks is callbacks
    ax=p.figure.axes[0]; x,y=ax.transData.transform((1,1))
    p.canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',p.canvas,x,y))
    assert 'Trace x:' in p.result.text()
    previous=ax.get_xlim(); p.toolbar.pan()
    for name,px in [('button_press_event',x),('motion_notify_event',x+30),('button_release_event',x+30)]:
        event=MouseEvent(name,p.canvas,px,y,button=MouseButton.LEFT,**({'buttons':{MouseButton.LEFT}} if name=='motion_notify_event' else {}))
        p.canvas.callbacks.process(name,event)
    p.toolbar.pan()
    assert ax.get_xlim()!=previous


def test_rpl_program_editor_and_persisted_modes(window,tmp_path):
    from hp48g.rpl_editor import ProgramEditor
    from hp48g.rpl_objects import RPLList,BinaryInteger
    from hp48g.engine import Program
    editor=ProgramEditor(window)
    editor.editor.setPlainText('« 0 1 10 FOR i i + NEXT »')
    assert editor.check()
    editor.add_to_stack(); assert isinstance(window.calc.stack[-1],Program)
    window.run('EVAL'); assert window.calc.stack==[55]
    window.execute_source("8 STWS 1 SF HEX 'work' CRDIR work { 1 2 } # FFh")
    path=tmp_path/'rpl-session.json'; window.save_to(path)
    window.execute_source('HOME 64 STWS 1 CF DEC CLEAR')
    window.apply_session(read_json(path))
    assert window.calc.rpl_state['wordsize']==8
    assert window.calc.rpl_state['flags']==[1]
    assert window.calc.rpl_state['path']==['work']
    assert window.calc.stack[-2:]==[RPLList([1,2]),BinaryInteger(255)]
    assert 'work' in window.mode_label.text()
    source=tmp_path/'example.rpl'; source.write_text('<< 2 3 + >>')
    editor.load_from(source); assert editor.program()==Program('2 3 +')
    assert window.calc.stack[-1]==BinaryInteger(255)
    editor.close(); window.close()
