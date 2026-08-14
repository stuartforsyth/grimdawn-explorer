"""Headless smoke test for the Item Search tab.

Runs only when PySide6 is installed and a KB has been built (offscreen Qt platform),
so it verifies the UI wiring end-to-end locally and skips cleanly elsewhere.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gd_assistant.data.repository import KnowledgeBase

if not KnowledgeBase().is_built():
    pytest.skip("knowledge base not built", allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_item_search_tab_search_and_detail(app):
    from gd_assistant.config.settings import Settings
    from gd_assistant.ui.main_window import MainWindow

    window = MainWindow(Settings())
    tab = window._item_tab

    total = tab._table.rowCount()
    assert total > 1000                       # all items loaded

    tab._search.setText("aether amulet")
    narrowed = tab._table.rowCount()
    assert 0 < narrowed < total               # property search narrows the list

    tab._table.selectRow(0)
    assert tab._table.item(0, 0).text()       # a name is shown
    assert len(tab._detail.toPlainText()) > 0  # detail panel rendered


def test_skill_devotion_tab_search_and_detail(app):
    from gd_assistant.config.settings import Settings
    from gd_assistant.ui.main_window import MainWindow

    window = MainWindow(Settings())
    tab = window._skill_tab

    total = tab._table.rowCount()
    assert total > 300                         # skills + devotions loaded

    tab._search.setText("cold damage")
    narrowed = tab._table.rowCount()
    assert 0 < narrowed < total                # damage-type search narrows the list

    tab._search.setText("defensive")           # a capability role (devotions)
    assert tab._table.rowCount() > 0

    tab._table.selectRow(0)
    assert tab._table.item(0, 0).text()
    assert len(tab._detail.toPlainText()) > 0  # detail panel rendered

    # multi-select Class filter spans masteries (Nightblade + Berserker cold synergies)
    tab._search.setText("cold")
    tab._kind.setCurrentText("Skills")
    for action in tab._class_filter._menu.actions():
        if action.text() in ("Nightblade", "Berserker"):
            action.setChecked(True)
    masteries = {tab._table.item(r, 2).text() for r in range(tab._table.rowCount())}
    assert masteries == {"Nightblade", "Berserker"}    # only the two ticked classes
    assert tab._table.rowCount() > 1


def test_item_search_pinning_persists_and_stays_on_top(app, tmp_path):
    from PySide6.QtCore import Qt

    from gd_assistant.config.settings import Settings
    from gd_assistant.ui.item_search import ItemSearchTab

    cfg = tmp_path / "config.json"
    tab = ItemSearchTab(settings=Settings.load(cfg))

    tab._table.selectRow(0)
    pinned_id = tab._selected_id()
    tab._toggle_pin()                                    # pin it

    # persisted to the config file (survives restart)
    assert pinned_id in Settings.load(cfg).pinned_items
    assert tab._pin_btn.text() == "Unpin"

    # a search the pinned item does NOT match -> it still appears, at the top, marked
    tab._search.setText("zzz_no_such_item_qwerty")
    assert tab._table.rowCount() >= 1
    assert tab._table.item(0, 0).data(Qt.ItemDataRole.UserRole) == pinned_id
    assert not tab._table.item(0, 0).icon().isNull()   # pin icon shown, name text untouched
    assert tab._table.item(0, 0).text() == tab._kb.item(pinned_id)["name"]

    # unpin removes it from persistence
    tab._select_by_id(pinned_id)
    tab._toggle_pin()
    assert pinned_id not in Settings.load(cfg).pinned_items
