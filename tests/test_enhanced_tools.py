import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sympy as s
import pytest
from PySide6.QtWidgets import QApplication
from hp48g.enhanced_tools import hp_source,EnhancedTools
from hp48g.rom_codec import decode_real
from hp48g.rom_session import save_checkpoint
from test_rom import native
from test_rom_desktop import wait_for


def test_unsupported_results_stay_on_host():
    for value in (s.oo,s.nan,s.Integer(10)**600,s.Integral(s.Symbol('x'))):
        with pytest.raises(ValueError):hp_source(value)
    assert hp_source([1,2])=='{ 1.00000000000 2.00000000000 }'
    assert hp_source(s.Symbol('x')**2)=="'(x)^(2)'"
    assert hp_source(s.sin(s.Symbol('x')))=="'SIN(x)'"


def test_enhanced_result_transfer_preserves_rom_stack(native,monkeypatch):
    from hp48g.rom_window import RomWindow
    app=QApplication.instance() or QApplication([])
    core,_,profile=native
    core.execute("CLEAR 91 42 'KEEP' STO");core.request('SAVE');core.close()
    save_checkpoint(profile,profile/'calculator.hp48state')
    monkeypatch.setattr(EnhancedTools,'import_legacy',lambda self:None)
    window=RomWindow(profile);errors=[];window.problem=errors.append
    wait_for(lambda:window.session is not None)
    ready=[];window.session.ready.connect(lambda:ready.append(True));wait_for(lambda:ready)
    try:
        window.open_enhanced();tools=window.enhanced_tools
        wait_for(lambda:not window.session.querying)
        tools.runner.asynchronous=False;tools.source.setText('2 3 +');tools.calculate()
        assert tools.results==[5]
        tools.push_value(tools.results[0]);wait_for(lambda:not window.session.querying)
        reply=[];window.session.request('EXPORT','1',reply.append);wait_for(lambda:reply)
        assert reply[0].get('ok'),(reply,tools.status.text())
        assert decode_real(reply[0]['object'])==5
        reply=[];window.session.request('EXPORT','2',reply.append);wait_for(lambda:reply)
        assert decode_real(reply[0]['object'])==91
        tools.push_value(s.oo);assert 'infinite' in tools.status.text()
        # A failed ROM action must not append an error or disturb existing levels.
        result=[];window.session.query('1 0 /',lambda value,error:result.append((value,error)),keep_result=True)
        wait_for(lambda:result);assert result[0][1]
        tools.read_stack();wait_for(lambda:'Copied from HP stack' in tools.status.text())
        assert float(tools.results[0])==5
        matrix=s.Matrix([[1,2],[3,4]])
        tools.push_value(matrix);wait_for(lambda:not window.session.querying)
        tools.read_stack();wait_for(lambda:'Copied from HP stack' in tools.status.text())
        assert tools.results[0].applyfunc(float)==matrix.applyfunc(float)
        assert float(tools.memory['KEEP'])==42
        tools.push_value(s.sin(s.Symbol('x')));wait_for(lambda:not window.session.querying)
        assert 'Result added' in tools.status.text(),tools.status.text()
        tools.source.setText("'x^3' x DIFF");assert tools.save()
        snapshot=tools.snapshot();tools.source.clear();tools.restore(snapshot)
        assert tools.source.text()=="'x^3' x DIFF"
        assert not errors
    finally:
        window.close();wait_for(lambda:window.done)


def test_legacy_workspace_recovery_keeps_original_file(tmp_path,monkeypatch):
    from hp48g.app import MainWindow
    from hp48g.rom_window import RomWindow
    from hp48g.serialization import write_json
    from PySide6.QtCore import QStandardPaths
    app=QApplication.instance() or QApplication([])
    old=MainWindow(asynchronous=False,interactive=False)
    old.calc.stack=[s.Integer(17)];old.calc.variables={'answer':s.Integer(42)}
    old.plot.expr.setText('x^2');old.data.setPlainText('1\n2\n3')
    path=tmp_path/'workspace.json';write_json(path,old.session_data());original=path.read_bytes();old.close()
    monkeypatch.setattr(QStandardPaths,'writableLocation',lambda _:str(tmp_path))
    window=RomWindow(tmp_path/'profile')
    try:
        window.open_enhanced();tools=window.enhanced_tools
        assert tools.results==[17,42]
        assert tools.plot.expr.text()=='x^2'
        assert tools.data.toPlainText()=='1\n2\n3'
        assert path.read_bytes()==original
        assert tools.save()
        saved=tools.path.read_bytes()
        tools.source.setText('changed')
        from hp48g.serialization import read_json
        tools.restore(read_json(tools.path))
        assert tools.source.text()!='changed'
        assert tools.path.read_bytes()==saved
    finally:window.close();app.processEvents()


def test_default_launcher_opens_only_rom_calculator(tmp_path,monkeypatch):
    import sys
    import hp48g.app as launcher
    import hp48g.rom_window as rom
    import hp48g.rom_instance as instance
    import hp48g.platform_ui as platform
    import hp48g.macos_launcher as macos
    import hp48g.data_paths as paths
    monkeypatch.setattr(paths,"migrate_data",lambda:None)
    from types import SimpleNamespace
    opened=[]
    application=SimpleNamespace(setApplicationName=lambda _:None,setApplicationDisplayName=lambda _:None,
                                setWindowIcon=lambda _:None,setStyle=lambda _:None,setStyleSheet=lambda _:None,exec=lambda:0)
    monkeypatch.setattr(launcher,'QApplication',lambda args:application)
    monkeypatch.setattr(macos,'relaunch_as_application',lambda:None)
    monkeypatch.setattr(platform,'prepare_application_name',lambda:None)
    monkeypatch.setattr(platform,'application_icon',lambda:None)
    monkeypatch.setattr(rom,'default_directory',lambda:tmp_path)
    monkeypatch.setattr(rom,'RomWindow',lambda path:SimpleNamespace(show=lambda:opened.append(path)))
    monkeypatch.setattr(instance,'send_existing',lambda path,command:False)
    monkeypatch.setattr(sys,'argv',['hp48g'])
    with pytest.raises(SystemExit):launcher.main()
    assert opened==[tmp_path]
