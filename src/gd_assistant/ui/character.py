"""Character tab — pick a save, see what's in it, and clone it (SPEC §14.1).

Read-only apart from one button: **Save As New Character…**, which never modifies the
character on screen. There is deliberately no "Save" — committing is always creating
(SPEC §5.3).

Records are resolved through the knowledge base so the view shows real names —
*Primal Strike (Shaman)* rather than `records/skills/playerclass06/savagestrike1.dbr`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gd_assistant.config.settings import Settings
from gd_assistant.data.repository import KnowledgeBase
from gd_assistant.models.character import Character
from gd_assistant.savefile import locator
from gd_assistant.savefile.parser import (
    GdcParseError,
    parse_character,
    read_header,
    slot_label,
)
from gd_assistant.ui.save_as_dialog import SaveAsNewCharacterDialog


class CharacterTab(QWidget):
    """Save-folder picker, character list, and a read-only view of the selection."""

    def __init__(self, settings: Settings, kb: KnowledgeBase | None = None) -> None:
        super().__init__()
        self._settings = settings
        self._kb = kb or KnowledgeBase()
        self._character: Character | None = None
        self._paths: list[Path] = []

        self._save_label = QLabel()
        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.clicked.connect(self._rescan)
        self._choose_btn = QPushButton("Choose folder…")
        self._choose_btn.clicked.connect(self._choose_folder)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self._save_label, 1)
        folder_row.addWidget(self._rescan_btn)
        folder_row.addWidget(self._choose_btn)

        self._picker = QComboBox()
        self._picker.currentIndexChanged.connect(lambda _i: self._show_selected())
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self._show_selected)
        self._save_as_btn = QPushButton("Save As New Character…")
        self._save_as_btn.setToolTip(
            "Create a new character from this one. The original is never modified."
        )
        self._save_as_btn.clicked.connect(self._save_as)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Character:"))
        picker_row.addWidget(self._picker, 1)
        picker_row.addWidget(self._reload_btn)
        picker_row.addWidget(self._save_as_btn)

        self._summary = QLabel()
        self._summary.setWordWrap(True)

        self._skills = self._make_table(("Skill", "Class", "Points"), stretch=0)
        self._devotions = self._make_table(("Constellation", "Affinities"), stretch=0)
        self._gear = self._make_table(("Slot", "Item", "Rarity", "Req"), stretch=1)

        self._details = QTabWidget()
        self._details.addTab(self._skills, "Skills")
        self._details.addTab(self._devotions, "Devotions")
        self._details.addTab(self._gear, "Gear")

        layout = QVBoxLayout(self)
        layout.addLayout(folder_row)
        layout.addLayout(picker_row)
        layout.addWidget(self._summary)
        layout.addWidget(self._details, 1)

        self._rescan()

    # -- save folder ------------------------------------------------------
    def save_dir(self) -> Path | None:
        if self._settings.save_dir:
            return Path(self._settings.save_dir)
        return locator.find_save_dir()

    def _rescan(self) -> None:
        save_dir = self.save_dir()
        if save_dir is None:
            self._save_label.setText("Save folder: not found — use Choose folder…")
            self._paths = []
        else:
            self._save_label.setText(f"Save folder: {save_dir}")
            self._paths = locator.list_characters(save_dir)
        self._repopulate()

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select your Grim Dawn save folder")
        if not chosen:
            return
        if not locator.is_save_dir(Path(chosen)):
            QMessageBox.warning(
                self, "Not a save folder",
                "That folder has no character sub-folders. Pick the Grim Dawn "
                "'save' folder (characters may sit under save/main).",
            )
            return
        self._settings.save_dir = chosen
        self._settings.save()
        self._rescan()

    def _picker_label(self, path: Path) -> str:
        """`Bale  L36  Warder (Soldier + Shaman)` — read from the header only.

        Reading just the header keeps building the list cheap; the full parse happens
        for the one character actually selected.
        """
        try:
            header = read_header(path / "player.gdc")
        except GdcParseError:
            return f"{path.name.lstrip('_')}  (unreadable)"
        label = f"{header.name}  L{header.level}"
        if header.hardcore:
            label += "  HC"
        klass = self._kb.class_description(header.class_tag) if self._kb.is_built() else ""
        return f"{label}  {klass}" if klass else label

    def _repopulate(self, select: Path | None = None) -> None:
        self._picker.blockSignals(True)
        self._picker.clear()
        for path in self._paths:
            self._picker.addItem(self._picker_label(path), userData=str(path))
        if select is not None:
            index = self._picker.findData(str(select))
            if index >= 0:
                self._picker.setCurrentIndex(index)
        self._picker.blockSignals(False)
        self._save_as_btn.setEnabled(bool(self._paths))
        self._show_selected()

    # -- selected character ----------------------------------------------
    def selected_path(self) -> Path | None:
        data = self._picker.currentData()
        return Path(data) if data else None

    def select_character(self, name: str) -> bool:
        """Select by character name, independent of how the row is labelled."""
        for index in range(self._picker.count()):
            path = Path(self._picker.itemData(index))
            if path.name.lstrip("_").casefold() == name.casefold():
                self._picker.setCurrentIndex(index)
                return True
        return False

    def _show_selected(self) -> None:
        path = self.selected_path()
        if path is None:
            self._character = None
            self._summary.setText("No character selected.")
            for table in (self._skills, self._devotions, self._gear):
                table.setRowCount(0)
            return
        try:
            self._character = parse_character(path / "player.gdc")
        except GdcParseError as exc:
            self._character = None
            self._summary.setText(f"Could not read this save: {exc}")
            for table in (self._skills, self._devotions, self._gear):
                table.setRowCount(0)
            return
        self._render(self._character)

    def _render(self, ch: Character) -> None:
        klass = self._kb.class_description(ch.class_tag) if self._kb.is_built() else ""
        masteries = " / ".join(
            f"{self._mastery_name(m)} {p}" for m, p in sorted(ch.masteries.items())
        )
        attrs = ch.attributes
        unspent = [
            f"{attrs.get(f'unspent_{k}', 0)} {label}"
            for k, label in (("attribute", "attribute"), ("skill", "skill"), ("devotion", "devotion"))
            if attrs.get(f"unspent_{k}")
        ]
        self._summary.setText(
            f"<b>{ch.name}</b> — level {ch.level}"
            + ("  (Hardcore)" if ch.hardcore else "")
            + (f" — {klass}" if klass else "")
            + (f"<br>Mastery bars: {masteries}" if masteries else "")
            + f"<br>Physique {attrs.get('physique', 0)}, "
            f"Cunning {attrs.get('cunning', 0)}, Spirit {attrs.get('spirit', 0)}"
            + (f"<br>Unspent: {', '.join(unspent)}" if unspent else "")
        )

        rows = []
        for allocation in sorted(ch.skills, key=lambda s: -s.points):
            record = self._kb.skill(allocation.skill_id) or {}
            name = self._kb.skill_name(allocation.skill_id) or record.get("name") or (
                allocation.skill_id.rsplit("/", 1)[-1].removesuffix(".dbr")
            )
            # The mastery bars are stored as skills too; label them so the two big
            # point sinks at the top of the list aren't mistaken for abilities.
            is_bar = "_classtraining_class" in allocation.skill_id
            klass = "Mastery bar" if is_bar else record.get("mastery", "")
            rows.append((name, klass, str(allocation.points)))
        self._fill(self._skills, rows)

        # Saves list individual stars; group them into the constellations they belong
        # to, which is how players actually think about devotion.
        taken: dict[str, int] = {}
        unknown = 0
        for node in ch.devotion:
            constellation = self._kb.constellation_for_star(node.node_id)
            if constellation is None:
                unknown += 1
                continue
            taken[constellation["name"]] = taken.get(constellation["name"], 0) + 1
        rows = []
        for name, count in sorted(taken.items()):
            constellation = next(d for d in self._kb.devotion if d["name"] == name)
            total = constellation.get("star_count") or 0
            affinities = constellation.get("affinity_given") or {}
            given = ", ".join(f"{k} {v}" for k, v in affinities.items())
            rows.append((f"{name}  ({count}/{total} stars)", given))
        if unknown:
            rows.append((f"{unknown} star(s) not in the knowledge base", ""))
        self._fill(self._devotions, rows)

        rows = []
        for equipped in ch.equipped:
            item = self._kb.item(equipped.item_id) or {}
            requirement = item.get("level_requirement")
            rows.append((
                slot_label(equipped.slot),
                item.get("name") or equipped.item_id.rsplit("/", 1)[-1].removesuffix(".dbr"),
                item.get("rarity") or "",
                str(requirement) if requirement else "",
            ))
        self._fill(self._gear, rows)

    def _mastery_name(self, mastery_id: str) -> str:
        """Resolve a two-digit mastery id to its name, falling back to the id."""
        if not self._kb.is_built():
            return mastery_id
        return self._kb.mastery_name(mastery_id) or mastery_id

    # -- cloning ----------------------------------------------------------
    def _save_as(self) -> None:
        path = self.selected_path()
        if path is None or self._character is None:
            return
        dialog = SaveAsNewCharacterDialog(path, self._character.name, parent=self)
        if dialog.exec() != SaveAsNewCharacterDialog.DialogCode.Accepted:
            return
        plan = dialog.result_plan
        QMessageBox.information(
            self, "Character created",
            f"Created “{plan.new_name}” at:\n{plan.destination}\n\n"
            f"“{plan.source_name}” was not modified.",
        )
        self._rescan()
        self._repopulate(select=plan.destination)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _make_table(columns: tuple[str, ...], *, stretch: int) -> QTableWidget:
        """A read-only table whose `stretch` column absorbs the spare width."""
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        for column in range(len(columns)):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column == stretch
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        return table

    @staticmethod
    def _fill(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(text))

    def reload(self, kb: KnowledgeBase | None = None) -> None:
        """(Re)load after a KB rebuild, so names resolve against the new data."""
        if kb is not None:
            self._kb = kb
        self._show_selected()
