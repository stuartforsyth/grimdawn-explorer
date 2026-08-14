"""Skill & Devotion Search tab: one search box over skills *and* constellations.

Answers "what should I invest in to boost <X>?" — search by damage type ("cold
damage"), capability ("defensive"), or free text, and narrow by **one or more**
classes (masteries) and/or devotion affinities. Use case: specced into Nightblade +
Berserker, tick both, type "cold" → cold synergies across both classes plus any cold
constellations. Skills and devotions share a results table (a *Kind* column separates
them) and a detail panel. All data is local KB (see `data.normalise` for the devotion
damage/role tags this searches over).
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gd_assistant.data.repository import KnowledgeBase


class _StayOpenMenu(QMenu):
    """A QMenu that toggles a checkable action without closing — for multi-select."""

    def mouseReleaseEvent(self, event) -> None:  # Qt override
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()  # flips the check, keeps the menu open
            return
        super().mouseReleaseEvent(event)


class _MultiSelectButton(QToolButton):
    """Dropdown of checkable options; `changed` fires on any toggle. `selected()` set."""

    changed = Signal()

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label
        self.setText(label)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = _StayOpenMenu(self)
        self.setMenu(self._menu)

    def set_options(self, options: list[str]) -> None:
        selected = self.selected()  # preserve ticks across a KB reload
        self._menu.clear()
        for opt in options:
            action = self._menu.addAction(opt)
            action.setCheckable(True)
            action.setChecked(opt in selected)
            action.toggled.connect(self._on_toggled)
        self._update_text()

    def selected(self) -> set[str]:
        return {a.text() for a in self._menu.actions() if a.isChecked()}

    def _on_toggled(self, _checked: bool) -> None:
        self._update_text()
        self.changed.emit()

    def _update_text(self) -> None:
        n = len(self.selected())
        self.setText(f"{self._label} ({n})" if n else self._label)


class SkillDevotionSearchTab(QWidget):
    _COLUMNS = ("Name", "Kind", "Class / Affinity", "Damage", "Roles / Type")

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        super().__init__()
        self._kb = kb or KnowledgeBase()

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search skills & devotions — e.g. 'cold damage', 'defensive', 'retaliation'"
        )
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip(
            "Terms match anywhere and are combined with AND; wrap words in \"quotes\" for "
            "an exact phrase.\nSearch damage types (cold, aether) or capabilities "
            "(defensive, sustain, retaliation).\nUse the Class / Affinity filters to span "
            "several masteries or affinities at once (OR within each filter)."
        )
        self._search.textChanged.connect(lambda _t: self._refresh())

        self._kind = QComboBox()
        self._kind.addItems(["All", "Skills", "Devotions"])
        self._kind.currentIndexChanged.connect(lambda _i: self._refresh())

        self._class_filter = _MultiSelectButton("Class")
        self._class_filter.setToolTip("Show skills from these masteries (tick several to span classes)")
        self._class_filter.changed.connect(self._refresh)
        self._affinity_filter = _MultiSelectButton("Affinity")
        self._affinity_filter.setToolTip("Show devotions requiring/granting these affinities")
        self._affinity_filter.changed.connect(self._refresh)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self._search, 1)
        controls.addWidget(self._kind)
        controls.addWidget(self._class_filter)
        controls.addWidget(self._affinity_filter)

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._show_selected)

        self._detail = QTextBrowser()
        self._status = QLabel()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(controls)
        left_layout.addWidget(self._table)
        left_layout.addWidget(self._status)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.reload()

    def reload(self, kb: KnowledgeBase | None = None) -> None:
        """(Re)load after a KB rebuild — pass a fresh KnowledgeBase to drop caches."""
        if kb is not None:
            self._kb = kb
        if self._kb.is_built():
            self._class_filter.set_options(self._kb.mastery_names())
            self._affinity_filter.set_options(self._kb.affinity_names())
        self._refresh()

    # -- data / rendering -------------------------------------------------
    def _refresh(self) -> None:
        if not self._kb.is_built():
            self._table.setRowCount(0)
            self._status.setText("Knowledge base not built — use ‘Update game data’ on the Overview tab.")
            self._detail.clear()
            return
        query = self._search.text()
        kind = self._kind.currentText()
        masteries = self._class_filter.selected()
        affinities = self._affinity_filter.selected()

        skills = [] if kind == "Devotions" else self._kb.search_skills(query, masteries=masteries)
        devotions = [] if kind == "Skills" else self._kb.search_devotions(query, affinities=affinities)
        self._populate(skills, devotions)
        self._status.setText(f"{len(skills)} skill(s) · {len(devotions)} devotion(s)")

    def _populate(self, skills: list[dict], devotions: list[dict]) -> None:
        rows = [("skill", s) for s in skills] + [("devotion", d) for d in devotions]
        self._table.setRowCount(len(rows))
        for row, (kind, entry) in enumerate(rows):
            if kind == "skill":
                cells = [entry.get("name") or "", "Skill", entry.get("mastery") or "",
                         ", ".join(entry.get("damage_types") or []), entry.get("type") or ""]
            else:
                cells = [entry.get("name") or "", "Devotion",
                         ", ".join(entry.get("affinity_required") or {}),
                         ", ".join(entry.get("damage_types") or []),
                         ", ".join(entry.get("roles") or [])]
            name_item = QTableWidgetItem(cells[0])
            name_item.setData(Qt.ItemDataRole.UserRole, (kind, entry["id"]))
            self._table.setItem(row, 0, name_item)
            for col, text in enumerate(cells[1:], start=1):
                self._table.setItem(row, col, QTableWidgetItem(text))

    def _show_selected(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        kind, entry_id = self._table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if kind == "skill":
            entry = self._kb.skill(entry_id)
            rows = self._kb.skill_properties(entry) if entry else []
        else:
            entry = self._kb.devotion_by_id(entry_id)
            rows = self._kb.devotion_properties(entry) if entry else []
        self._detail.setHtml(self._render(rows))

    @staticmethod
    def _render(rows: list[tuple[str, str, str | None]]) -> str:
        if not rows:
            return ""
        heading = escape(rows[0][1])
        html = [f"<h3>{heading}</h3>", "<table cellspacing='6'>"]
        for label, value, color in rows[1:]:
            style = f' style="color:{color}"' if color else ""
            html.append(
                f"<tr><td{style}><b>{escape(label)}</b></td>"
                f"<td{style}>{escape(str(value))}</td></tr>"
            )
        html.append("</table>")
        return "".join(html)
