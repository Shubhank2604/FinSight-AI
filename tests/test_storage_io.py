import pytest

from storage_io import atomic_replace


def windows_lock():
    error = PermissionError('Windows file is temporarily locked')
    error.winerror = 5
    return error


def test_atomic_replace_recovers_from_temporary_windows_lock(tmp_path, monkeypatch):
    import storage_io
    source, target = tmp_path / 'new.json', tmp_path / 'old.json'
    source.write_text('new'); target.write_text('old')
    replace, attempts, delays = storage_io.os.replace, [], []
    def locked(a, b):
        attempts.append(1)
        if len(attempts) <= 2:
            assert target.read_text() == 'old'
            raise windows_lock()
        replace(a, b)
    monkeypatch.setattr(storage_io.os, 'replace', locked)
    monkeypatch.setattr(storage_io.time, 'sleep', delays.append)
    atomic_replace(source, target)
    assert target.read_text() == 'new' and not source.exists()
    assert delays == [.05, .1]


def test_permanent_windows_lock_keeps_original_and_pending_files(tmp_path, monkeypatch):
    import storage_io
    source, target = tmp_path / 'new.json', tmp_path / 'old.json'
    source.write_text('new'); target.write_text('old')
    delays = []
    def locked(*args):
        raise windows_lock()
    monkeypatch.setattr(storage_io.os, 'replace', locked)
    monkeypatch.setattr(storage_io.time, 'sleep', delays.append)
    with pytest.raises(PermissionError):
        atomic_replace(source, target)
    assert target.read_text() == 'old' and source.read_text() == 'new'
    assert len(delays) == 4


def test_other_permission_errors_are_not_retried(monkeypatch):
    import storage_io
    def forbidden(*args):
        raise PermissionError('No write permission')
    monkeypatch.setattr(storage_io.os, 'replace', forbidden)
    monkeypatch.setattr(storage_io.time, 'sleep', lambda _: pytest.fail('Must not retry'))
    with pytest.raises(PermissionError):
        atomic_replace('source', 'target')
