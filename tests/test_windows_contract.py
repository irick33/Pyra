"""Contract test for pywinpty calls; does not replace a real Windows smoke test."""

import sys
import types

from pyra.terminal import Reader


def test_windows_command_keeps_paths_with_spaces(app, tmp_path, monkeypatch):
    captured = {}

    class FakePty:
        pid = 123
        exitstatus = 0
        alive = True

        @classmethod
        def spawn(cls, argv, **kwargs):
            captured["argv"] = argv
            captured.update(kwargs)
            return cls()

        def read(self, _size):
            self.alive = False
            raise EOFError()

        def isalive(self):
            return self.alive

    monkeypatch.setitem(sys.modules, "winpty", types.SimpleNamespace(PtyProcess=FakePty))
    monkeypatch.setattr(sys, "platform", "win32")
    command = [r"C:\Program Files\Python\python.exe", "-u", r"C:\Мой проект\main.py", "a b"]
    reader = Reader(command, tmp_path, command[0])
    reader.run()
    assert captured["argv"] == command
    assert isinstance(captured["argv"], list)
    assert reader.exit_code == 0
