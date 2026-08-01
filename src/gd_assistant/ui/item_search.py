"""Item Search tab: search box + sortable table + detail panel, with pinning.

Left: a search box (matches item name OR any property — rarity, slot, set,
granted/+skill names + their class, damage types, friendly stat labels) and a table
sortable by any column (click a header; click again to reverse). Right: the selected
item's full property list, and a **Pin / Unpin** button.

Pinned items form a persistent "farm list": they are saved to config (survive
restarts) and always shown at the top of the table regardless of the current search
or sort. All data comes from the local KB via `KnowledgeBase`.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gd_assistant.config.settings import Settings
from gd_assistant.data import colors
from gd_assistant.data.repository import KnowledgeBase

# table column index -> KnowledgeBase.sort_by key
_SORT_KEYS = {0: "name", 1: "level", 2: "item_level", 3: "rarity", 4: "slot"}


def _pin_icon() -> QIcon:
    """A small red pin, drawn (font-independent) so it needs no asset file."""
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#d13030"))
    painter.drawEllipse(3, 1, 8, 8)          # pin head
    pen = QPen(QColor("#d13030"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(7, 8, 7, 13)            # needle
    painter.end()
    return QIcon(pm)


class _NumericItem(QTableWidgetItem):
    """Table cell that shows a number, blank if None."""

    def __init__(self, value: object) -> None:
        super().__init__("" if value is None else str(value))


class ItemSearchTab(QWidget):
    _COLUMNS = ("Name", "Req Lvl", "Item Lvl", "Rarity", "Slot")

    def __init__(self, kb: KnowledgeBase | None = None, settings: Settings | None = None) -> None:
        super().__init__()
        self._kb = kb or KnowledgeBase()
        self._settings = settings or Settings()
        self._pins: list[str] = list(self._settings.pinned_items)
        self._sort_by = "level"
        self._descending = False
        self._pin_icon = _pin_icon()

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search name or property — e.g. 'cold occultist', 'fire resistance', 'aether amulet'"
        )
        self._search.setToolTip(
            "Terms match anywhere and are combined with AND.\n"
            'Wrap words in "double quotes" to match an exact phrase — '
            '"converted to cold" only matches that adjacent phrase, '
            "whereas converted to cold (no quotes) matches all three words anywhere."
        )
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._refresh())

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setSortingEnabled(False)  # we sort manually so pins stay on top
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self._on_header_clicked)
        self._table.itemSelectionChanged.connect(self._show_selected)

        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        self._pin_btn = QPushButton("Pin")
        self._pin_btn.setEnabled(False)
        self._pin_btn.clicked.connect(self._toggle_pin)

        self._status = QLabel()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._search)
        left_layout.addWidget(self._table)
        left_layout.addWidget(self._status)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._detail)
        right_layout.addWidget(self._pin_btn)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.reload()

    def reload(self, kb: KnowledgeBase | None = None) -> None:
        """(Re)load after a KB rebuild — pass a fresh KnowledgeBase to drop caches."""
        if kb is not None:
            self._kb = kb
        self._refresh()

    # -- sorting ----------------------------------------------------------
    def _on_header_clicked(self, section: int) -> None:
        key = _SORT_KEYS.get(section)
        if key is None:
            return
        if key == self._sort_by:
            self._descending = not self._descending
        else:
            self._sort_by, self._descending = key, False
        order = Qt.SortOrder.DescendingOrder if self._descending else Qt.SortOrder.AscendingOrder
        self._table.horizontalHeader().setSortIndicator(section, order)
        self._refresh(keep_selection=True)

    # -- data / rendering -------------------------------------------------
    def _refresh(self, keep_selection: bool = False) -> None:
        if not self._kb.is_built():
            self._table.setRowCount(0)
            self._status.setText("Knowledge base not built — use ‘Update game data’ on the Overview tab.")
            self._detail.clear()
            self._pin_btn.setEnabled(False)
            return

        keep_id = self._selected_id() if keep_selection else None
        results = self._kb.search_items(self._search.text(), sort_by=self._sort_by,
                                        descending=self._descending)
        pin_ids = [pid for pid in self._pins if self._kb.item(pid)]  # drop stale ids
        pin_set = set(pin_ids)
        pinned = self._kb.sort_items([self._kb.item(pid) for pid in pin_ids],
                                     self._sort_by, self._descending)
        rest = [it for it in results if it["id"] not in pin_set]

        self._populate(pinned + rest, pin_set)
        self._status.setText(
            f"{len(pinned)} pinned · {len(rest)} match" if pin_set else f"{len(rest)} item(s)"
        )
        if keep_id is not None:
            self._select_by_id(keep_id)
            self._show_selected()  # selectRow is a no-op if the row index is unchanged

    def _populate(self, items: list[dict], pinned: set[str]) -> None:
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            name = QTableWidgetItem(item.get("name") or "")
            name.setData(Qt.ItemDataRole.UserRole, item["id"])
            if item["id"] in pinned:
                name.setIcon(self._pin_icon)  # icon only — leaves the name text untouched
            cells = [
                name,
                _NumericItem(item.get("level_requirement")),
                _NumericItem(item.get("item_level")),
                QTableWidgetItem(item.get("rarity") or ""),
                QTableWidgetItem(item.get("slot") or ""),
            ]
            brush = QColor(colors.rarity_color(item.get("rarity")) or "")
            for col, cell in enumerate(cells):
                if brush.isValid():
                    cell.setForeground(brush)
                self._table.setItem(row, col, cell)

    # -- selection / pinning ---------------------------------------------
    def _selected_id(self) -> str | None:
        selected = self._table.selectedItems()
        if not selected:
            return None
        return self._table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _select_by_id(self, item_id: str) -> None:
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).data(Qt.ItemDataRole.UserRole) == item_id:
                self._table.selectRow(row)
                return

    def _show_selected(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            self._pin_btn.setEnabled(False)
            return
        item = self._kb.item(item_id)
        if item is not None:
            self._detail.setHtml(self._render(item))
        self._pin_btn.setEnabled(True)
        self._pin_btn.setText("Unpin" if item_id in set(self._pins) else "Pin")

    def _toggle_pin(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        if item_id in self._pins:
            self._pins.remove(item_id)
        else:
            self._pins.append(item_id)
        self._settings.pinned_items = self._pins
        self._settings.save()
        self._refresh(keep_selection=True)  # re-anchors pinned to the top, keeps selection

    def _render(self, item: dict) -> str:
        rows = self._kb.item_properties(item)
        rarity_col = colors.rarity_color(item.get("rarity"))
        heading = escape(item.get("name") or "")
        h3 = f'<h3 style="color:{rarity_col}">{heading}</h3>' if rarity_col else f"<h3>{heading}</h3>"
        html = [h3, "<table cellspacing='6'>"]
        for label, value, color in rows:
            style = f' style="color:{color}"' if color else ""
            html.append(
                f"<tr><td{style}><b>{escape(label)}</b></td>"
                f"<td{style}>{escape(str(value))}</td></tr>"
            )
        html.append("</table>")
        return "".join(html)
