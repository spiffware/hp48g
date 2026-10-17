from PySide6.QtCore import QLockFile, QStandardPaths
import pytest
from hp48g.data_paths import data_directory, migrate_data


def test_data_root_is_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(QStandardPaths,'writableLocation',lambda kind:str(tmp_path))
    assert data_directory()==tmp_path/'hp48gx'


def test_migration_preserves_state_and_never_overwrites(tmp_path):
    old=tmp_path/'old';new=tmp_path/'hp48gx'
    profile=old/'original-hp48';profile.mkdir(parents=True)
    (profile/'calculator.hp48state').write_bytes(b'RAM and card data')
    (old/'workspace.json').write_text('{}')
    migrate_data(old,new)
    assert (new/'original-hp48/calculator.hp48state').read_bytes()==b'RAM and card data'
    assert (new/'workspace.json').read_text()=='{}'
    assert not (new/'original-hp48/session.lock').exists()
    (new/'original-hp48/calculator.hp48state').write_bytes(b'new data')
    migrate_data(old,new)
    assert (new/'original-hp48/calculator.hp48state').read_bytes()==b'new data'
    assert (profile/'calculator.hp48state').read_bytes()==b'RAM and card data'


def test_migration_refuses_live_profile(tmp_path):
    old=tmp_path/'old';profile=old/'original-hp48';profile.mkdir(parents=True)
    lock=QLockFile(str(profile/'session.lock'));assert lock.tryLock(0)
    try:
        with pytest.raises(RuntimeError,match='Close the running calculator'):
            migrate_data(old,tmp_path/'hp48gx')
        assert not (tmp_path/'hp48gx').exists()
    finally:lock.unlock()
