"""Offline card changes applied through a backed-up calculator restart."""
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QFileDialog,QInputDialog
from .rom_tools import row_buttons
from .rom_backups import atomic_bytes
from .rom_session import restore_checkpoint,save_checkpoint


def card_sizes(port,model='GX'):
    if port not in (1,2):raise ValueError('Choose port 1 or 2')
    return (32768,131072) if port==1 or model=='SX' else tuple(131072*2**i for i in range(6))


def card_checkpoint(checkpoint,port,data=None,size=None):
    """Return a new checkpoint; never modify the source or silently truncate data."""
    with tempfile.TemporaryDirectory(prefix='hp48g-card-') as directory:
        runtime=Path(directory);restore_checkpoint(checkpoint,runtime)
        model='SX' if (runtime/'ram').stat().st_size==32768 else 'GX'
        target=runtime/f'port{port}'
        old=target.read_bytes() if target.exists() else b''
        if size is not None:
            if size not in card_sizes(port,model):raise ValueError('Unsupported card capacity')
            if size<len(old) and any(old):raise ValueError('A used card cannot be shrunk safely. Export it and create a new blank card instead.')
            data=old[:size]+bytes(max(0,size-len(old)))
        if data is not None and len(data) not in card_sizes(port,model):raise ValueError('Unsupported card image size')
        if data is None:target.unlink(missing_ok=True)
        else:target.write_bytes(data)
        output=runtime/'changed.hp48state';save_checkpoint(runtime,output)
        return output.read_bytes()


def merge_source():
    """Idempotently add GX port 1 to working RAM, returning free bytes."""
    return 'IF 1 PVARS SWAP DROP "SYSRAM" == NOT THEN 1 MERGE END MEM'


