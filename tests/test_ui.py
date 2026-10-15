import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('MPLCONFIGDIR','/tmp/hp48g-matplotlib')
import pytest
from PySide6.QtWidgets import QApplication
from hp48g.app import MainWindow,STYLE,encode,decode
from hp48g.engine import Calculator

@pytest.fixture(scope='module')
def window():
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(STYLE)
    w=MainWindow(asynchronous=False,interactive=False); w.show(); app.processEvents()
    yield w
    w.close()


def test_keypad(window):
    window.key('2'); window.key('ENTER'); window.key('3'); window.key('+')
    assert window.calc.stack==[5]
    window.key('ENTER'); assert window.calc.stack==[5,5]
    window.key('UNDO'); assert window.calc.stack==[5]
    window.key('SHIFT'); window.key('SIN'); assert 'Error' not in window.status.text()


def test_all_graph_modes(window):
    for index in range(window.plot.mode.count()):
        window.plot.mode.setCurrentIndex(index); window.plot.draw()
        assert 'error' not in window.plot.result.text().lower(),window.plot.result.text()


def test_session_codec():
    c=Calculator(); c.execute("1/3 (2+3*i) [[1,2],[3,4]] [1,2] « DUP * » 'x^2'")
    assert [decode(encode(v)) for v in c.stack]==c.stack


def test_statistics_and_units(window):
    window.calculate_stats(); assert 'Linear fit' in window.stats_result.toPlainText()
    window.convert_unit(); assert '3.280839' in window.unit_result.text()


def test_second_function_is_plotted(window):
    import numpy as np
    plot=window.plot
    plot.mode.setCurrentText('Function'); plot.angles.setCurrentText('RAD')
    plot.expr.setText('sin(x)'); plot.second.setText('cos(x)')
    plot.draw()
    curves={line.get_label():line for line in plot.figure.axes[0].lines}
    assert 'sin(x)' in curves and 'cos(x)' in curves
    assert np.allclose(curves['cos(x)'].get_ydata(),np.cos(curves['cos(x)'].get_xdata()))
    plot.second.clear(); plot.draw()
    assert 'cos(x)' not in [line.get_label() for line in plot.figure.axes[0].lines]
    plot.mode.setCurrentText('Polar')
    assert plot.second.isHidden() and plot.second_label.isHidden()
    plot.mode.setCurrentText('Parametric')
    assert not plot.second.isHidden() and plot.second_label.text()=='y(t)'


def test_function_redraw_preserves_custom_axes(window):
    plot=window.plot
    plot.mode.setCurrentText('Function'); plot.draw()
    ax=plot.figure.axes[0]
    # These are the same axis setters used by the toolbar's limits editor.
    ax.set_xlim(-4,6); ax.set_ylim(-2,3)
    plot.expr.setText('sin('); plot.draw()
    assert 'Graph error' in plot.result.text()
    assert plot.figure.axes[0] is ax
    plot.expr.setText('sin(x); x^2'); plot.second.setText('cos(x)')
    plot.draw()
    assert plot.figure.axes[0].get_xlim()==pytest.approx((-4,6))
    assert plot.figure.axes[0].get_ylim()==pytest.approx((-2,3))
    assert 'x^2' in [line.get_label() for line in plot.figure.axes[0].lines]
    plot.low.setText('-20'); plot.high.setText('20'); plot.draw()
    assert plot.figure.axes[0].get_xlim()==pytest.approx((-20,20))
    assert plot.figure.axes[0].get_ylim()==pytest.approx((-2,3))
    plot.toolbar.home()
    assert plot.figure.axes[0].get_ylim()==pytest.approx((-2,3))
    plot.mode.setCurrentText('Polar'); plot.draw()
    plot.mode.setCurrentText('Function'); plot.draw()
    assert plot.figure.axes[0].get_ylim()==pytest.approx((-2,3))


def test_collapsed_window_fits_calculator_frame(window):
    window.open_tools(1)
    QApplication.processEvents()
    expanded_size=window.size()
    expanded_split=window.splitter.sizes()
    expression=window.plot.expr.text()
    for _ in range(2):
        window.hide_tools_button.click()
        QApplication.processEvents()
        body=window.splitter.widget(0)
        assert window.tabs.isHidden()
        assert window.width()==window.splitter.width()==body.width()
        assert body.width()==expanded_split[0]
        window.open_tools(1)
        QApplication.processEvents()
        assert window.size()==expanded_size
        assert window.splitter.sizes()==expanded_split
        assert window.plot.expr.text()==expression
