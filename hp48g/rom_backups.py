"""Named snapshots and rolling recovery points for original calculator memory."""
from datetime import datetime,timezone
from pathlib import Path
import os
import re
import tempfile
from .rom_session import restore_checkpoint


def atomic_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.write-')
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class Backups:
    def __init__(self,directory):
        self.directory=Path(directory)/'backups';self.directory.mkdir(parents=True,exist_ok=True)
    def destination(self,label='Snapshot',automatic=False):
        label=re.sub(r'[^\w .-]','_',label).strip(' .')[:60] or 'Snapshot'
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        return self.directory/f'{"Auto" if automatic else label} — {stamp}.hp48state'
    def entries(self):return sorted(self.directory.glob('*.hp48state'),key=lambda p:p.stat().st_mtime,reverse=True)
    def prune(self,keep=10):
        automatic=[p for p in self.entries() if p.name.startswith('Auto — ')]
        for path in automatic[keep:]:path.unlink()
    def validated_bytes(self,path):
        data=Path(path).read_bytes()
        with tempfile.TemporaryDirectory() as runtime:restore_checkpoint(path,runtime)
        return data
    def import_file(self,path):
        data=self.validated_bytes(path);target=self.destination(Path(path).stem)
        atomic_bytes(target,data);return target
