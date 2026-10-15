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


class CardManager(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.setWindowTitle('Memory cards');self.resize(600,230)
        layout=QVBoxLayout(self)
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
    def capacity(self):
        model=getattr(self.window.session,'model','GX')
        sizes=card_sizes(self.port.currentIndex()+1,model)
        text,ok=QInputDialog.getItem(self,'Card capacity','Capacity:',[f'{s//1024} KB' for s in sizes],0,False)
        return int(text.split()[0])*1024 if ok else None
    def change(self,data=None,size=None):
        port=self.port.currentIndex()+1
        def saved(ok):
            if not ok:self.status.setText('Wait for the calculator to finish its current operation.');return
            try:
                checkpoint=self.window.backups.entries()[0]
                result=card_checkpoint(checkpoint,port,data,size)
                self.window.restart_checkpoint(result);self.status.setText('Card updated. Calculator restarting…')
            except Exception as exc:self.status.setText(str(exc))
        def checked(memory):
            if memory=='SYSRAM':self.status.setText('This card is merged into main memory. Make it independent before changing or ejecting it.');return
            self.window.make_backup('Before card change',saved)
        self.window.query(f'{port} PVARS SWAP DROP',checked)
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
