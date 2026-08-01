"""Application entry point.

Wires together configuration and the UI. Kept intentionally thin so the pieces
(config, save parsing, knowledge base, suggestions) can be developed and tested
independently of the GUI.
"""

from __future__ import annotations

import sys

from gd_assistant.config.settings import Settings


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop app. Returns a process exit code."""
    argv = argv if argv is not None else sys.argv[1:]

    settings = Settings.load()

    try:
        from PySide6.QtWidgets import QApplication

        from gd_assistant.ui.main_window import MainWindow
    except ImportError:
        # GUI deps not installed yet — fail helpfully rather than crashing.
        print(
            "PySide6 is not installed. Install dev dependencies with:\n"
            '    pip install -e ".[dev]"\n'
            f"(config loaded OK; save dir = {settings.save_dir or 'not set'})",
            file=sys.stderr,
        )
        return 1

    qt_app = QApplication(sys.argv)
    window = MainWindow(settings)
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
