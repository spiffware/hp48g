"""Codec/checkpoint tests plus real ROM execution when HP48G_TEST_ROM is set."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import zipfile
from decimal import Decimal

import pytest
from hp48g.rom_codec import (encode_text,decode_text,string_object,execution_object,object_size,
    import_binary,export_binary,decode_real,number_nibbles)
from hp48g.rom_session import restore_checkpoint,save_checkpoint
from hp48g.rom_setup import build_core,validate_rom


def test_hp_characters_and_native_object_roundtrip():
    source='« 1_m 2_cm + → x « x √ » »'
    assert decode_text(encode_text(source))==source
    assert encode_text(r'\<< \pi \-> \>>')==encode_text('« π → »')
    assert encode_text('x̄')==b'\x81'
    for obj in (string_object(source),execution_object(source)):
        assert object_size(obj)==len(obj)
        assert import_binary(export_binary(obj))==obj
    assert decode_real('339201000000000000550')==55
    with pytest.raises(ValueError):encode_text('🙂')


@pytest.mark.parametrize('data',[b'',b'HPHP48-R',b'HPHP48-R\x2c\x2a\x00',b'HPHP48-R'+bytes.fromhex('2c2a00ffff')])
def test_invalid_binary(data):
    with pytest.raises(ValueError):import_binary(data)


def test_checkpoint_roundtrip_and_no_path_escape(tmp_path):
    runtime=tmp_path/'runtime';runtime.mkdir();(runtime/'state').write_bytes(bytes.fromhex('48503438010301')+bytes(364));(runtime/'ram').write_bytes(bytes(131072))
    archive=tmp_path/'saved';save_checkpoint(runtime,archive)
    restored=tmp_path/'restored';restored.mkdir();restore_checkpoint(archive,restored)
    assert (restored/'ram').read_bytes()==bytes(131072)
    with zipfile.ZipFile(archive,'a') as z:z.writestr('../escape',b'bad')
    with pytest.raises(ValueError):restore_checkpoint(archive,restored)
    assert not (tmp_path/'escape').exists()


class Core:
    def __init__(self,binary,profile):
        self.process=subprocess.Popen([str(binary),str(profile)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.responses=queue.Queue();self.frames=[];self.audio=[];self.sequence=0
        def read():
            for line in self.process.stdout:
                data=json.loads(line)
                if 'frame' in data:self.frames.append(data)
                elif 'audio' in data:self.audio.append(data['audio'])
                else:self.responses.put(data)
        threading.Thread(target=read,daemon=True).start()
        assert self.responses.get(timeout=10)['ready']
    def request(self,verb,args=''):
        self.sequence+=1
        self.process.stdin.write(f'{verb} {self.sequence} {args}\n');self.process.stdin.flush()
        result=self.responses.get(timeout=10)
        assert result['id']==self.sequence
        assert result['ok'],result
        return result
    def idle(self):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            status=self.request('STATUS')
            if status['idle'] and not status['busy']:return
            time.sleep(.03)
        raise AssertionError('Calculator did not become idle')
    def key(self,index):
        self.request('KEY',f'{index} 1');time.sleep(.08)
        self.request('KEY',f'{index} 0');time.sleep(.08)
    def execute(self,source):
        self.idle();self.request('PUSH',execution_object(source));self.key(14);self.idle()
        return self.request('EXPORT','1')['object']
    def close(self):
        if self.process.poll() is None:
            self.request('QUIT');self.process.wait(timeout=3)


@pytest.fixture
def native(tmp_path):
    rom=os.environ.get('HP48G_TEST_ROM')
    if not rom:pytest.skip('Set HP48G_TEST_ROM to a revision R ROM to run native conformance tests')
    validate_rom(Path(rom).read_bytes())
    binary=build_core(tmp_path/'build');profile=tmp_path/'profile';profile.mkdir();shutil.copyfile(rom,profile/'rom')
    for name in ('port1','port2'):(profile/name).write_bytes(bytes(131072))
    core=Core(binary,profile)
    time.sleep(.6)
    for attempt in range(5):
        core.key(44);time.sleep(.25);core.key(5);time.sleep(.5)
        memory=core.request('READ','806ee 5')['nibbles']
        if int(memory[::-1],16)>=0x80000:break
    assert int(memory[::-1],16)>=0x80000, 'ROM did not initialize'
    core.idle()
    yield core,binary,profile
    core.close()


@pytest.mark.parametrize('source,expected',[
    ('CLEAR 2 3 +',5),
    ('CLEAR 0 1 10 FOR i i + NEXT',55),
    ('CLEAR 1_m 1_cm + 1_cm CONVERT UVAL',101),
    ('CLEAR 1 SF 1 FS?',1),
    ('CLEAR -17 SF -17 FS?',1),
    ('CLEAR { 1 2 3 } 1 « SQ » DOLIST LIST→ DROP + +',14),
    ('CLEAR [[ 1 2 ][ 3 4 ]] DET',-2),
    ('CLEAR 5 2 COMB',10),
    ('CLEAR IFERR 1 0 / THEN 42 END',42),
    ('CLEAR 4 → x « x SQ »',16),
    ("CLEAR 'x^3' 'x' ∂ 2 'x' STO EVAL",12),
    ("CLEAR 123 :1:PORTVAL STO :1:PORTVAL RCL",123),
])
def test_original_commands(native,source,expected):
    core,_,_=native
    assert decode_real(core.execute(source))==Decimal(expected)


def test_native_program_graphics_and_persistence(native):
    core,binary,profile=native
    program=core.execute('CLEAR « 7 SQ »')
    assert import_binary(export_binary(program))==program
    core.request('PUSH',program);core.key(14);core.idle()
    assert decode_real(core.request('EXPORT','1')['object'])==49
    grob=core.execute('CLEAR # 16d # 8d BLANK')
    assert grob.startswith(number_nibbles(0x2b1e))
    assert import_binary(export_binary(grob))==grob
    # Strip the UserRPL wrapper, leaving an original System RPL secondary.
    assert program[5:10]==number_nibbles(0x2361e)
    assert program[-10:-5]==number_nibbles(0x23639)
    system_program=program[:5]+program[10:-10]+program[-5:]
    core.request('PUSH',import_binary(export_binary(system_program)));core.key(14);core.idle()
    assert decode_real(core.request('EXPORT','1')['object'])==49
    # Saturn code objects are transferred without conversion to Python objects.
    code=number_nibbles(0x2dcc)+number_nibbles(7)+'01'
    core.request('PUSH',import_binary(export_binary(code)))
    assert core.request('EXPORT','1')['object']==code
    core.execute("CLEAR 55 'SAVED' STO 55")
    core.request('SAVE');core.close()
    checkpoint=profile/'checkpoint';save_checkpoint(profile,checkpoint)
    restore_checkpoint(checkpoint,profile)
    restarted=Core(binary,profile)
    try:
        time.sleep(.5);restarted.idle()
        assert decode_real(restarted.request('EXPORT','1')['object'])==55
        assert decode_real(restarted.execute("CLEAR 'SAVED' RCL"))==55
        assert len(restarted.frames[-1]['frame'])==2176
    finally:restarted.close()


def test_failed_checkpoint_preserves_previous_save(tmp_path):
    runtime=tmp_path/'runtime';runtime.mkdir()
    (runtime/'state').write_bytes(b'truncated')
    (runtime/'ram').write_bytes(bytes(131072))
    destination=tmp_path/'saved';destination.write_bytes(b'previous checkpoint')
    with pytest.raises(ValueError):save_checkpoint(runtime,destination)
    assert destination.read_bytes()==b'previous checkpoint'


def test_original_window_keyboard_and_setup(tmp_path):
    from PySide6.QtWidgets import QApplication
    from hp48g.rom_window import RomWindow
    app=QApplication.instance() or QApplication([])
    window=RomWindow(tmp_path)
    assert window.session is None
    assert 'Download' in window.status.text()
    assert len(window.buttons)==49
    window.show_frame({'frame':'00'*1088,'annunciators':2,'on':True})
    assert window.buttons[31].text()=='PLOT'
    window.show_frame({'frame':'00'*1088,'annunciators':4,'on':True})
    assert window.buttons[18].text()=='S'
    window.close();app.processEvents()
