"""Qt transport and atomic checkpoints for the isolated GPL Saturn process."""
from pathlib import Path
import json
import os
import shutil
import tempfile
import zipfile
import time
import uuid
import hashlib
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, QLockFile
from .rom_setup import validate_rom, ROM_SHA256,ROM_CATALOG,identify_rom
from .rom_codec import execution_object, object_size, query_source, decode_value

FILES = {'state': 371, 'ram': 131072, 'port1': 4194304, 'port2': 4194304}


def validate_memory(contents):
    state=contents.get('state',b'');ram=contents.get('ram',b'')
    if len(state)!=371 or state[:7]!=bytes.fromhex('48503438010301'):
        raise ValueError('Invalid or incompatible Saturn CPU checkpoint')
    if len(ram) not in (32768,131072):raise ValueError('Invalid HP 48 RAM size')
    for name in ('port1','port2'):
        if name in contents:
            size=len(contents[name])
            valid=size in (32768,131072) if name=='port1' or len(ram)==32768 else 131072<=size<=4194304 and size&(size-1)==0
            if not valid:raise ValueError('Invalid memory card size')


def checkpoint_rom_hash(runtime):
    runtime=Path(runtime)
    if (runtime/'rom').exists():return hashlib.sha256(validate_rom((runtime/'rom').read_bytes())).hexdigest()
    if (runtime/'rom.sha256').exists():return (runtime/'rom.sha256').read_text()
    return ROM_SHA256


def save_checkpoint(runtime, destination):
    destination = Path(destination)
    contents={name:(Path(runtime)/name).read_bytes() for name in FILES if (Path(runtime)/name).exists()}
    validate_memory(contents)
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix='.checkpoint-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('rom.sha256', checkpoint_rom_hash(runtime))
                for file,data in contents.items():archive.writestr(file,data)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, destination)
    finally:
        if os.path.exists(name): os.unlink(name)


def restore_checkpoint(source, runtime):
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) - (set(FILES) | {'rom.sha256'}):
            raise ValueError('Unexpected files in calculator checkpoint')
        if not {'state', 'ram', 'rom.sha256'} <= set(names): raise ValueError('Incomplete calculator checkpoint')
        digest=archive.read('rom.sha256').decode() if archive.getinfo('rom.sha256').file_size==64 else ''
        matches=[info for info in ROM_CATALOG.values() if info['sha256']==digest]
        if not matches:raise ValueError('Checkpoint uses an unsupported ROM')
        if (Path(runtime)/'rom').exists() and checkpoint_rom_hash(runtime)!=digest:raise ValueError('Checkpoint uses a different ROM')
        contents = {}
        for name, limit in FILES.items():
            if name in names:
                if archive.getinfo(name).file_size > limit: raise ValueError('Checkpoint file exceeds memory limits')
                contents[name] = archive.read(name)
        validate_memory(contents)
        expected_ram=32768 if matches[0]['size']==262144 else 131072
        if len(contents['ram'])!=expected_ram:raise ValueError('RAM does not match ROM model')
        (Path(runtime)/'rom.sha256').write_text(digest)
        for name, data in contents.items(): (Path(runtime)/name).write_bytes(data)


