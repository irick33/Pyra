import codecs
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal


def ruff_command():
    """Use the native binary directly, avoiding an extra Python startup per check."""
    executable = Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff")
    if executable.is_file():
        return str(executable), []
    return sys.executable, ["-m", "ruff"]


def process_environment(interpreter=None):
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")
    if interpreter:
        folder = Path(interpreter).parent
        env.insert("PATH", str(folder) + os.pathsep + env.value("PATH"))
        if folder.name.lower() in {"scripts", "bin"} and (folder.parent / "pyvenv.cfg").exists():
            env.insert("VIRTUAL_ENV", str(folder.parent))
        else:
            env.remove("VIRTUAL_ENV")
    return env


class Job(QObject):
    output = pyqtSignal(str)
    done = pyqtSignal(int, str)
    running = pyqtSignal(bool)

    def __init__(self, parent=None, merged=True):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
            if merged
            else QProcess.ProcessChannelMode.SeparateChannels
        )
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._read_error)
        self.process.started.connect(self._send_stdin)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.buffer = bytearray()
        self.error_buffer = bytearray()
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.error_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._stdin = None
        self.active = False

    @property
    def error_text(self):
        return self.error_buffer.decode("utf-8", errors="replace")

    def start(self, program, args, cwd=None, stdin=None):
        if self.active:
            return False
        self.buffer.clear()
        self.error_buffer.clear()
        self.decoder.reset()
        self.error_decoder.reset()
        self._stdin = stdin.encode("utf-8") if stdin is not None else None
        self.active = True
        self.running.emit(True)
        self.process.setProcessEnvironment(process_environment(program))
        self.process.setWorkingDirectory(str(cwd or Path.cwd()))
        self.process.start(str(program), [str(a) for a in args])
        return True

    def _send_stdin(self):
        if self._stdin is not None:
            self.process.write(self._stdin)
            self.process.closeWriteChannel()

    def _read(self):
        data = bytes(self.process.readAllStandardOutput())
        self.buffer.extend(data)
        if len(self.buffer) > 4 * 1024 * 1024:
            del self.buffer[: -2 * 1024 * 1024]
        self.output.emit(self.decoder.decode(data))

    def _read_error(self):
        data = bytes(self.process.readAllStandardError())
        self.error_buffer.extend(data)
        if len(self.error_buffer) > 4 * 1024 * 1024:
            del self.error_buffer[: -2 * 1024 * 1024]
        self.output.emit(self.error_decoder.decode(data))

    def _finished(self, code, _status=None):
        if not self.active:
            return
        self._read()
        self._read_error()
        self.active = False
        self.running.emit(False)
        self.done.emit(code, self.buffer.decode("utf-8", errors="replace"))

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.buffer.extend(self.process.errorString().encode())
            self._finished(-1)

    def stop(self):
        if self.active:
            self.process.kill()

    def close(self):
        self.stop()
        self.process.waitForFinished(1500)


class Intelligence(QObject):
    result = pyqtSignal(dict, object)
    failure = pyqtSignal(dict, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(process_environment())
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.errorOccurred.connect(self._failed)
        self.process.finished.connect(self._exited)
        self.buffer = bytearray()
        self.sequence = 0
        self.current = None
        self.pending = OrderedDict()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.closing = False

    def request(self, **payload):
        self.sequence += 1
        payload["id"] = self.sequence
        key = (payload.get("token"), payload["operation"])
        self.pending[key] = payload
        self.pending.move_to_end(key)
        while len(self.pending) > 16:
            self.pending.popitem(last=False)
        self._next()

    def _next(self):
        if self.current or not self.pending or self.closing:
            return
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.process.start(sys.executable, ["-m", "pyra.worker"])
        _, self.current = self.pending.popitem(last=False)
        self.process.write((json.dumps(self.current) + "\n").encode("utf-8"))
        self.timer.start(15000)

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b"\n" in self.buffer:
            line, _, self.buffer = self.buffer.partition(b"\n")
            try:
                response = json.loads(line)
            except ValueError:
                continue
            request = self.current
            if request and response.get("id") == request["id"]:
                self.timer.stop()
                self.current = None
                if "error" in response:
                    self.failure.emit(request, response["error"])
                else:
                    self.result.emit(request, response["result"])
                self._next()

    def _timeout(self):
        if self.current:
            self.failure.emit(self.current, "Анализ превысил 15 секунд; процесс перезапущен")
        self.current = None
        self.process.kill()

    def _failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._exited()

    def _exited(self, *_):
        self.timer.stop()
        self.buffer.clear()
        if self.current:
            self.failure.emit(self.current, "Процесс анализа завершился")
            self.current = None
        if not self.closing:
            QTimer.singleShot(100, self._next)

    def close(self):
        self.closing = True
        self.timer.stop()
        self.pending.clear()
        self.process.kill()
        self.process.waitForFinished(1500)


PACKAGE_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:(?:==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!-]+"
    r"(?:,(?:==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!-]+)*)?"
)


def valid_package(value):
    return bool(PACKAGE_PATTERN.fullmatch(value.strip()))


def split_arguments(value):
    """shlex follows POSIX quoting even on Windows; document double-slash Windows paths."""
    import shlex

    return shlex.split(value, posix=True)


def stop_process_tree(pid):
    if sys.platform == "win32":
        subprocess.Popen(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        import signal

        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
