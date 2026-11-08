"""Disk operations live here; opening a project never executes its code."""

import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path

IGNORED = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".ide-venv",
    "venv",
    "env",
    "__pycache__",
    ".pyra",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "build",
    "dist",
}
MAX_SOURCE = 1024 * 1024


@dataclass
class SourceFile:
    text: str
    encoding: str
    newline: str


def read_source(path: Path) -> SourceFile:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError("Это двоичный файл. Откройте текстовый файл.")
    if path.suffix in {".py", ".pyw", ".pyi"}:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    else:
        encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    text = raw.decode(encoding)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return SourceFile(text.replace("\r\n", "\n").replace("\r", "\n"), encoding, newline)


def atomic_write(path: Path, data: bytes) -> None:
    """Same-directory replace keeps the previous version intact on write failure."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_source(path: Path, text: str, encoding: str, newline: str) -> None:
    atomic_write(path, text.replace("\n", newline).encode(encoding))


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def save_json(path: Path, value) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def env_python(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def interpreter_version_hint(interpreter):
    """Read a venv's version without spawning Python during GUI startup."""
    path = Path(interpreter)
    try:
        for line in (path.parent.parent / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "version":
                return [int(part) for part in value.strip().split(".")[:3]]
    except (OSError, ValueError):
        pass
    if str(path) in {sys.executable, getattr(sys, "_base_executable", sys.executable)}:
        return list(sys.version_info[:3])
    return None


def project_files(root: Path, suffixes=None, limit=20000):
    """Bounded traversal; no symlink loops or environment indexing."""
    count = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(
            d for d in folders if d not in IGNORED and not Path(directory, d).is_symlink()
        )
        for name in sorted(files):
            path = Path(directory, name)
            if path.is_symlink() or (suffixes and path.suffix not in suffixes):
                continue
            count += 1
            if count > limit:
                return
            yield path


def recovery_name(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest() + ".json"


def apply_refactor(changes: list[dict]) -> None:
    """Validate every original first; roll back already replaced files on failure."""
    originals = {}
    for change in changes:
        path = Path(change["path"])
        source = read_source(path)
        if source.text != change["before"]:
            raise ValueError(f"Файл изменился после предпросмотра: {path}")
        originals[path] = (path.read_bytes(), source)
    applied = []
    try:
        for change in changes:
            path = Path(change["path"])
            source = originals[path][1]
            save_source(path, change["after"], source.encoding, source.newline)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            atomic_write(path, originals[path][0])
        raise
