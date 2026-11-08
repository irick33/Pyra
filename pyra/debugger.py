"""Small asynchronous DAP client. debugpy supplies the actual Python debugger."""

import json
import sys

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from .services import process_environment


class DAPClient(QObject):
    terminalRequested = pyqtSignal(int, dict)
    stopped = pyqtSignal(list)
    scopes = pyqtSignal(list)
    variables = pyqtSignal(int, list)
    output = pyqtSignal(str)
    state = pyqtSignal(str)
    finished = pyqtSignal()
    evaluated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(process_environment())
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.sequence = 0
        self.callbacks = {}
        self.buffer = bytearray()
        self.active = False
        self.thread_id = None
        self.frame_id = None
        self.breakpoints = {}
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._timed_out)

    def launch(self, program, interpreter, cwd, args=None, breakpoints=None, integrated=False):
        if self.active:
            return False
        self.buffer.clear()
        self.callbacks.clear()
        self.active = True
        self.breakpoints = breakpoints or {}
        self.configuration = {
            "name": "Pyra",
            "type": "python",
            "request": "launch",
            "program": str(program),
            "python": str(interpreter),
            "cwd": str(cwd),
            "args": args or [],
            "console": "integratedTerminal" if integrated else "internalConsole",
            "redirectOutput": True,
            "justMyCode": True,
            "subProcess": False,
            "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        }
        self.process.started.connect(self._initialize)
        self.process.start(sys.executable, ["-m", "debugpy.adapter"])
        self.state.emit("Запуск отладчика…")
        self.timeout.start(20000)
        return True

    def _initialize(self):
        self.process.started.disconnect(self._initialize)
        self.request(
            "initialize",
            {
                "clientID": "pyra",
                "adapterID": "python",
                "pathFormat": "path",
                "linesStartAt1": True,
                "columnsStartAt1": True,
                "supportsVariableType": True,
                "supportsRunInTerminalRequest": True,
            },
            lambda _: self.request("launch", self.configuration),
        )

    def request(self, command, arguments=None, callback=None):
        self.sequence += 1
        if callback:
            self.callbacks[self.sequence] = callback
        payload = json.dumps(
            {
                "seq": self.sequence,
                "type": "request",
                "command": command,
                "arguments": arguments or {},
            }
        ).encode("utf-8")
        self.process.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b"\r\n\r\n" in self.buffer:
            header, _, rest = self.buffer.partition(b"\r\n\r\n")
            length = next(
                (
                    int(line.split(b":", 1)[1])
                    for line in header.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ),
                0,
            )
            if len(rest) < length:
                return
            self.buffer = rest[length:]
            try:
                self._message(json.loads(rest[:length]))
            except (ValueError, KeyError) as error:
                self.output.emit(f"Ошибка протокола отладки: {error}\n")

    def _message(self, message):
        if message["type"] == "request" and message.get("command") == "runInTerminal":
            self.terminalRequested.emit(message["seq"], message.get("arguments", {}))
            return
        if message["type"] == "response":
            callback = self.callbacks.pop(message.get("request_seq"), None)
            if not message.get("success", True):
                self.output.emit(message.get("message", "Ошибка отладчика") + "\n")
                if message.get("command") in {"initialize", "launch"}:
                    self.stop()
            elif callback:
                callback(message.get("body", {}))
            return
        if message["type"] != "event":
            return
        event, body = message["event"], message.get("body", {})
        if event == "initialized":
            self._configure_breakpoints()
        elif event == "stopped":
            self.timeout.stop()
            self.thread_id = body.get("threadId", 1)
            self.state.emit("Пауза · " + body.get("reason", "breakpoint"))
            self.request("stackTrace", {"threadId": self.thread_id}, self._stack)
        elif event == "continued":
            self.state.emit("Выполняется")
        elif event == "output":
            self.output.emit(body.get("output", ""))
        elif event == "process":
            self.timeout.stop()
            self.state.emit("Выполняется")
        elif event == "terminated":
            self.request("disconnect", {"terminateDebuggee": True})
            QTimer.singleShot(800, self._kill_if_active)

    def terminal_response(self, request_seq, pid=None, error=None):
        self.sequence += 1
        message = {
            "seq": self.sequence,
            "type": "response",
            "request_seq": request_seq,
            "command": "runInTerminal",
            "success": error is None,
            "body": {"processId": pid, "shellProcessId": pid} if pid else {},
        }
        if error:
            message["message"] = error
        payload = json.dumps(message).encode("utf-8")
        self.process.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)

    def _configure_breakpoints(self):
        entries = list(self.breakpoints.items())

        def configure_next(_=None):
            if entries:
                path, lines = entries.pop(0)
                self.request(
                    "setBreakpoints",
                    {"source": {"path": path}, "breakpoints": [{"line": n} for n in lines]},
                    configure_next,
                )
            else:
                self.request("configurationDone")

        configure_next()

    def update_breakpoints(self, path, lines):
        self.breakpoints[str(path)] = lines
        if self.active:
            self.request(
                "setBreakpoints",
                {"source": {"path": str(path)}, "breakpoints": [{"line": n} for n in lines]},
            )

    def _stack(self, body):
        frames = body.get("stackFrames", [])
        self.stopped.emit(frames)
        if frames:
            self.select_frame(frames[0]["id"])

    def select_frame(self, frame):
        self.frame_id = frame
        self.request(
            "scopes", {"frameId": frame}, lambda body: self.scopes.emit(body.get("scopes", []))
        )

    def fetch_variables(self, reference):
        self.request(
            "variables",
            {"variablesReference": reference},
            lambda body: self.variables.emit(reference, body.get("variables", [])),
        )

    def action(self, command):
        if not self.active:
            return
        if command == "pause":
            self.request(
                "threads",
                callback=lambda b: self.request(
                    "pause", {"threadId": b.get("threads", [{}])[0].get("id", 1)}
                ),
            )
        elif self.thread_id:
            self.request(command, {"threadId": self.thread_id})

    def evaluate(self, expression):
        if self.frame_id is not None:
            self.request(
                "evaluate",
                {"expression": expression, "frameId": self.frame_id, "context": "repl"},
                lambda b: self.evaluated.emit(b.get("result", "")),
            )

    def _stderr(self):
        self.output.emit(bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))

    def _finished(self, *_):
        was_active = self.active
        self.active = False
        self.timeout.stop()
        self.callbacks.clear()
        self.thread_id = self.frame_id = None
        self.state.emit("Отладка завершена")
        if was_active:
            self.finished.emit()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.output.emit(self.process.errorString())
            self._finished()

    def _timed_out(self):
        self.output.emit("Отладчик не запустился за 20 секунд\n")
        self.stop()

    def _kill_if_active(self):
        if self.active:
            self.process.kill()

    def stop(self):
        if self.active:
            self.request("disconnect", {"terminateDebuggee": True})
            QTimer.singleShot(1200, self._kill_if_active)

    def close(self):
        self.stop()
        if self.active and not self.process.waitForFinished(1800):
            self.process.kill()
            self.process.waitForFinished(1000)
