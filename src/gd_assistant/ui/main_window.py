"""Main application window (PySide6).

MVP shell. Two things are wired for real here:
  * showing the save-folder + knowledge-base status, and
  * an **"Update game data"** button that re-runs the native datamine to rebuild the
    JSON knowledge base — so the user can refresh content after a patch/DLC without
    leaving the app (SPEC §6.3, requested feature). The build runs on a worker
    thread so the UI stays responsive.

Character view, suggestions, and feedback controls land in later milestones.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gd_assistant.config.settings import Settings
from gd_assistant.data import updater
from gd_assistant.data.repository import KB_DIR, KnowledgeBase
from gd_assistant.knowledge import extractor
from gd_assistant.savefile import locator
from gd_assistant.ui.character import CharacterTab
from gd_assistant.ui.item_search import ItemSearchTab
from gd_assistant.ui.skill_search import SkillDevotionSearchTab


class _KbBuildWorker(QThread):
    """Runs the native datamine + KB build off the UI thread."""

    succeeded = Signal(dict)   # {category: count}
    failed = Signal(str)

    def __init__(self, install_dir: Path, out_dir: Path) -> None:
        super().__init__()
        self._install_dir = install_dir
        self._out_dir = out_dir

    def run(self) -> None:
        try:
            counts = updater.build_kb(self._install_dir, self._out_dir)
            self.succeeded.emit(counts)
        except Exception as exc:  # noqa: BLE001 - worker must report any failure to the UI, not crash
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._worker: _KbBuildWorker | None = None
        self.setWindowTitle("Grim Dawn Build Assistant")
        self.resize(900, 600)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        self._character_tab = CharacterTab(settings=settings)
        tabs.addTab(self._character_tab, "Character")
        self._item_tab = ItemSearchTab(settings=settings)
        tabs.addTab(self._item_tab, "Item Search")
        self._skill_tab = SkillDevotionSearchTab()
        tabs.addTab(self._skill_tab, "Skills & Devotions")
        self.setCentralWidget(tabs)

    def _build_overview_tab(self) -> QWidget:
        save_dir = self.settings.save_dir or (
            str(found) if (found := locator.find_save_dir()) else None
        )

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Grim Dawn Build Assistant — v0.1"))
        self._save_label = QLabel(
            f"Save folder: {save_dir}" if save_dir
            else "Save folder: not found — use Choose folder…"
        )
        layout.addWidget(self._save_label)

        self._kb_label = QLabel(self._kb_status_text())
        layout.addWidget(self._kb_label)

        # --- Update game data (rebuild knowledge base) ---
        self._update_btn = QPushButton("Update game data (rebuild knowledge base)")
        self._update_btn.clicked.connect(self._on_update_clicked)
        layout.addWidget(self._update_btn)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        layout.addWidget(QLabel(
            "Character view, suggestions, and feedback land in the MVP milestones (SPEC §10)."
        ))
        layout.addStretch(1)
        return tab

    # -- knowledge base ---------------------------------------------------
    def _kb_status_text(self) -> str:
        kb = KnowledgeBase()
        if not kb.is_built():
            return "Knowledge base: not built — click ‘Update game data’."
        meta = kb.meta()
        return (
            f"Knowledge base: {len(kb.masteries)} masteries, {len(kb.skills)} skills, "
            f"{len(kb.items)} items (built {meta.get('built_at', '?')})"
        )

    def _on_update_clicked(self) -> None:
        install_dir = self._resolve_install_dir()
        if install_dir is None:
            return  # user cancelled the folder picker

        self._update_btn.setEnabled(False)
        self._status_label.setText("Rebuilding knowledge base from game files… this can take a while.")

        self._worker = _KbBuildWorker(install_dir, KB_DIR)
        self._worker.succeeded.connect(self._on_build_ok)
        self._worker.failed.connect(self._on_build_failed)
        self._worker.start()

    def _resolve_install_dir(self) -> Path | None:
        """Return a valid install dir, prompting for one (and saving it) if needed."""
        saved = self.settings.game_install_dir
        if saved and extractor.looks_like_install(Path(saved)):
            return Path(saved)

        chosen = QFileDialog.getExistingDirectory(self, "Select your Grim Dawn install folder")
        if not chosen:
            return None
        if not extractor.looks_like_install(Path(chosen)):
            QMessageBox.warning(
                self, "Not a Grim Dawn install",
                "That folder has no database/database.arz. Pick the game's root folder.",
            )
            return None
        self.settings.game_install_dir = chosen
        self.settings.save()
        return Path(chosen)

    def _on_build_ok(self, counts: dict) -> None:
        self._status_label.setText(
            "Knowledge base updated: " + ", ".join(f"{k} {v}" for k, v in counts.items())
        )
        self._kb_label.setText(self._kb_status_text())
        self._item_tab.reload(KnowledgeBase())  # fresh KB -> drop cached data
        self._skill_tab.reload(KnowledgeBase())
        self._character_tab.reload(KnowledgeBase())
        self._update_btn.setEnabled(True)
        self._worker = None

    def _on_build_failed(self, message: str) -> None:
        self._status_label.setText(f"Update failed: {message}")
        QMessageBox.critical(self, "Update failed", message)
        self._update_btn.setEnabled(True)
        self._worker = None
