"""Search + export tab.

End-to-end flow:

1. User fills query / sources / language / year range / max-results.
2. ``Search`` button kicks off :func:`thesisagents.core.pipeline.run_search`
   on a worker thread.
3. Results populate the table; status bar reports the count. With a
   citation snowball selected the top results are expanded along their
   citation links first, and with a library file and "add" ticked the
   results are merged into it.
   ``Search library`` fills the same table from the library file instead,
   without any network access.
4. ``Export…`` opens a directory picker and runs ``export_collection``
   on another worker thread.

All worker callbacks land on the main thread because Qt signal/slot
across threads is queue-routed automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from thesisagents.cli_snowball import DEFAULT_SNOWBALL_MAX_TOTAL, DEFAULT_SNOWBALL_SEEDS
from thesisagents.core.constants import (
    DEFAULT_PAGE_SIZE,
    EXPORT_BIBTEX,
    EXPORT_PPTX,
    EXPORT_XLSX,
    MAX_RESULTS_PER_SOURCE,
)
from thesisagents.core.diagnostics import SourceStatus
from thesisagents.core.models import ExportOptions, PaperCollection, Query
from thesisagents.core.pipeline import run_search
from thesisagents.core.query import normalize_query
from thesisagents.core.snowball import Direction, expand_collection, snowball
from thesisagents.exporters import export_collection
from thesisagents.exporters.i18n import SUPPORTED_LANGUAGES as DECK_LANGUAGES
from thesisagents.fetchers.http import shutdown_clients
from thesisagents.gui.i18n import LANGUAGE_DISPLAY_NAMES, t
from thesisagents.gui.models.papers_table_model import PapersTableModel
from thesisagents.gui.widgets.responsive import (
    AdaptiveSplit,
    Breakpoint,
    adapt_form_rows,
    make_card,
)
from thesisagents.gui.widgets.source_multiselect import SourceMultiselect
from thesisagents.gui.workers import AsyncWorker, BlockingWorker
from thesisagents.library import AddReport, Library

_MIN_YEAR = 1900
_MAX_YEAR = 2100
#: Formats the one-button Export writes. Built from the format constants, not
#: typed out: the literal ``"bibtex"`` used here before is not a registered
#: format (the name is ``"bib"``), so the button reported
#: "no exporter registered for this format" on every click.
QUICK_EXPORT_FORMATS: tuple[str, ...] = (EXPORT_PPTX, EXPORT_XLSX, EXPORT_BIBTEX)
#: Label shown next to a source that contributed nothing for a reason other
#: than "no match". ``SourceStatus.OK`` is absent on purpose: an ok source
#: shows its result count instead.
_SOURCE_STATUS_KEYS: dict[SourceStatus, str] = {
    SourceStatus.FAILED: "search.source_failed",
    SourceStatus.RATE_LIMITED: "search.source_rate_limited",
    SourceStatus.DISABLED: "search.source_disabled",
}


#: The snowball selector: label key and the direction it stands for. The
#: bounds are the CLI's defaults (5 seeds, 20 new papers), so the same
#: search gives the same expansion from either surface.
_SNOWBALL_CHOICES: tuple[tuple[str, str | None], ...] = (
    ("search.snowball_off", None),
    ("search.snowball_references", Direction.REFERENCES.value),
    ("search.snowball_cited_by", Direction.CITED_BY.value),
    ("search.snowball_both", Direction.BOTH.value),
)
_LIBRARY_FILE_FILTER = "SQLite (*.db *.sqlite *.sqlite3);;All files (*)"
#: Result columns hidden on a compact window (authors, DOI): the title needs
#: the room, and both values stay in the export.
_COMPACT_HIDDEN_COLUMNS: tuple[int, ...] = (1, 4)
#: Starting width of the authors column, in pixels.
_AUTHORS_COLUMN_WIDTH = 170
#: Link schemes a double-click may hand to the desktop browser.
_OPENABLE_SCHEMES: frozenset[str] = frozenset({"http", "https"})


@dataclass(frozen=True)
class _SearchOutcome:
    """What a search worker hands back to the UI thread besides the papers.

    The boundary this guards: the worker thread. Everything the status line
    needs travels in this one frozen object through the ``finished`` signal,
    so the worker never touches a widget or a page attribute.

    ``discovered`` is the number of papers the snowball added (``None`` when
    it was off), ``library`` what merging into the library changed, and
    ``library_total`` the size of the library when the papers came from it.

    Example: ``_SearchOutcome(collection, discovered=3)`` after a search with
    the snowball on.
    """

    collection: PaperCollection
    discovered: int | None = None
    library: AddReport | None = None
    library_total: int | None = None


class SearchPage(QWidget):
    """Search + export page."""

    # Emitted whenever a fresh search completes (or the cached collection
    # is cleared). Receivers should use ``isinstance(obj, PaperCollection)``
    # because Signal(object) is the only typed-Python way to ship a
    # frozen dataclass across threads.
    collection_ready = Signal(object)
    #: The library file named on this tab, emitted as it is typed. The Deck
    #: tab listens, so its export keeps identifier checks in the same library.
    library_path_changed = Signal(str)
    #: ``True`` when a search, library search or export starts on a worker
    #: thread, ``False`` when it ends either way. The main window shows its
    #: progress indicator while any page is busy.
    busy_changed = Signal(bool)

    def __init__(self, ui_language: str = "en", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_language = ui_language
        self._collection: PaperCollection | None = None
        self._papers_model = PapersTableModel(language=ui_language)
        self._build_ui()

    def _build_ui(self) -> None:
        """Controls in three cards, the results table beside or below them.

        The cards group the form by question: what to search (query and
        sources), which papers to keep (language, count, years, venues), and
        what to do around the search (snowball, library). The action buttons
        sit in a footer pinned below the cards, so Search stays in reach
        however far the cards are scrolled.
        """
        language = self._ui_language
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        controls = QWidget(self)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 6, 0)
        controls_layout.setSpacing(12)

        query_card, query_layout = make_card(t("search.card_query", language), controls)
        self._query_input = QLineEdit(self)
        self._query_input.setPlaceholderText(t("search.query_placeholder", language))
        self._query_input.setClearButtonEnabled(True)
        # Enter in the query field runs the search, like a browser's search box.
        self._query_input.returnPressed.connect(self._on_search_clicked)
        query_layout.addWidget(QLabel(t("search.query_label", language), query_card))
        query_layout.addWidget(self._query_input)
        query_layout.addWidget(QLabel(t("search.sources_label", language), query_card))
        self._sources_widget = SourceMultiselect(self)
        query_layout.addWidget(self._sources_widget)
        controls_layout.addWidget(query_card)

        filters_card, filters_layout = make_card(t("search.card_filters", language), controls)
        form = QFormLayout()
        filters_layout.addLayout(form)

        self._language_combo = QComboBox(self)
        for code in DECK_LANGUAGES:
            display = LANGUAGE_DISPLAY_NAMES.get(code, code)
            # Suffix the BCP-47 code in dim parens so power users can
            # tell which slide-deck locale they are about to ship.
            self._language_combo.addItem(f"{display} ({code})", code)
        form.addRow(t("search.language_label", language), self._language_combo)

        self._max_spin = QSpinBox(self)
        self._max_spin.setRange(1, MAX_RESULTS_PER_SOURCE)
        self._max_spin.setValue(DEFAULT_PAGE_SIZE)
        form.addRow(t("search.max_results_label", language), self._max_spin)

        year_row = QWidget(self)
        year_layout = QHBoxLayout(year_row)
        year_layout.setContentsMargins(0, 0, 0, 0)
        self._year_from_spin = self._year_spin()
        self._year_to_spin = self._year_spin()
        year_layout.addWidget(QLabel(t("search.year_from", language)))
        year_layout.addWidget(self._year_from_spin, stretch=1)
        year_layout.addWidget(QLabel(t("search.year_to", language)))
        year_layout.addWidget(self._year_to_spin, stretch=1)
        form.addRow(year_row)

        self._top_tier_check = QCheckBox(t("search.top_tier_only", language), self)
        self._top_tier_check.setChecked(True)
        form.addRow(self._top_tier_check)
        adapt_form_rows(filters_card, form)
        controls_layout.addWidget(filters_card)

        library_card, library_card_layout = make_card(
            t("search.card_library", language), controls
        )
        library_form = QFormLayout()
        library_card_layout.addLayout(library_form)
        self._snowball_combo = QComboBox(self)
        for label_key, direction in _SNOWBALL_CHOICES:
            self._snowball_combo.addItem(t(label_key, language), direction)
        library_form.addRow(t("search.snowball_label", language), self._snowball_combo)

        library_row = QWidget(self)
        library_layout = QHBoxLayout(library_row)
        library_layout.setContentsMargins(0, 0, 0, 0)
        self._library_input = QLineEdit(self)
        self._library_input.setPlaceholderText(t("search.library_placeholder", language))
        self._library_input.textChanged.connect(
            lambda text: self.library_path_changed.emit(text.strip())
        )
        library_browse = QPushButton(t("search.library_browse", language), self)
        library_browse.clicked.connect(self._on_browse_library)
        library_layout.addWidget(self._library_input, stretch=1)
        library_layout.addWidget(library_browse)
        library_form.addRow(t("search.library_label", language), library_row)

        self._library_add_check = QCheckBox(t("search.library_add", language), self)
        library_form.addRow(self._library_add_check)
        adapt_form_rows(library_card, library_form)
        controls_layout.addWidget(library_card)
        controls_layout.addStretch(1)

        footer = QWidget(self)
        button_row = QHBoxLayout(footer)
        button_row.setContentsMargins(0, 0, 6, 0)
        self._search_button = QPushButton(t("search.search_button", language), self)
        self._search_button.setProperty("primary", True)
        self._search_button.setDefault(True)
        self._search_button.clicked.connect(self._on_search_clicked)
        self._library_search_button = QPushButton(
            t("search.library_search_button", language), self
        )
        self._library_search_button.clicked.connect(self._on_library_search_clicked)
        self._export_button = QPushButton(t("search.export_button", language), self)
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._on_export_clicked)
        button_row.addWidget(self._search_button, stretch=1)
        button_row.addWidget(self._library_search_button)
        button_row.addWidget(self._export_button)

        results = QWidget(self)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(6, 0, 0, 0)
        results_title = QLabel(t("search.results_title", language), results)
        results_title.setObjectName("CardTitle")
        results_layout.addWidget(results_title)
        self._table = QTableView(self)
        self._table.setModel(self._papers_model)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Authors can run to a long list: a fixed, user-resizable width
        # leaves the title (the stretched column) room to be read.
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, _AUTHORS_COLUMN_WIDTH)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        results_layout.addWidget(self._table, stretch=1)
        self._status_label = QLabel(t("search.status_idle", language), self)
        self._status_label.setObjectName("Muted")
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        results_layout.addWidget(self._status_label)

        self._split = AdaptiveSplit(controls, results, footer=footer, parent=self)
        outer.addWidget(self._split)

    def apply_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Re-arrange for the window size class (called by the main window).

        On a compact window the authors and DOI columns are hidden: with the
        title squeezed to a few characters the table is unreadable, and both
        values stay in the row's export.
        """
        self._split.apply_breakpoint(breakpoint)
        compact = breakpoint is Breakpoint.COMPACT
        for column in _COMPACT_HIDDEN_COLUMNS:
            self._table.setColumnHidden(column, compact)

    def _on_row_double_clicked(self, index: QModelIndex) -> None:
        """Open the paper's landing page in the browser.

        Only ``http`` / ``https`` links are opened: the URL comes from a
        remote API, and handing a ``file:`` or custom-scheme link to the
        desktop would let a source record launch a local program.
        """
        papers = self._papers_model.papers()
        if not (0 <= index.row() < len(papers)):
            return
        url = QUrl(papers[index.row()].url)
        if url.scheme() in _OPENABLE_SCHEMES:
            QDesktopServices.openUrl(url)

    def split(self) -> AdaptiveSplit:
        return self._split

    def table(self) -> QTableView:
        return self._table

    def _year_spin(self) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setRange(_MIN_YEAR - 1, _MAX_YEAR)
        spin.setSpecialValueText("—")
        spin.setValue(_MIN_YEAR - 1)
        return spin

    def _year(self, spin: QSpinBox) -> int | None:
        value = spin.value()
        return value if value >= _MIN_YEAR else None

    def _on_search_clicked(self) -> None:
        keywords = self._query_input.text().strip()
        if not keywords:
            self._set_status(t("search.error_empty_query", self._ui_language))
            return
        sources = self._sources_widget.selected()
        if not sources:
            self._set_status(t("search.error_empty_query", self._ui_language))
            return
        normalised = normalize_query(keywords)
        query = Query(
            keywords=normalised,
            sources=sources,
            max_results=self._max_spin.value(),
            year_from=self._year(self._year_from_spin),
            year_to=self._year(self._year_to_spin),
            top_tier_only=self._top_tier_check.isChecked(),
        )
        direction = self._snowball_combo.currentData()
        library_path = self._library_path()
        add_to_library = self._library_add_check.isChecked()
        if add_to_library and not library_path:
            self._set_status(t("search.error_no_library", self._ui_language))
            return
        self._set_busy()

        async def coro() -> _SearchOutcome:
            discovered: int | None = None
            try:
                collection = await run_search(query)
                if direction and collection.papers:
                    found = await snowball(
                        collection.papers[:DEFAULT_SNOWBALL_SEEDS],
                        known=collection.papers,
                        direction=direction,
                        keywords=query.keywords,
                        max_total=DEFAULT_SNOWBALL_MAX_TOTAL,
                    )
                    collection = expand_collection(collection, found)
                    discovered = len(found.discovered)
            finally:
                await shutdown_clients()
            report: AddReport | None = None
            if add_to_library and collection.papers:
                with Library(library_path) as library:
                    report = library.add_collection(collection)
            return _SearchOutcome(collection, discovered=discovered, library=report)

        worker = AsyncWorker(coro)
        worker.signals.finished.connect(self._on_search_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_library_search_clicked(self) -> None:
        """Fill the table from the library file. No network is used.

        The query field is the library query: stored papers matching it are
        listed best first, and an empty field lists the most recently seen.
        Max results and the year range apply. The papers then behave like
        search results: they can be exported, enriched and built into a deck.
        """
        library_path = self._library_path()
        if not library_path:
            self._set_status(t("search.error_no_library", self._ui_language))
            return
        text = self._query_input.text().strip()
        limit = self._max_spin.value()
        year_from = self._year(self._year_from_spin)
        year_to = self._year(self._year_to_spin)
        self._set_busy()

        def call() -> _SearchOutcome:
            with Library(library_path, create=False) as library:
                collection = library.collection(
                    text, limit=limit, year_from=year_from, year_to=year_to
                )
                return _SearchOutcome(collection, library_total=len(library))

        worker = BlockingWorker(call)
        worker.signals.finished.connect(self._on_search_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_browse_library(self) -> None:
        # A save dialog without the overwrite prompt: the file may exist (an
        # existing library) or not yet (one is created on the first add).
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("search.library_dialog_title", self._ui_language),
            self._library_path() or str(Path.cwd() / "thesis.db"),
            _LIBRARY_FILE_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self._library_input.setText(path)

    def _library_path(self) -> str:
        return self._library_input.text().strip()

    def _set_busy(self) -> None:
        self._search_button.setEnabled(False)
        self._library_search_button.setEnabled(False)
        self._export_button.setEnabled(False)
        self._set_status(t("search.status_running", self._ui_language))
        self.busy_changed.emit(True)

    def _on_search_finished(self, result: object) -> None:
        self.busy_changed.emit(False)
        outcome = result if isinstance(result, _SearchOutcome) else None
        collection = outcome.collection if outcome is not None else result
        if not isinstance(collection, PaperCollection):  # pragma: no cover — defensive
            self._on_worker_failed(
                RuntimeError(f"unexpected worker result type: {type(collection)!r}")
            )
            return
        self._collection = collection
        self._papers_model.set_collection(collection)
        self._search_button.setEnabled(True)
        self._library_search_button.setEnabled(True)
        self._export_button.setEnabled(bool(collection.papers))
        # Tell downstream tabs (Enrich, Deck) about the fresh results
        # so they enable their own actions without polling.
        self.collection_ready.emit(collection)
        self._set_status(self._finished_status(collection, outcome))

    def _finished_status(
        self, collection: PaperCollection, outcome: _SearchOutcome | None
    ) -> str:
        """The status line after a run: counts, sources, snowball, library."""
        language = self._ui_language
        if outcome is not None and outcome.library_total is not None:
            return t(
                "search.library_found", language,
                count=len(collection.papers), total=outcome.library_total,
            )
        parts = [t("search.status_done", language, count=len(collection.papers))]
        summary = self._source_summary(collection)
        if summary:
            parts.append(t("search.sources_summary", language, summary=summary))
        if outcome is not None and outcome.discovered is not None:
            parts.append(t("search.snowball_summary", language, count=outcome.discovered))
        if outcome is not None and outcome.library is not None:
            parts.append(
                t(
                    "search.library_added", language,
                    added=outcome.library.added, merged=outcome.library.merged,
                )
            )
        return " ".join(parts)

    def _source_summary(self, collection: PaperCollection) -> str:
        """What each source returned, as ``"arxiv 23, openalex 25, ieee (failed)"``.

        Why it is on the status line: a source that fails is skipped without
        stopping the search, so "Found 3 papers" alone cannot tell a narrow
        topic from a search that lost most of its sources. Empty when the
        collection carries no per-source counts.
        """
        diagnostics = collection.diagnostics
        if diagnostics is None:
            return ""
        parts: list[str] = []
        for stat in diagnostics.source_stats:
            label_key = _SOURCE_STATUS_KEYS.get(stat.status)
            if label_key is None:
                parts.append(f"{stat.source} {stat.returned}")
            else:
                parts.append(f"{stat.source} ({t(label_key, self._ui_language)})")
        return ", ".join(parts)

    def _on_worker_failed(self, err: object) -> None:
        self.busy_changed.emit(False)
        self._search_button.setEnabled(True)
        self._library_search_button.setEnabled(True)
        self._export_button.setEnabled(bool(self._collection and self._collection.papers))
        self._set_status(
            t("search.error_generic", self._ui_language, error=str(err))
        )

    def _on_export_clicked(self) -> None:
        if self._collection is None or not self._collection.papers:
            self._set_status(t("search.error_no_results", self._ui_language))
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            t("search.export_dialog_title", self._ui_language),
            str(Path.cwd() / "exports"),
        )
        if not directory:
            return
        language = self._language_combo.currentData() or "en"
        options = ExportOptions(
            formats=QUICK_EXPORT_FORMATS,
            out_dir=directory,
            language=language,
        )
        collection = self._collection
        self._export_button.setEnabled(False)
        self._set_status(t("search.status_export_running", self._ui_language))
        self.busy_changed.emit(True)

        library_path = self._library_path()

        def export_call() -> dict[str, Path]:
            if not library_path:
                return export_collection(collection, options)
            # With a library file the identifier checks are kept in it, so a
            # DOI or URL verified by an earlier export is not asked about again.
            with Library(library_path) as library:
                return export_collection(
                    collection, options, verification_cache=library.verification_cache()
                )

        worker = BlockingWorker(export_call)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_export_finished(self, written: object) -> None:
        self.busy_changed.emit(False)
        self._export_button.setEnabled(True)
        if not isinstance(written, dict) or not written:
            self._set_status(t("search.error_no_results", self._ui_language))
            return
        any_path = next(iter(written.values()))
        self._set_status(
            t("search.status_export_done", self._ui_language, path=str(any_path))
        )

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    # --- accessors used by tests ----------------------------------------

    def papers_model(self) -> PapersTableModel:
        return self._papers_model

    def status_text(self) -> str:
        return self._status_label.text()

    def set_query_text(self, text: str) -> None:
        self._query_input.setText(text)

    def set_library_path(self, path: str) -> None:
        self._library_input.setText(path)

    def library_add_checkbox(self) -> QCheckBox:
        return self._library_add_check

    def snowball_combo(self) -> QComboBox:
        return self._snowball_combo
