"""Give source launches a real macOS application identity without freezing code."""
from pathlib import Path
import os
import plistlib
import shlex
import shutil
import sys


def source_bundle():
    from .platform_ui import DISPLAY_NAME
    root=Path(__file__).resolve().parent.parent
    contents=root/'build'/f'{DISPLAY_NAME}.app'/'Contents'
    binary=contents/'MacOS'/'hp48gx-python'
    if Path(sys.executable).absolute()==binary.absolute():return binary
    (contents/'MacOS').mkdir(parents=True,exist_ok=True)
    (contents/'Resources').mkdir(exist_ok=True)
    interpreter=Path(sys.executable).resolve()
    if not binary.exists() or interpreter.stat().st_mtime_ns!=binary.stat().st_mtime_ns:
        shutil.copy2(interpreter,binary)
    # The copied interpreter still uses this project's existing environment.
    config=Path(sys.prefix)/'pyvenv.cfg'
    if config.exists():shutil.copy2(config,contents/'pyvenv.cfg')
    else:
        (contents/'pyvenv.cfg').write_text(f'home = {interpreter.parent}\ninclude-system-site-packages = true\n')
    library=contents/'lib'
    if not library.exists():library.symlink_to(Path(sys.prefix)/'lib',target_is_directory=True)
    launcher=contents/'MacOS'/DISPLAY_NAME
    launcher.write_text('#!/bin/sh\ncd '+shlex.quote(str(root))+' || exit 1\nexec '+shlex.quote(str(binary))+' -m hp48g "$@"\n')
    launcher.chmod(0o755)
    shutil.copy2(root/'hp48g/assets/hp48gx-icon.icns',contents/'Resources'/'hp48gx.icns')
    info={'CFBundleName':DISPLAY_NAME,'CFBundleDisplayName':DISPLAY_NAME,
          'CFBundleIdentifier':'org.hp48g.desktop','CFBundleExecutable':DISPLAY_NAME,
          'CFBundlePackageType':'APPL','CFBundleIconFile':'hp48gx.icns',
          'CFBundleVersion':'1','CFBundleShortVersionString':'0.1.0','NSHighResolutionCapable':True}
    with (contents/'Info.plist').open('wb') as stream:plistlib.dump(info,stream)
    return binary


def relaunch_as_application():
    if sys.platform!='darwin' or getattr(sys,'frozen',False):return
    binary=source_bundle()
    if Path(sys.executable).absolute()==binary.absolute():return
    root=Path(__file__).resolve().parent.parent
    env=os.environ.copy();env['PYTHONPATH']=str(root)+os.pathsep+env.get('PYTHONPATH','')
    os.execve(str(binary),[str(binary),'-m','hp48g',*sys.argv[1:]],env)
