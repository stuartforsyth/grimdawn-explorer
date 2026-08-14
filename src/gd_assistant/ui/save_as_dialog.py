"""“Save As New Character…” — the only place in the UI that writes save data.

The dialog is built around showing the user exactly what will happen *before* it
happens: which folder is about to be created, whether any save bytes get written at
all, and anything currently blocking the write. Nothing is created until Create is
pressed, and the source character is never modified (SPEC §5.3, §14.1).

`resolve_plan` holds the validation logic as a plain function so the rules can be
tested without a display.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from gd_assistant.savefile.clone import (
    CloneError,
    ClonePlan,
    clone_character,
    find_running_game,
    plan_clone,
)

MODE_RENAME = "rename"
MODE_FOLDER = "folder"


@dataclass(frozen=True)
class PlanPreview:
    """The outcome of validating what the user has typed so far."""

    plan: ClonePlan | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.plan is not None


def resolve_plan(source: Path, mode: str, text: str, save_dir: Path | None = None) -> PlanPreview:
    """Validate the dialog's inputs, returning either a plan or why there isn't one."""
    if not text.strip():
        label = "character name" if mode == MODE_RENAME else "folder name"
        return PlanPreview(None, f"Enter a {label}.")
    try:
        plan = plan_clone(
            source,
            new_name=text if mode == MODE_RENAME else None,
            folder_name=text if mode == MODE_FOLDER else None,
            save_dir=save_dir,
        )
    except CloneError as exc:
        return PlanPreview(None, str(exc))

    if plan.destination.exists():
        return PlanPreview(None, f"“{plan.destination.name}” already exists — pick another name.")
    return PlanPreview(plan)


class SaveAsNewCharacterDialog(QDialog):
    """Collects a name, previews the clone, and performs it on accept."""

    def __init__(self, source: Path, character_label: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save As New Character")
        self.setMinimumWidth(560)
        self._source = source
        self.result_plan: ClonePlan | None = None

        intro = QLabel(
            f"Cloning <b>{character_label}</b> into a new character.<br>"
            "Your existing save is opened read-only and is never modified."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)

        self._rename_radio = QRadioButton("Rename the character")
        self._rename_radio.setToolTip(
            "Creates a new folder and rewrites the name stored inside player.gdc."
        )
        self._folder_radio = QRadioButton("Keep the name, use a different folder")
        self._folder_radio.setToolTip(
            "Copies the character as-is. No save data is rewritten at all — the "
            "player.gdc is duplicated byte for byte."
        )
        self._rename_radio.setChecked(True)
        self._rename_radio.toggled.connect(self._on_mode_changed)

        self._name = QLineEdit()
        self._name.setClearButtonEnabled(True)
        self._name.textChanged.connect(lambda _t: self._revalidate())

        form = QFormLayout()
        form.addRow("New name:", self._name)

        self._destination = QLabel()
        self._destination.setWordWrap(True)
        self._effect = QLabel()
        self._effect.setWordWrap(True)
        self._problem = QLabel()
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet("color: palette(link-visited);")

        self._recheck = QPushButton("Check again")
        self._recheck.clicked.connect(self._revalidate)
        self._recheck.setVisible(False)
        recheck_row = QHBoxLayout()
        recheck_row.addWidget(self._problem, 1)
        recheck_row.addWidget(self._recheck)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self._create = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._create.setText("Create")
        self._buttons.accepted.connect(self._on_create)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self._rename_radio)
        layout.addWidget(self._folder_radio)
        layout.addLayout(form)
        layout.addWidget(self._destination)
        layout.addWidget(self._effect)
        layout.addLayout(recheck_row)
        layout.addStretch(1)
        layout.addWidget(self._buttons)

        self._name.setText(f"{character_label} copy")
        self._name.selectAll()
        self._revalidate()

    @property
    def mode(self) -> str:
        return MODE_RENAME if self._rename_radio.isChecked() else MODE_FOLDER

    def _on_mode_changed(self) -> None:
        renaming = self.mode == MODE_RENAME
        self._name.setToolTip(
            "The new character's name, used for both the folder and the save file."
            if renaming
            else "Only the folder name changes; the character keeps its current name."
        )
        self._revalidate()

    def _revalidate(self) -> PlanPreview:
        preview = resolve_plan(self._source, self.mode, self._name.text())
        blocker = find_running_game()

        if preview.plan is not None:
            self._destination.setText(f"Will create:  {preview.plan.destination}")
            self._effect.setText(
                "The character name inside the save will be rewritten."
                if preview.plan.rename_in_file
                else "No save data is rewritten — player.gdc is copied byte for byte."
            )
        else:
            self._destination.setText("")
            self._effect.setText("")

        if blocker:
            self._problem.setText(
                f"{blocker} is running. Close Grim Dawn first — it rewrites its saves "
                "on exit and would discard the new character."
            )
            self._recheck.setVisible(True)
        else:
            self._problem.setText(preview.error or "")
            self._recheck.setVisible(False)

        self._create.setEnabled(preview.ok and blocker is None)
        return preview

    def _on_create(self) -> None:
        preview = self._revalidate()
        if not preview.ok or preview.plan is None:
            return
        # The copy is a handful of small files, so this is fast enough to run inline;
        # nothing lands in the save folder unless it verifies (SPEC §5.3).
        try:
            clone_character(preview.plan)
        except CloneError as exc:
            self._problem.setText(str(exc))
            self._recheck.setVisible(True)
            self._create.setEnabled(False)
            return
        self.result_plan = preview.plan
        self.accept()