class RomSession(QObject):
    frame = Signal(dict)
    audio = Signal(dict)
    soundStopped = Signal()
    ready = Signal()
    error = Signal(str)
    stopped = Signal()

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = Path(directory).resolve()
        self.lock = QLockFile(str(self.directory/'session.lock'))
        if not self.lock.tryLock(0): raise RuntimeError('This original-calculator profile is already open.')
        self.runtime = tempfile.TemporaryDirectory(prefix='hp48g-rom-')
        self.buffer = bytearray(); self.sequence = 0; self.pending = {}; self.closing = False; self.transferring = False; self.querying = False; self.saving = False
        try:
            self.revision=identify_rom((self.directory/'rom').read_bytes());self.model='SX' if self.revision.startswith('sx') else 'GX'
            shutil.copyfile(self.directory/'rom', Path(self.runtime.name)/'rom')
            checkpoint = self.directory/'calculator.hp48state'
            self.fresh = not checkpoint.exists()
            if checkpoint.exists(): restore_checkpoint(checkpoint, self.runtime.name)
            else:
                for name in ('port1', 'port2'): (Path(self.runtime.name)/name).write_bytes(bytes(131072))
        except Exception:
            self.runtime.cleanup(); self.lock.unlock(); raise
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.log = ''
        self.watchdog=QTimer(self);self.watchdog.setInterval(100);self.watchdog.timeout.connect(self._expire_requests);self.watchdog.start()
        self.process.start(str(self.directory/'build'/('hp48g-rom-core.exe' if sys.platform=='win32' else 'hp48g-rom-core')), [self.runtime.name])

    def _process_error(self,error):
        self.error.emit(self.process.errorString())
        if error==QProcess.ProcessError.FailedToStart:
            self.watchdog.stop();self.runtime.cleanup();self.lock.unlock();self.stopped.emit()

    def _stderr(self):
        self.log = (self.log + bytes(self.process.readAllStandardError()).decode(errors='replace'))[-8000:]

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n' in self.buffer:
            line, _, rest = self.buffer.partition(b'\n'); self.buffer = bytearray(rest)
            try: data = json.loads(line)
            except (ValueError, UnicodeError): self.error.emit('Invalid response from Saturn core'); continue
            if 'frame' in data: self.frame.emit(data)
            elif 'audio' in data:self.audio.emit(data['audio'])
            elif data.get('ready'): self.ready.emit()
            elif data.get('id') in self.pending:
                callback, deadline = self.pending.pop(data['id'])
                if callback: callback(data)
                elif not data.get('ok'): self.error.emit(data.get('message', 'Calculator request failed'))

    def request(self, verb, args='', callback=None):
        if self.process.state() != QProcess.ProcessState.Running:
            if callback:callback({'ok':False,'message':'Calculator is not running'})
            else:self.error.emit('Calculator is not running')
            return
        self.sequence += 1; identifier = self.sequence
        self.pending[identifier] = callback, time.monotonic()+10
        self.process.write(f'{verb} {identifier} {args}\n'.encode('ascii'))

    def _expire_requests(self):
        now=time.monotonic()
        for identifier,(callback,deadline) in list(self.pending.items()):
            if deadline>now:continue
            self.pending.pop(identifier,None)
            result={'ok':False,'message':'Calculator request timed out'}
            if callback:callback(result)
            else:self.error.emit(result['message'])

    def key(self, index, down):
        if index==44 and down:self.soundStopped.emit()
        self.request('KEY', f'{index} {int(down)}')

    def tap(self, index):
        self.key(index, True)
        QTimer.singleShot(80, lambda: self.key(index, False) if not self.closing else None)

    def push(self, nibbles, evaluate=False, completed=None):
        if self.transferring or self.querying: raise ValueError('Wait for the previous desktop operation to finish')
        if object_size(nibbles) != len(nibbles): raise ValueError('Invalid native object')
        self.transferring=True
        def pushed(result):
            QTimer.singleShot(200,lambda:setattr(self,'transferring',False))
            if not result.get('ok'): self.error.emit(result.get('message', 'Import failed')); return
            # EVAL evaluates an execution wrapper. ON refreshes the stack after a plain import.
            self.tap(14 if evaluate else 44)
            if completed:
                deadline=time.monotonic()+30
                def checked(reply):
                    if not reply.get('ok') or time.monotonic()>deadline:completed(False)
                    elif reply.get('idle') and not reply.get('busy'):completed(True)
                    else:QTimer.singleShot(60,poll)
                def poll():self.request('STATUS',callback=checked)
                QTimer.singleShot(250,poll)
        self.request('PUSH', nibbles, pushed)

    def execute(self, source, completed=None):
        if self.querying:raise ValueError('Wait for the desktop operation to finish')
        self.push(execution_object(source), evaluate=True, completed=completed)

    def query(self, source, callback):
        """Run one ROM query/action on an isolated stack, then consume its reply."""
        if self.querying or self.transferring or self.closing:
            callback(None,'Calculator is busy with another desktop operation');return
        self.querying=True;deadline=time.monotonic()+30;token=uuid.uuid4().hex
        def finish(value=None,error=None):
            self.querying=False;callback(value,error)
        def taken(reply):
            try:
                if not reply.get('ok'):raise ValueError(reply.get('message','Query failed'))
                packet=decode_value(reply['value'])
                if not isinstance(packet,list) or len(packet)!=3 or packet[2]!=token:
                    raise ValueError('Calculator query did not return its reply; the stack was left untouched')
                value,ok,_=packet
                def consumed(result):
                    if not result.get('ok'):finish(error=result.get('message','Reply changed'));return
                    self.tap(44)
                    QTimer.singleShot(150,lambda:finish(value) if ok else finish(error=str(value)))
                self.request('CONSUME',reply['object'],consumed)
            except Exception as exc:finish(error=str(exc))
        def status(reply):
            if time.monotonic()>deadline:
                finish(error='Calculator operation timed out; use ON to interrupt it');return
            if reply.get('ok') and reply.get('idle') and not reply.get('busy'):
                self.request('EXPORT','1',taken)
            else:QTimer.singleShot(60,poll)
        def poll():self.request('STATUS',callback=status)
        def pushed(reply):
            if not reply.get('ok'):finish(error=reply.get('message','Query failed'));return
            self.tap(14);QTimer.singleShot(250,poll)
        try:self.request('PUSH',execution_object(query_source(source,token)),pushed)
        except Exception as exc:finish(error=str(exc))


    def rescan_cards(self,callback):
        """Power-cycle the guest so its ROM discovers changed card capacity."""
        self.tap(39)  # Right shift + ON is OFF, then ON preserves the stack.
        QTimer.singleShot(160,lambda:self.tap(44) if not self.closing else None)
        QTimer.singleShot(400,lambda:self.tap(44) if not self.closing else None)
        QTimer.singleShot(750,lambda:self.query('PINIT 0' if self.model=='GX' else '0',callback) if not self.closing else None)

    def save(self, callback=None, destination=None):
        if self.saving:
            if callback:callback(False)
            return
        self.saving=True
        def saved(result):
            self.saving=False
            try:
                if not result.get('ok'): raise RuntimeError(result.get('message', 'Save failed'))
                save_checkpoint(self.runtime.name, destination or self.directory/'calculator.hp48state')
            except Exception as exc:
                self.error.emit(str(exc))
                if callback: callback(False)
                return
            if callback: callback(True)
        self.request('SAVE', callback=saved)

    def close(self):
        if self.closing: return
        if self.saving:QTimer.singleShot(100,self.close);return
        def saved(ok):
            if ok:
                self.closing = True
                self.request('QUIT')
        for index in range(49): self.key(index,False)
        self.save(saved)

    def _finished(self, code, status):
        self.watchdog.stop();self.pending.clear()
        if not self.closing: self.error.emit(f'Saturn core stopped ({code}). {self.log[-1500:]}')
        self.runtime.cleanup(); self.lock.unlock(); self.stopped.emit()