class CardManager(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Memory cards');self.resize(600,230)
        layout=QVBoxLayout(self)
        self.memory_info=QLabel('Working memory: reading…');self.memory_info.setWordWrap(True);layout.addWidget(self.memory_info)
        row_buttons(layout,[('Expand working memory to 256 KB',self.expand_memory),('Enable 4 MB storage card',self.enable_storage)])
        note=QLabel('Memory configuration and card contents are saved with this calculator profile and restored on launch. Storage is separate from working memory.');note.setWordWrap(True);layout.addWidget(note)
        self.port=QComboBox();self.port.addItems(['Port 1','Port 2']);layout.addWidget(self.port)
        self.status=QLabel('Card changes save a recovery backup and restart the calculator. Export a card to keep a portable copy.');self.status.setWordWrap(True);layout.addWidget(self.status)
        row_buttons(layout,[('New blank card…',self.new),('Mount image…',self.mount),('Export…',self.export)])
        row_buttons(layout,[('Resize…',self.resize_card),('Make independent',self.free_card),('Eject',self.eject),('Refresh',self.refresh)])
        self.port.currentIndexChanged.connect(self.refresh);self.refresh()
    def refresh(self):
        session=self.window.session
        if session:
            path=Path(session.runtime.name)/f'port{self.port.currentIndex()+1}'
            self.status.setText(f'{self.port.currentText()}: {path.stat().st_size//1024} KB' if path.exists() else f'{self.port.currentText()}: empty')
            if not session.querying and not session.transferring and not session.closing:
                self.setEnabled(False)
                def described(value,error):
                    self.setEnabled(True)
                    if self.window.session is not session:return
                    if error:self.memory_info.setText('Return to the normal stack and click Refresh to read working memory.');return
                    free,kind=value
                    capacity=(128 if session.model=='GX' else 32)+(path1.stat().st_size//1024 if kind=='SYSRAM' and path1.exists() else 0)
                    storage=Path(session.runtime.name)/'port2'
                    storage_kb=storage.stat().st_size//1024 if storage.exists() else 0
                    label='4 MB' if storage_kb==4096 else f'{storage_kb} KB'
                    working=f'{capacity} KB' if session.model=='GX' else 'SX'
                    self.memory_info.setText(f'Working memory: {working}; free: {float(free)/1024:.1f} KB. Storage card: {label}.')
                path1=Path(session.runtime.name)/'port1'
                source='MEM 1 PVARS SWAP DROP 2 →LIST' if path1.exists() else 'MEM "Absent" 2 →LIST'
                session.query(source,described)
    def expand_memory(self):
        session=self.window.session
        if not session:return
        if session.model!='GX':self.status.setText('The 256 KB option requires a GX ROM profile.');return
        path=Path(session.runtime.name)/'port1'
        if not path.exists() or path.stat().st_size!=131072:
            self.status.setText('Create or resize a port 1 card to 128 KB first, then expand working memory.');return
        self.setEnabled(False)
        def finish(message):
            self.setEnabled(True);self.refresh();self.status.setText(message)
        def merged(value,error):
            if error:finish(error);return
            session.save(lambda ok:finish(f'256 KB working memory enabled and saved. Free: {float(value)/1024:.1f} KB.' if ok else 'Memory expanded, but saving failed. Keep the calculator open and retry Save memory.'))
        def saved(ok):
            if not ok:finish('Wait for the current operation to finish, then try again.');return
            if self.window.session is not session:finish('Calculator changed; try again.');return
            session.query(merge_source(),merged)
        self.window.make_backup('Before expanding working memory',saved)
    def enable_storage(self):
        session=self.window.session
        if not session:return
        if session.model!='GX':self.status.setText('The 4 MB card requires a GX ROM profile.');return
        path=Path(session.runtime.name)/'port2'
        if path.exists() and path.stat().st_size==4194304:
            self.refresh();self.status.setText('The 4 MB storage card is already enabled; its contents are unchanged.');return
        self.port.blockSignals(True);self.port.setCurrentIndex(1);self.port.blockSignals(False)
        self.change(size=4194304)
    def capacity(self):
        model=getattr(self.window.session,'model','GX')
        sizes=card_sizes(self.port.currentIndex()+1,model)
        text,ok=QInputDialog.getItem(self,'Card capacity','Capacity:',[f'{s//1024} KB' for s in sizes],0,False)
        return int(text.split()[0])*1024 if ok else None
    def change(self,data=None,size=None):
        port=self.port.currentIndex()+1
        session=self.window.session
        if not session:return
        self.setEnabled(False)
        def failed(message):self.setEnabled(True);self.status.setText(message)
        def saved(ok):
            if not ok:failed('Wait for the calculator to finish its current operation.');return
            try:
                checkpoint=self.window.backups.entries()[0]
                result=card_checkpoint(checkpoint,port,data,size)
                atomic_bytes(self.window.directory/'cards-pending',b'1')
                self.window.restart_checkpoint(result);self.status.setText('Card updated. Calculator restarting…')
            except Exception as exc:failed(str(exc))
        def checked(memory,error=None):
            if error:failed(error);return
            if memory=='SYSRAM':failed('This card is merged into main memory. Make it independent before changing or ejecting it.');return
            self.window.make_backup('Before card change',saved)
        if (Path(session.runtime.name)/f'port{port}').exists():session.query(f'{port} PVARS SWAP DROP',checked)
        else:checked(None)
    def free_card(self):
        port=self.port.currentIndex()+1
        self.window.make_backup('Before freeing card',lambda ok:self.window.query(f'{{ }} {port} FREE "OK"',lambda _:self.refresh()) if ok else None)
    def new(self):
        size=self.capacity()
        if size is not None:self.change(bytes(size))
    def mount(self):
        path,_=QFileDialog.getOpenFileName(self,'Mount packed card image','','Card image (*.hp48card);;All files (*)')
        if path:
            try:
                if Path(path).stat().st_size>4194304:raise ValueError('Card image exceeds 4 MB')
                self.change(Path(path).read_bytes())
            except Exception as exc:self.status.setText(str(exc))
    def resize_card(self):
        size=self.capacity()
        if size is not None:self.change(size=size)
    def eject(self):self.change()
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export card',f'port{self.port.currentIndex()+1}.hp48card','Card image (*.hp48card)')
        if not path:return
        port=self.port.currentIndex()+1;session=self.window.session
        def saved(ok):
            if not ok:return
            try:
                atomic_bytes(path,(Path(session.runtime.name)/f'port{port}').read_bytes());self.status.setText('Card exported.')
            except Exception as exc:self.status.setText(str(exc))
        if session and not session.querying and not session.transferring:session.save(saved)
