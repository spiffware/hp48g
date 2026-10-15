"""Download pinned ROM fixtures for optional native conformance tests (never packaged)."""
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hp48g.rom_setup import ROM_CATALOG,install_rom

root=Path('.rom');root.mkdir(exist_ok=True)
for revision in ROM_CATALOG:
    path=install_rom(root/'fixtures'/revision,revision=revision)
    shutil.copyfile(path,root/('rom' if revision=='gxrom-r' else revision))
