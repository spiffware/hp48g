"""Build a standalone desktop app with its own Python, Qt and Saturn executable."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hp48g.rom_setup import build_core
from hp48g.platform_ui import DISPLAY_NAME


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',action='store_true');args=parser.parse_args()
    core=build_core(ROOT/'build'/'native')
    notices=ROOT/'build'/'notices';notices.mkdir(parents=True,exist_ok=True)
    packages=[]
    for name in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','numpy','scipy','sympy','matplotlib','PyInstaller'):
        distribution=importlib.metadata.distribution(name)
        packages.append({'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression',distribution.metadata.get('License','See included license files'))})
        for file in distribution.files or []:
            if any(part.lower().startswith(('license','copying','notice')) for part in file.parts):
                source=Path(distribution.locate_file(file))
                if source.is_file():
                    target=notices/name/str(file).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    (notices/'packages.json').write_text(json.dumps(packages,indent=2))
    shutil.copyfile(ROOT/'LICENSE',notices/'HP48G-LICENSE')
    name=DISPLAY_NAME if sys.platform=='darwin' else 'HP48G'
    icon=ROOT/'hp48g'/'assets'/('hp48gx-icon.icns' if sys.platform=='darwin' else 'hp48gx-icon.ico')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name',name,'--icon',str(icon),
             '--paths',str(ROOT),'--add-data',str(notices)+os.pathsep+'notices','--collect-data','hp48g','--hidden-import','PySide6.QtMultimedia',
             '--hidden-import','PySide6.QtNetwork','--add-binary',str(core)+os.pathsep+'hp48g/native/bin',
             '--add-data',str(ROOT/'hp48g/native/x48ng')+os.pathsep+'hp48g/native/x48ng',
             '--osx-bundle-identifier','org.hp48g.desktop',str(ROOT/'scripts/desktop_entry.py')]
    env=os.environ.copy();env['PYINSTALLER_CONFIG_DIR']=str(ROOT/'build'/'pyinstaller-cache')
    subprocess.run(command,cwd=ROOT,env=env,check=True)
    if args.archive:
        if sys.platform=='darwin':
            staging=ROOT/'build'/'dmg';staging.mkdir(exist_ok=True)
            app=staging/f'{name}.app'
            if app.exists():shutil.rmtree(app)
            shutil.copytree(ROOT/'dist'/f'{name}.app',app,symlinks=True)
            link=staging/'Applications'
            if not link.exists():link.symlink_to('/Applications')
            subprocess.run(['hdiutil','create','-volname','HP48G','-srcfolder',str(staging),'-ov','-format','UDZO',str(ROOT/'dist'/'HP48G-macOS.dmg')],check=True)
        elif sys.platform=='win32':shutil.make_archive(str(ROOT/'dist'/'HP48G-Windows'),'zip',ROOT/'dist','HP48G')
        else:
            with tarfile.open(ROOT/'dist'/'HP48G-Linux.tar.gz','w:gz') as archive:archive.add(ROOT/'dist'/'HP48G',arcname='HP48G')

if __name__=='__main__':main()
