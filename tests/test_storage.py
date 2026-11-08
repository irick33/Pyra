import os

import pytest

from pyra.services import valid_package
from pyra.storage import apply_refactor, atomic_write, project_files, read_source, save_source


def test_python_encoding_and_crlf_roundtrip(tmp_path):
    path = tmp_path / "пример.py"
    data = '# coding: cp1251\r\nprint("Привет")\r\n'.encode("cp1251")
    path.write_bytes(data)
    source = read_source(path)
    assert source.newline == "\r\n"
    assert "Привет" in source.text
    save_source(path, source.text, source.encoding, source.newline)
    assert path.read_bytes() == data


def test_atomic_write_preserves_permissions(tmp_path):
    path = tmp_path / "script.py"
    path.write_bytes(b"old")
    path.chmod(0o755)
    atomic_write(path, b"new")
    assert path.read_bytes() == b"new"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o755


def test_binary_rejected(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"\x00\x01")
    with pytest.raises(ValueError):
        read_source(path)


def test_scan_excludes_environment_and_symlinks(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignore.py").write_text("x=1")
    if os.name != "nt":
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    assert [p.name for p in project_files(tmp_path)] == ["main.py"]


def test_refactor_conflict_prevents_all_writes(tmp_path):
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("old = 1\n")
    second.write_text("changed = 2\n")
    with pytest.raises(ValueError):
        apply_refactor(
            [
                {"path": str(first), "before": "old = 1\n", "after": "new = 1\n"},
                {"path": str(second), "before": "old = 2\n", "after": "new = 2\n"},
            ]
        )
    assert first.read_text() == "old = 1\n"


def test_refactor_transaction_rolls_back_on_second_write(tmp_path, monkeypatch):
    import pyra.storage as storage

    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("a=1\n")
    second.write_text("a=2\n")
    actual_save = storage.save_source

    def fail_second(path, *args):
        if path == second:
            raise OSError("simulated disk failure")
        actual_save(path, *args)

    monkeypatch.setattr(storage, "save_source", fail_second)
    with pytest.raises(OSError):
        apply_refactor(
            [
                {"path": str(first), "before": "a=1\n", "after": "b=1\n"},
                {"path": str(second), "before": "a=2\n", "after": "b=2\n"},
            ]
        )
    assert first.read_text() == "a=1\n"
    assert second.read_text() == "a=2\n"


@pytest.mark.parametrize(
    "value", ["requests", "numpy>=1.26,<3", "fastapi[standard]", "pandas==2.2.3"]
)
def test_package_specs(value):
    assert valid_package(value)


@pytest.mark.parametrize(
    "value", ["--target=/tmp", "requests; echo bad", "a && b", "", "-r file.txt"]
)
def test_no_pip_flags_or_shell_commands(value):
    assert not valid_package(value)
