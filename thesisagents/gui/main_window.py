"""Main application window: a sidebar, the four pages, and a status bar.

Layout, from left to right: the :class:`NavRail` sidebar, then a stack
holding one page at a time. Each page has a title and a one-line subtitle
saying what the step does, above its body. The status bar at the bottom
shows a progress bar while any page has work running on a worker thread.

The window adapts to its width (see ``widgets/responsive.py``):

* **Compact** (< 760 px): the sidebar collapses to icons, forms put their
  labels above the fields, controls sit above the results.
* **Medium** (760-1179 px): full sidebar, controls above the results.
* **Expanded** (>= 1180 px): controls in a side column beside the results.

The pages are told when the size class changes (``apply_breakpoint``), so
each one decides how to re-arrange itself. ``Ctrl+1`` ... ``Ctrl+4`` switch
pages from the keyboard.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from thesisagents.core.models import PaperCollection
from thesisagents.gui.i18n import t
from thesisagents.gui.pages.deck import DeckPage
from thesisagents.gui.pages.enrich import EnrichPage
from thesisagents.gui.pages.search import SearchPage
from thesisagents.gui.pages.settings import (
    SettingsPage,
    saved_style,
    saved_theme,
    settings_store,
)
from thesisagents.gui.theme import THEME_SYSTEM, apply_theme
from thesisagents.gui.widgets.nav_rail import NavRail
from thesisagents.gui.widgets.responsive import Breakpoint, breakpoint_for_width

# The floor fits a 1366 x 768 laptop at 125 % scaling with room to spare:
# the compact layout (icon sidebar, stacked panes, wrapped form rows) is
# what makes a window this small usable.
_MIN_WIDTH = 640
_MIN_HEIGHT = 480
_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 800
# QSettings key holding the window's size, position and maximised state.
_GEOMETRY_KEY = "window/geometry"

# Page order: (icon, nav label key, subtitle key). The index is the
# sidebar index, the stack index and the Ctrl+N shortcut.
_SEARCH, _ENRICH, _DECK, _SETTINGS = range(4)
_PAGE_META: tuple[tuple[str, str, str], ...] = (
    ("search", "nav.search", "page.search_subtitle"),
    ("enrich", "nav.enrich", "page.enrich_subtitle"),
    ("deck", "nav.deck", "page.deck_subtitle"),
    ("settings", "nav.settings", "page.settings_subtitle"),
)


class MainWindow(QMainWindow):
    """Top-level window. Owns the sidebar, the page stack and every page.

    The window's size and position are saved to QSettings when it closes
    and restored when the next one is built.
    """

    def __init__(self, ui_language: str = "en", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_language = ui_language
        self._breakpoint: Breakpoint | None = None
        self._busy_pages: set[str] = set()
        self.setWindowTitle(t("app.title", ui_language))
        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        self._restore_geometry()

        self._search_page = SearchPage(ui_language=ui_language)
        self._enrich_page = EnrichPage(ui_language=ui_language)
        self._deck_page = DeckPage(ui_language=ui_language)
        self._settings_page = SettingsPage(ui_language=ui_language)

        self._nav = NavRail(
            brand=t("app.title", ui_language),
            toggle_tip=t("nav.toggle", ui_language),
        )
        self._stack = QStackedWidget(self)
        self._headers: list[QWidget] = []
        bodies: tuple[QWidget, ...] = (
            self._search_page,
            self._enrich_page,
            self._deck_page,
            self._scrollable(self._settings_page),
        )
        for index, (icon, label_key, subtitle_key) in enumerate(_PAGE_META):
            self._nav.add_item(
                icon, t(label_key, ui_language), bottom=index == _SETTINGS
            )
            self._stack.addWidget(
                self._page_frame(
                    t(label_key, ui_language), t(subtitle_key, ui_language), bodies[index]
                )
            )
        self._nav.current_changed.connect(self._stack.setCurrentIndex)

        central = QWidget(self)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._nav)
        row.addWidget(self._stack, stretch=1)
        self.setCentralWidget(central)

        self._build_status_bar()
        self._wire_pages()
        for index in range(len(_PAGE_META)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self._nav.set_current(i))
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        self._apply_breakpoint(breakpoint_for_width(self.width()))
        self._restore_forms()

    # --- construction ---------------------------------------------------

    def _page_frame(self, title: str, subtitle: str, body: QWidget) -> QWidget:
        """A page with its title and subtitle above ``body``."""
        frame = QWidget(self)
        frame.setObjectName("PageBody")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(4)
        header = QWidget(frame)
        header.setObjectName("PageHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)
        heading = QLabel(title, header)
        heading.setObjectName("PageTitle")
        caption = QLabel(subtitle, header)
        caption.setObjectName("PageSubtitle")
        caption.setWordWrap(True)
        header_layout.addWidget(heading)
        header_layout.addWidget(caption)
        layout.addWidget(header)
        layout.addSpacing(10)
        layout.addWidget(body, stretch=1)
        self._headers.append(frame)
        return frame

    def _scrollable(self, page: QWidget) -> QScrollArea:
        """Wrap a page that has no results pane, so it scrolls when short.

        ``widgetResizable=True`` makes the page stretch with the scroll
        area's width instead of sitting at its size hint.
        """
        scroll = QScrollArea(self)
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)
        bar.setSizeGripEnabled(True)
        self._busy_bar = QProgressBar(bar)
        self._busy_bar.setRange(0, 0)  # indeterminate
        self._busy_bar.setFixedWidth(160)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setVisible(False)
        bar.addPermanentWidget(self._busy_bar)
        self.setStatusBar(bar)

    def _wire_pages(self) -> None:
        # Data flow between steps: Search → Enrich (raw collection) and
        # Search → Deck (so the user can skip enrichment), plus Enrich →
        # Deck (the enriched collection takes precedence).
        self._search_page.collection_ready.connect(self._enrich_page.set_collection)
        self._search_page.collection_ready.connect(self._deck_page.set_collection)
        self._search_page.library_path_changed.connect(self._deck_page.set_library_path)
        self._enrich_page.collection_ready.connect(self._deck_page.set_collection)
        self._search_page.collection_ready.connect(self._on_search_collection)
        self._enrich_page.collection_ready.connect(self._on_enriched_collection)
        for key, page in (
            ("search", self._search_page),
            ("enrich", self._enrich_page),
            ("deck", self._deck_page),
        ):
            page.busy_changed.connect(lambda busy, k=key: self._on_busy_changed(k, busy))
        self._settings_page.theme_changed.connect(self._on_theme_changed)

    # --- responsive -----------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_breakpoint(breakpoint_for_width(event.size().width()))

    def _apply_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Re-arrange the sidebar and every page for ``breakpoint``."""
        if breakpoint == self._breakpoint:
            return
        self._breakpoint = breakpoint
        self._nav.set_compact(breakpoint is Breakpoint.COMPACT)
        margin = 12 if breakpoint is Breakpoint.COMPACT else 24
        for frame in self._headers:
            frame.layout().setContentsMargins(margin, 14, margin, 10)
        for page in (
            self._search_page, self._enrich_page, self._deck_page, self._settings_page,
        ):
            page.apply_breakpoint(breakpoint)

    # --- slots ------------------------------------------------------------

    def _on_search_collection(self, collection: object) -> None:
        count = len(collection.papers) if isinstance(collection, PaperCollection) else 0
        badge = str(count) if count else ""
        self._nav.set_badge(_ENRICH, badge)
        self._nav.set_badge(_DECK, badge)

    def _on_enriched_collection(self, collection: object) -> None:
        if isinstance(collection, PaperCollection):
            count = len(collection.papers)
            self._nav.set_badge(_DECK, str(count) if count else "")

    def _on_busy_changed(self, key: str, busy: bool) -> None:
        if busy:
            self._busy_pages.add(key)
        else:
            self._busy_pages.discard(key)
        working = bool(self._busy_pages)
        self._busy_bar.setVisible(working)
        if working:
            self.statusBar().showMessage(t("status.busy", self._ui_language))
        else:
            self.statusBar().clearMessage()

    def _on_theme_changed(self, choice: str) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, choice, saved_style())
        self._nav.refresh_icons()

    def _on_system_scheme(self, _scheme: object) -> None:
        """Follow the OS switching light / dark, when the theme is "system"."""
        if saved_theme() == THEME_SYSTEM:
            self._on_theme_changed(THEME_SYSTEM)

    # --- geometry ---------------------------------------------------------

    def _restore_geometry(self) -> None:
        """Apply the geometry saved by the last window, if any.

        ``restoreGeometry`` moves a window that would land off-screen (a
        monitor that is gone) back onto an available screen, and ignores
        data it cannot parse, so the defaults above stay in that case.
        """
        saved = settings_store().value(_GEOMETRY_KEY)
        if isinstance(saved, QByteArray) and not saved.isEmpty():
            self.restoreGeometry(saved)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Save the window geometry and the form values, then close as usual."""
        store = settings_store()
        store.setValue(_GEOMETRY_KEY, self.saveGeometry())
        self.save_forms(store)
        super().closeEvent(event)

    def save_forms(self, store: QSettings) -> None:
        """Write the Search, Enrich and Deck fields so the next start has them."""
        for page in (self._search_page, self._enrich_page, self._deck_page):
            page.save_form(store)
        store.sync()

    def _restore_forms(self) -> None:
        store = settings_store()
        for page in (self._search_page, self._enrich_page, self._deck_page):
            page.restore_form(store)

    # --- accessors used by tests ----------------------------------------

    def search_page(self) -> SearchPage:
        return self._search_page

    def settings_page(self) -> SettingsPage:
        return self._settings_page

    def enrich_page(self) -> EnrichPage:
        return self._enrich_page

    def deck_page(self) -> DeckPage:
        return self._deck_page

    def nav_rail(self) -> NavRail:
        return self._nav

    def page_stack(self) -> QStackedWidget:
        return self._stack

    def current_breakpoint(self) -> Breakpoint | None:
        return self._breakpoint

    def is_busy(self) -> bool:
        """Whether the status-bar progress indicator is showing."""
        return bool(self._busy_pages)

    def page_count(self) -> int:
        return self._stack.count()

    def tab_count(self) -> int:
        """Kept for callers of the tabbed window: the number of pages."""
        return self.page_count()


if __name__ == "__main__":
    # Run this module directly for a quick look at the window while
    # developing: ``python -m thesisagents.gui.main_window``. It goes through
    # ``app.main`` rather than building ``MainWindow`` here, because ``main``
    # also pins the HiDPI policy, loads the saved API keys into the
    # environment, applies the saved theme and picks the interface language.
    # A bare ``MainWindow()`` would skip all four and open unstyled, in English.
    from thesisagents.gui.app import main

    raise SystemExit(main())
