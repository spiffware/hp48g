"""Regression coverage for desktop tools and cross-model native execution."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import shutil
import time
import zipfile
from decimal import Decimal
import pytest
from PySide6.QtWidgets import QApplication
from hp48g.rom_graph_math import analysis_source
from hp48g.rom_debugger import instrument,SourceDebugger
from hp48g.rom_cards import card_checkpoint,card_sizes
from hp48g.rom_background import ReminderStore,launch_command
from hp48g.rom_codec import decode_value,decode_real,query_source
from hp48g.rom_session import save_checkpoint,restore_checkpoint
from hp48g.rom_setup import build_core,identify_rom,ROM_CATALOG
from test_rom import native,Core
from test_rom_desktop import native_query,wait_for


def test_reminders_survive_restart_snooze_and_cancel(tmp_path):
    store=ReminderStore(tmp_path);a=store.add('First',10);b=store.add('Second',20)
    store=ReminderStore(tmp_path)
    assert [i['title'] for i in store.due(15)]==['First']
    assert not ReminderStore(tmp_path).due(15)
    store.snooze(a['id']);assert store.items[0]['status']=='pending'
    store.cancel(b['id']);assert not store.due(30)
    assert '--background' in launch_command(tmp_path)


def test_source_mapping_preserves_literals_and_declarations():
    text='«\n1 3 FOR i\n i SQ\nNEXT\n4 → x « x 2 + »\n"HALT test" { 1 2 }\n»'
    compiled,locations=instrument(text,'marker')
    assert 'FOR i' in compiled and '→ x «' in compiled
    assert '"HALT test"' in compiled and '{ 1 2 }' in compiled
    assert any(loc.line==3 for loc in locations.values())
    assert all(text[loc.start:loc.end] for loc in locations.values())


def test_card_changes_are_copy_on_write_and_preserve_checkpoint(native,tmp_path):
    core,_,profile=native
    core.execute('CLEAR 91');core.request('SAVE')
    original=tmp_path/'original';save_checkpoint(profile,original);before=original.read_bytes()
    changed=card_checkpoint(original,2,size=262144);target=tmp_path/'changed';target.write_bytes(changed)
    restored=tmp_path/'restored';restored.mkdir();restore_checkpoint(target,restored)
    assert (restored/'port2').stat().st_size==262144
    assert original.read_bytes()==before
    with pytest.raises(ValueError):card_checkpoint(original,2,data=bytes(393216))
    assert all(s&(s-1)==0 for s in card_sizes(2))
    target.write_bytes(card_checkpoint(original,1))
    other=tmp_path/'other';other.mkdir();restore_checkpoint(target,other);assert not (other/'port1').exists()


def test_rom_graph_analysis_preserves_stack_and_variables(native):
    core,_,_=native;core.execute("CLEAR 91 77 'X' STO")
    for kind,expression,other,a,b,expected in [
        ('Trace','X^2','',3,0,9),('Root','X^2-4','',1,3,2),
        ('Intersection','X^2','4',1,3,2),('Stationary point','(X-2)^2','',0,3,2),
        ('Integral','X^2','',0,1,Decimal('0.333333333333'))]:
        value=native_query(core,analysis_source(kind,expression,other,a,b))
        assert abs(float(value)-float(expected))<1e-9,(kind,value)
        assert native_query(core,"'X' RCL")==77
        assert decode_real(core.request('EXPORT','1')['object'])==91
    native_query(core,"'X' PURGE 0")
    assert native_query(core,analysis_source('Trace','X^2',a=3))==9
    assert native_query(core,"VARS 'X' POS")==0


def test_source_debugger_runs_loops_in_rom(native):
    core,_,_=native;token='testingmarker'
    source='« 0 1 3 FOR i i + NEXT »'
    compiled,locations=instrument(source,token)
    core.execute('CLEAR 91 '+compiled)
    seen=[]
    for _ in range(40):
        reply=core.request('EXPORT','1');marker=decode_value(reply['value'])
        assert marker[0]==token,marker
        index=int(marker[1]);core.request('CONSUME',reply['object']);seen.append(index)
        core.key(34);core.key(44);core.idle()
        if index==0:break
    else:pytest.fail('Debugger never completed')
    assert len(seen)>len(locations)
    assert decode_real(core.request('EXPORT','1')['object'])==6
    assert decode_real(core.request('EXPORT','2')['object'])==91
    reply=core.request('DEBUGSTATE');assert len(reply['stack'])>=2


@pytest.mark.parametrize('revision',['sxrom-j','gxrom-k','gxrom-l','gxrom-m','gxrom-p'])
def test_additional_rom_revisions(revision,tmp_path):
    rom=Path(os.environ.get('HP48G_TEST_ROM','.rom/rom')).parent/revision
    if not os.environ.get('HP48G_TEST_ROM') or not rom.exists():pytest.skip('Additional ROM fixtures not installed')
    assert identify_rom(rom.read_bytes())==revision
    profile=tmp_path/'profile';profile.mkdir();shutil.copyfile(rom,profile/'rom')
    core=Core(build_core(tmp_path/'build'),profile)
    try:
        time.sleep(.6)
        for _ in range(4):
            core.key(44);core.key(5);time.sleep(.3)
            addr='7056f' if revision.startswith('sx') else '806ee'
            if int(core.request('READ',addr+' 5')['nibbles'][::-1],16)>0x70000:break
        assert decode_real(core.execute('CLEAR 2 3 +'))==5
        assert decode_real(core.execute('CLEAR 0 1 10 FOR i i + NEXT'))==55
        core.request('SAVE');checkpoint=tmp_path/'saved';save_checkpoint(profile,checkpoint)
        core.close();restore_checkpoint(checkpoint,profile)
        core=Core(build_core(tmp_path/'build'),profile);time.sleep(.3);core.idle()
        assert decode_real(core.request('EXPORT','1')['object'])==55
    finally:core.close()


def test_source_debugger_desktop_breakpoints_and_watch(native):
    from hp48g.rom_window import RomWindow
    app=QApplication.instance() or QApplication([])
    core,_,profile=native
    core.execute("CLEAR 91 42 'ANSWER' STO");core.request('SAVE');core.close();save_checkpoint(profile,profile/'calculator.hp48state')
    window=RomWindow(profile);errors=[];window.problem=errors.append
    wait_for(lambda:window.session is not None);time.sleep(.15);app.processEvents()
    debugger=SourceDebugger(window,'«\n1\n2\n+\n»');debugger.watches.setText('ANSWER');debugger.breakpoints.setText('4')
    try:
        debugger.start();wait_for(lambda:debugger.location is not None)
        wait_for(lambda:not window.session.querying)
        assert debugger.location.line==2
        wait_for(lambda:debugger.state.topLevelItemCount()>0)
        assert debugger.state.topLevelItem(0).text(1)=='42'
        debugger.resume();wait_for(lambda:debugger.location.line==4 and not debugger.waiting)
        wait_for(lambda:not window.session.querying)
        debugger.step();wait_for(lambda:not debugger.active)
        time.sleep(.5);app.processEvents()
        reply=[];window.session.request('EXPORT','1',reply.append);wait_for(lambda:reply)
        assert decode_real(reply[0]['object'])==3
        assert not errors,errors
    finally:
        debugger.close();window.close();wait_for(lambda:window.done)


def test_waveform_pcm_and_windows_wake_xml(tmp_path):
    import xml.etree.ElementTree as ET
    import numpy as np
    from hp48g.rom_audio import ToneStream
    from hp48g.rom_wake import windows_task,wake_id
    app=QApplication.instance() or QApplication([])
    stream=ToneStream();samples=np.array([12000,-12000,0,6000],dtype='<i2');stream.add_pcm(samples.tobytes())
    assert stream.readData(8)==samples.tobytes()
    item={'id':'a'*32,'at':time.time()+3600}
    root=ET.fromstring(windows_task(tmp_path,item));namespace={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert root.find('t:Settings/t:WakeToRun',namespace).text=='true'
    with pytest.raises(ValueError):wake_id({'id':'../bad'})


def test_rom_extrema_and_failure_restore_variable(native):
    core,_,_=native;core.execute("CLEAR 91 77 'X' STO")
    result=native_query(core,analysis_source('Extremum','(X-2)^2',a=0,b=3))
    assert result==[2,0,2]
    core.execute(query_source(analysis_source('Trace','1/0',a=3)))
    value,ok=decode_value(core.request('TAKE')['value']);assert not ok
    assert native_query(core,"'X' RCL")==77
    assert decode_real(core.request('EXPORT','1')['object'])==91


def test_merged_card_stack_access_and_safe_unmerge(native):
    core,_,_=native;core.execute('CLEAR 91')
    assert native_query(core,'1 MERGE 1 PVARS SWAP DROP')=='SYSRAM'
    assert decode_real(core.request('EXPORT','1')['object'])==91
    assert native_query(core,'{ } 1 FREE 1 PVARS SWAP DROP')>0
    assert decode_real(core.request('EXPORT','1')['object'])==91


def test_wake_launch_request_is_scoped_and_quoted(tmp_path,monkeypatch):
    import plistlib
    import hp48g.rom_wake as wake
    commands=[]
    monkeypatch.setattr(wake.sys,'platform','darwin')
    monkeypatch.setattr(wake.Path,'home',classmethod(lambda cls:tmp_path))
    monkeypatch.setattr(wake.subprocess,'run',lambda args,**kwargs:commands.append(args))
    item={'id':'b'*32,'at':time.time()+3600}
    directory=tmp_path/'profile with spaces'
    wake.schedule_wake(directory,item)
    path=next((tmp_path/'Library/LaunchAgents').glob('*.plist'))
    data=plistlib.loads(path.read_bytes())
    assert data['ProgramArguments'][-1]==str(directory)
    assert commands[-1][0]=='/usr/bin/osascript'
    assert 'wakeorpoweron' in commands[-1][-1]
    wake.cancel_wake(item)
    assert not path.exists()
    assert 'cancel wakeorpoweron' in commands[-1][-1]
