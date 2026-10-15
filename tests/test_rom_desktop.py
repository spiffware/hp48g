import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import math
from pathlib import Path
import shutil
import time
import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from hp48g.rom_audio import ToneStream
from hp48g.rom_backups import Backups
from hp48g.rom_codec import decode_value,query_source,quote_text,decode_real
from hp48g.rom_graph import GraphCanvas,grob_image
from hp48g.rom_session import RomSession,save_checkpoint
from test_rom import native


def wait_for(predicate,seconds=10):
    end=time.monotonic()+seconds
    while not predicate() and time.monotonic()<end:
        QApplication.processEvents();time.sleep(.005)
    assert predicate(),'Timed out'


def test_audio_pcm_pitch_duration_and_silence():
    app=QApplication.instance() or QApplication([])
    stream=ToneStream();stream.add(440,.1)
    samples=np.frombuffer(stream.readData(8820),dtype='<i2')
    crossings=np.count_nonzero((samples[:-1]<=0)&(samples[1:]>0))
    assert 43<=crossings<=45
    assert len(samples)==4410 and not stream.tones
    assert not any(stream.readData(100))
    stream.add(float('nan'),1);stream.add(1,-1);assert not stream.tones


def test_backup_retention_never_deletes_named(tmp_path):
    backups=Backups(tmp_path)
    named=backups.destination('Keep me');named.write_bytes(b'named')
    for _ in range(14):backups.destination(automatic=True).write_bytes(b'auto')
    backups.prune()
    assert len(backups.entries())==11 and named.exists()
    invalid=tmp_path/'invalid';invalid.write_bytes(b'bad')
    with pytest.raises(Exception):backups.import_file(invalid)
    assert len(backups.entries())==11


def test_graph_coordinate_mapping_in_letterboxed_view():
    app=QApplication.instance() or QApplication([])
    canvas=GraphCanvas();canvas.resize(800,400);canvas.set_bounds((-10,10,-5,5))
    rect=canvas.image_rect()
    assert canvas.coordinate(QPointF(rect.topLeft()))==(-10,5)
    assert canvas.coordinate(QPointF(rect.bottomRight()))==(10,-5)
    with pytest.raises(ValueError):canvas.set_bounds((1,0,-1,1))


def native_query(core,source):
    core.execute(query_source(source))
    result=core.request('TAKE')
    value,ok=decode_value(result['value'])
    assert ok,value
    return value


def test_rom_queries_memory_graph_and_program_syntax(native):
    core,_,_=native
    core.execute("CLEAR 91 'NUMBER' STO « DUP SQ » 'PROGRAM' STO 'FOLDER' CRDIR 123")
    rows=native_query(core,'VARS 1 « DUP RCL DUP TYPE SWAP BYTES SWAP DROP 3 →LIST » DOLIST')
    assert {'NUMBER','PROGRAM','FOLDER'}=={row[0] for row in rows}
    assert decode_real(core.request('EXPORT','1')['object'])==123
    assert native_query(core,lambda saved:f'{saved} DUP SIZE GET →STR')=='123'
    assert native_query(core,quote_text('« 1 2 + »')+' STR→ DROP "OK"')=='OK'
    native_query(core,'(-6.5,-3.1) PMIN (6.5,3.2) PMAX \'X^2\' \'EQ\' STO FUNCTION ERASE DRAW "OK"')
    values=native_query(core,"'PPAR' RCL 1 GET 'PPAR' RCL 2 GET PICT RCL 3 →LIST")
    assert values[0]==complex(-6.5,-3.1)
    image=grob_image(values[2]['raw']);assert image.width()==131 and image.height()==64
    assert decode_real(core.request('EXPORT','1')['object'])==123
    native_query(core,"'FOLDER' EVAL 55 'INSIDE' STO HOME \"OK\"")
    assert 'INSIDE' in native_query(core,"'FOLDER' EVAL VARS")


def test_rom_beep_frequency_duration_and_mute(native):
    core,_,_=native;core.audio.clear()
    core.execute('CLEAR 440 .1 BEEP 1')
    assert any(event['frequency']==440 and event['duration']==.1 for event in core.audio)
    core.audio.clear();core.execute('-56 SF 880 .1 BEEP -56 CF 1')
    assert not core.audio


