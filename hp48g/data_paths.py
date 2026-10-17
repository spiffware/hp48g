"""Per-user data location, independent of the app's visible name."""
from pathlib import Path
import shutil
import tempfile
from PySide6.QtCore import QStandardPaths, QLockFile


def data_directory():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation))/'hp48gx'


def legacy_directory():
    # Retain the old Qt application name solely to locate existing installations.
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


def migrate_data(source=None, destination=None):
    """Copy a closed legacy installation once; never overwrite newer saved data."""
    source=Path(source) if source is not None else legacy_directory()
    destination=Path(destination) if destination is not None else data_directory()
    if destination.exists() or not source.exists() or source==destination:return
    profile=source/'original-hp48'
    lock=QLockFile(str(profile/'session.lock')) if profile.exists() else None
    if lock is not None and not lock.tryLock(0):
        raise RuntimeError('Close the running calculator before migrating its saved data to hp48gx.')
    temporary=None
    try:
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=Path(tempfile.mkdtemp(prefix='.hp48gx-migration-',dir=destination.parent))
        shutil.copytree(source,temporary,dirs_exist_ok=True,ignore=shutil.ignore_patterns('session.lock'))
        temporary.rename(destination)
        temporary=None
    finally:
        if temporary is not None:shutil.rmtree(temporary)
        if lock is not None:lock.unlock()
