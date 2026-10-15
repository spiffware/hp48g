"""Reproducible build and ROM setup for the separate Saturn process."""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

NATIVE_SOURCE=Path(__file__).parent/'native'/'x48ng'
ROM_URL='https://www.hpcalc.org/hp48/pc/emulators/gxrom-r.zip'
ROM_SHA256='de3a5a07b0f00640f4ba3599ea4092e9473113aad75c04bd03d3e37c059b5b33'

ROM_CATALOG = {'sxrom-j': {'sha256': 'e5eb3af020e4910f35a7580a705cf0a46f3ba9d7ba5516582d98010c93af7c74', 'member': 'sxrom-j', 'size': 262144}, 'gxrom-p': {'sha256': 'c8771f37bfb849e23d71b9d84cb013cd69586ef7bd8e72f7e024dcd1555d1aaa', 'member': 'gxrom-p', 'size': 524288}, 'gxrom-k': {'sha256': '254a3fbc0450c7d53f12f44e746ed12b93c61da00392d1c8bdc359897781fd7d', 'member': 'gxrom-k', 'size': 524288}, 'gxrom-l': {'sha256': 'cc68f67a0febf11e27682831179a3f1d2cc521dae14b65847b964177d370af8a', 'member': 'gxrom-l', 'size': 524288}, 'gxrom-m': {'sha256': '3bbaaf6ffca61185fbd98df41e48308fcb937b84b1e2305e074d2dc33bcb8731', 'member': 'gxrom-m', 'size': 524288}, 'gxrom-r': {'sha256': 'de3a5a07b0f00640f4ba3599ea4092e9473113aad75c04bd03d3e37c059b5b33', 'member': 'gxrom-r', 'size': 524288}}

def identify_rom(data):
    digest=hashlib.sha256(data).hexdigest()
    for name,info in ROM_CATALOG.items():
        if digest==info["sha256"] and len(data)==info["size"]:return name
    raise ValueError("Unrecognized ROM. Supported: GX revisions K, L, M, P, R and SX revision J.")


def build_core(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    bundled=Path(__file__).parent/'native'/'bin'/('hp48g-rom-core.exe' if sys.platform=='win32' else 'hp48g-rom-core')
    if bundled.exists():
        destination=directory/bundled.name
        if not destination.exists() or hashlib.sha256(destination.read_bytes()).digest()!=hashlib.sha256(bundled.read_bytes()).digest():
            temporary=directory/(bundled.name+'.tmp');shutil.copy2(bundled,temporary);os.replace(temporary,destination)
        return destination
    files=sorted(p for p in NATIVE_SOURCE.rglob('*') if p.suffix in ('.c','.h'))
    digest=hashlib.sha256(b''.join(p.read_bytes() for p in files)+Path(__file__).read_bytes()+sys.platform.encode()+platform.machine().encode()).hexdigest()
    binary=directory/('hp48g-rom-core.exe' if sys.platform=='win32' else 'hp48g-rom-core'); stamp=directory/'source.sha256'
    if binary.exists() and stamp.exists() and stamp.read_text()==digest: return binary
    compiler=shutil.which(os.environ.get('CC','gcc' if sys.platform=='win32' else 'cc'))
    if compiler is None:raise RuntimeError('Install a C compiler for a source checkout, or use the standalone desktop package.')
    sources=[NATIVE_SOURCE/name for name in ('bridge.c','objects.c','emulator_api.c','romio.c','disconnected.c')]
    sources += [NATIVE_SOURCE/'core'/f'{name}.c' for name in ('emulate','memory','registers','timers','init','persistence')]
    output=directory/(f'hp48g-rom-core-{os.getpid()}.tmp'+('.exe' if sys.platform=='win32' else ''))
    command=[compiler,'-std=gnu11','-O2','-D_DEFAULT_SOURCE','-D_DARWIN_C_SOURCE','-D_GNU_SOURCE',
             '-DVERSION_MAJOR=1','-DVERSION_MINOR=3','-DPATCHLEVEL=1',f'-I{NATIVE_SOURCE}',f'-I{NATIVE_SOURCE / "core"}',
             *map(str,sources),'-o',str(output)]
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        if result.returncode: raise RuntimeError('Could not build Saturn core:\n'+result.stderr[-4000:])
        os.replace(output,binary);stamp.write_text(digest)
    finally: output.unlink(missing_ok=True)
    return binary


def validate_rom(data):
    identify_rom(data)
    return data


def install_rom(directory,source=None,revision='gxrom-r'):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if revision not in ROM_CATALOG:raise ValueError('Unsupported ROM revision')
    if source:data=Path(source).read_bytes()
    else:
        url='https://www.hpcalc.org/hp48/pc/emulators/'+revision+'.zip'
        request=urllib.request.Request(url,headers={'User-Agent':'HP48G-Desktop/0.3'})
        with urllib.request.urlopen(request,timeout=30) as response:data=response.read(1_000_001)
        if len(data)>1_000_000:raise ValueError('Unexpected ROM archive size')
    if data.startswith(b'PK'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates=[i for i in archive.infolist() if i.file_size in (262144,524288)]
            if len(candidates)!=1:raise ValueError('Choose an archive containing exactly one HP ROM')
            data=archive.read(candidates[0])
    name=identify_rom(data)
    if not source and name!=revision:raise ValueError('Downloaded ROM revision does not match the request')
    current=directory/'rom'
    if (directory/'calculator.hp48state').exists() and (not current.exists() or current.read_bytes()!=data):
        raise ValueError('Use a new calculator profile for a different ROM to preserve the existing memory.')
    fd,name=tempfile.mkstemp(dir=directory,prefix='.rom-')
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,current)
    finally:
        if os.path.exists(name):os.unlink(name)
    return current


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);parser.add_argument('--rom');parser.add_argument('--download-rom',action='store_true');parser.add_argument('--revision',choices=ROM_CATALOG,default='gxrom-r')
    args=parser.parse_args()
    if args.download_rom or args.rom: install_rom(args.directory,args.rom,args.revision)
    print(build_core(Path(args.directory)/'build'))

if __name__=='__main__': main()