def test_qt_query_preserves_stack_and_reports_errors(native):
    app=QApplication.instance() or QApplication([])
    core,binary,profile=native
    core.execute('CLEAR 91');core.request('SAVE');core.close()
    save_checkpoint(profile,profile/'calculator.hp48state')
    (profile/'build').mkdir();shutil.copy2(binary,profile/'build'/binary.name)
    session=RomSession(profile);errors=[];session.error.connect(errors.append)
    ready=[];session.ready.connect(lambda:ready.append(True));wait_for(lambda:ready)
    try:
        for source,expected in [('2 3 +',5),('VARS',[]),('1 0 /',None)]:
            result=[];session.query(source,lambda value,error:result.append((value,error)))
            wait_for(lambda:result)
            if expected is None:assert result[0][1]
            else:assert result==[(expected,None)]
        result=[];session.request('EXPORT','1',result.append);wait_for(lambda:result)
        assert decode_real(result[0]['object'])==91
        assert not errors
    finally:
        stopped=[];session.stopped.connect(lambda:stopped.append(True));session.close();wait_for(lambda:stopped)


def test_alarm_uses_speaker_while_idle(native):
    core,_,_=native;core.audio.clear()
    core.execute('CLEAR DATE TIME HMS→ 3 3600 / + →HMS « 880 .1 BEEP » 3 →LIST STOALARM')
    deadline=time.monotonic()+8
    while time.monotonic()<deadline and not any(e['frequency']==880 for e in core.audio):time.sleep(.05)
    assert any(e['frequency']==880 and e['duration']==.1 for e in core.audio),core.audio


def test_rom_debugger_physical_menu_steps(native):
    core,_,_=native
    core.execute('CLEAR 91 « 1 2 + » 41 MENU')
    core.key(0);core.idle() # DBUG is an interactive menu operation, not a command name.
    for expected in (1,2,3):
        core.key(1);core.idle()
        assert decode_real(core.request('EXPORT','1')['object'])==expected
    core.key(34);core.key(44);core.idle() # Left-shift ON / CONT
    assert decode_real(core.request('EXPORT','1')['object'])==3


def test_desktop_backup_restore_clipboard_and_editor(native,tmp_path):
    from hp48g.rom_window import RomWindow
    from hp48g.rom_tools import RomProgramEditor,MemoryBrowser
    from hp48g.rom_graph import RomGraph
    app=QApplication.instance() or QApplication([])
    core,_,profile=native
    core.execute('CLEAR 91');core.request('SAVE');core.close();save_checkpoint(profile,profile/'calculator.hp48state')
    window=RomWindow(profile);errors=[];window.problem=errors.append
    window.show();wait_for(lambda:window.session is not None);time.sleep(.1);app.processEvents()
    def query(source):
        result=[];window.query(source,result.append);wait_for(lambda:result or errors);assert not errors,errors;return result[0]
    try:
        saved=[];window.make_backup('Baseline',saved.append);wait_for(lambda:saved);assert saved==[True]
        baseline=window.backups.entries()[0]
        query("42 'N' STO \"OK\"")
        window.copy_stack();wait_for(lambda:QApplication.clipboard().mimeData() is not None and QApplication.clipboard().mimeData().hasFormat('application/x-hp48-object'))
        assert QApplication.clipboard().text()=='91'
        editor=RomProgramEditor(window);editor.editor.setPlainText('1 2 +');editor.check()
        wait_for(lambda:not window.session.querying);assert not errors,errors
        assert editor.status.text()=='Syntax OK'
        assert window.save_draft() and (profile/'editor-draft.rpl').read_text()=='1 2 +'
        memory=MemoryBrowser(window);wait_for(lambda:not window.session.querying)
        assert memory.tree.topLevelItem(0).text(0)=='N'
        graph=RomGraph(window);wait_for(lambda:not window.session.querying)
        graph.angles.setCurrentText('RAD');graph.expression.setText('X^2');graph.plot();wait_for(lambda:not window.session.querying)
        assert not graph.canvas.image.isNull(),(errors,graph.status.text())
        assert graph.canvas.image.save(str(tmp_path/'plot.png'))
        graph.schedule_draw((-2,2,-1,5));wait_for(lambda:graph.pending is None and not graph.drawing)
        assert graph.canvas.bounds==(-2,2,-1,5)
        assert query("'PPAR' RCL 1 GET")==complex(-2,-1)
        old_session=window.session;window.restore_backup(baseline)
        wait_for(lambda:window.session is not None and window.session is not old_session)
        time.sleep(.1);app.processEvents()
        assert query("IFERR 'N' RCL THEN 0 END")==0
        assert any(p.name.startswith('Before restore') for p in window.backups.entries())
        assert query(lambda saved:f'{saved} DUP SIZE GET')==91
        editor.close();memory.close();graph.close()
    finally:
        window.close();wait_for(lambda:window.done);QApplication.clipboard().clear()
