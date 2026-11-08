"""Source and packaged entry point. Self-test never touches the user's session."""
import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--startup-probe"]:
        from pyra.selftest import startup_probe
        raise SystemExit(startup_probe(sys.argv[2]))
    if sys.argv[1:2] == ["--self-test"]:
        from pyra.selftest import main
        raise SystemExit(main(sys.argv[2:]))
    try:
        from pyra.app import main
        raise SystemExit(main())
    except Exception:
        import logging
        from pyra.diagnostics import setup_logging, fallback_data_dir
        if not logging.getLogger("pyra").handlers:
            setup_logging(fallback_data_dir())
        logging.getLogger("pyra").exception("Startup failed")
        if sys.stderr is not None:
            import traceback
            traceback.print_exc()
        else:
            # --windowed has no stderr. Show a concrete path even on import failure.
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,
                    f"Pyra не удалось запустить. Подробности:\n{fallback_data_dir() / 'logs/pyra.log'}",
                    "Ошибка запуска Pyra", 0x10)
            except Exception:
                pass
        raise SystemExit(1)
