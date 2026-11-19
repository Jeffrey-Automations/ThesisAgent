"""Library page: a read-only view of a literature library file.

Closes ``progress.md`` #20. Before this page a library (``thesisagents/library/``)
could only be *searched* from the GUI. Its statistics, the searches that
filled it, the citation links between its papers and the stored DOI / URL
verdicts were reachable from the CLI, MCP (``library_stats``) and Python only.

What the page shows, all read from one :class:`LibrarySnapshot` loaded on a
worker thread:

* an **Overview** card: papers, searches, citation links, year span, papers
  per source, identifier checks per status;
* a **Papers** tab: every stored paper (or those matching the find box), and
  for the selected one its citation neighbours inside the library and its
  stored identifier verdicts;
* a **Searches** tab: every import, newest first.

The page never writes: the file is opened with ``create=False`` so a typo in
the path says "no library there" instead of creating an empty one. **Send to
Enrich and Deck** hands the listed papers on like a search result.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from thesisagents.core.diagnostics import PaperRelation
from thesisagents.core.export_validation import KIND_DOI, KIND_URL
from thesisagents.core.identifiers import canonical_doi
from thesisagents.core.models import Paper, PaperCollection
from thesisagents.gui.i18n import t
from thesisagents.gui.widgets.responsive import (
    AdaptiveSplit,
    Breakpoint,
    adapt_form_rows,
    make_card,
)
from thesisagents.gui.workers import BlockingWorker
from thesisagents.library import Library, LibraryEntry, LibraryRun, LibraryStats

_LIBRARY_FILE_FILTER = "SQLite (*.db *.sqlite *.sqlite3);;All files (*)"
_FORM_GROUP = "form/library"
_NO_VALUE = "—"
#: Role the tables sort by: numbers for counts and years (a missing year as
#: -1), case-folded text otherwise. A display column mixing ``2024`` and
#: ``"—"`` cannot be compared directly.
_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2


@dataclass(frozen=True)
class IdentifierVerdict:
    """One stored DOI / URL check of a paper: kind, value, status, date (ISO)."""

    kind: str
    value: str
    status: str
    checked_at: str


@dataclass(frozen=True)
class LibrarySnapshot:
    """Everything the page shows, read in one go on a worker thread.

    The boundary this guards: the SQLite connection. It lives only inside
    :func:`load_snapshot`, so the UI thread never touches the database and
    a slow disk never freezes the window. ``collection`` is what **Send to
    Enrich and Deck** hands on: the listed papers with their citation links.

    Example: ``load_snapshot("thesis.db", "graph").stats.papers``.
    """

    path: str
    query: str
    stats: LibraryStats
    entries: tuple[LibraryEntry, ...]
    runs: tuple[LibraryRun, ...]
    relations: tuple[PaperRelation, ...]
    verdicts: Mapping[str, tuple[IdentifierVerdict, ...]]
    collection: PaperCollection

    def paper_titles(self) -> dict[str, str]:
        """``dedup_key`` → title for every listed paper."""
        return {entry.paper.dedup_key(): entry.paper.title for entry in self.entries}


def load_snapshot(path: str, query: str = "") -> LibrarySnapshot:
    """Read a library file into a :class:`LibrarySnapshot`. Blocking.

    Raises ``FileNotFoundError`` (from ``Library(create=False)``) when there
    is no library at ``path``, which the page reports on its status line.
    """
    with Library(path, create=False) as library:
        entries = tuple(library.search(query, limit=None))
        keys = {entry.paper.dedup_key() for entry in entries}
        relations = tuple(
            relation
            for relation in library.relations()
            if relation.source_key in keys or relation.target_key in keys
        )
        verdicts = {
            entry.paper.dedup_key(): _stored_verdicts(library, entry.paper)
            for entry in entries
        }
        return LibrarySnapshot(
            path=path,
            query=query,
            stats=library.stats(),
            entries=entries,
            runs=tuple(library.runs()),
            relations=relations,
            verdicts=verdicts,
            collection=library.collection(query),
        )


def _stored_verdicts(library: Library, paper: Paper) -> tuple[IdentifierVerdict, ...]:
    """The cached DOI and URL verdicts of ``paper``, keyed the way the export
    preflight stores them (a canonical DOI, an ``https`` URL)."""
    targets: list[tuple[str, str, str]] = []
    canonical = canonical_doi(paper.doi) if paper.doi else None
    if canonical:
        targets.append((KIND_DOI, paper.doi or canonical, canonical))
    if paper.url:
        url = paper.url.strip()
        https = "https://" + url[len("http://"):] if url.startswith("http://") else url
        targets.append((KIND_URL, url, https))
    found: list[IdentifierVerdict] = []
    for kind, shown, key in targets:
        stored = library.stored_verdict(kind, key)
        if stored is not None:
            verdict, when = stored
            found.append(
                IdentifierVerdict(kind, shown, verdict.status.value, when.date().isoformat())
            )
    return tuple(found)


class LibraryPage(QWidget):
    """Read-only browser for a library file. See the module docstring."""

    #: The listed papers, sent on to Enrich and Deck like a search result.
    collection_ready = Signal(object)
    #: ``True`` while a library is being read on a worker thread.
    busy_changed = Signal(bool)

    def __init__(self, ui_language: str = "en", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_language = ui_language
        self._snapshot: LibrarySnapshot | None = None
        self._papers_model = QStandardItemModel(0, 5, self)
        self._runs_model = QStandardItemModel(0, 4, self)
        self._build_ui()

    # --- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        language = self._ui_language
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        controls = QWidget(self)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 6, 0)
        controls_layout.setSpacing(12)

        file_card, file_layout = make_card(t("library.card_file", language), controls)
        path_row = QHBoxLayout()
        self._path_input = QLineEdit(self)
        self._path_input.setPlaceholderText(t("search.library_placeholder", language))
        self._path_input.returnPressed.connect(self._on_open_clicked)
        browse = QPushButton(t("search.library_browse", language), self)
        browse.clicked.connect(self._on_browse)
        path_row.addWidget(self._path_input, stretch=1)
        path_row.addWidget(browse)
        file_layout.addLayout(path_row)
        self._query_input = QLineEdit(self)
        self._query_input.setPlaceholderText(t("library.query_placeholder", language))
        self._query_input.setClearButtonEnabled(True)
        self._query_input.returnPressed.connect(self._on_open_clicked)
        file_layout.addWidget(self._query_input)
        controls_layout.addWidget(file_card)

        overview_card, overview_layout = make_card(
            t("library.card_overview", language), controls
        )
        form = QFormLayout()
        overview_layout.addLayout(form)
        self._stat_labels: dict[str, QLabel] = {}
        for key in ("papers", "runs", "relations", "years", "sources", "checks"):
            value = QLabel(_NO_VALUE, overview_card)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(t(f"library.stat_{key}", language), value)
            self._stat_labels[key] = value
        # Short labels and values: keep them side by side down to 300 px.
        adapt_form_rows(overview_card, form, threshold=300)
        controls_layout.addWidget(overview_card)
        controls_layout.addStretch(1)

        footer = QWidget(self)
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(0, 0, 6, 0)
        self._open_button = QPushButton(t("library.open_button", language), self)
        self._open_button.setProperty("primary", True)
        self._open_button.clicked.connect(self._on_open_clicked)
        self._send_button = QPushButton(t("library.send_button", language), self)
        self._send_button.setEnabled(False)
        self._send_button.clicked.connect(self._on_send_clicked)
        buttons.addWidget(self._open_button, stretch=1)
        buttons.addWidget(self._send_button)

        results = QWidget(self)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(6, 0, 0, 0)
        self._tabs = QTabWidget(results)
        self._tabs.setDocumentMode(True)
        # The style's own base line ignores the theme (a white rule in dark
        # mode); the stylesheet's pane border draws the line instead.
        self._tabs.tabBar().setDrawBase(False)
        self._tabs.addTab(self._build_papers_tab(), t("library.tab_papers", language))
        self._tabs.addTab(self._build_runs_tab(), t("library.tab_runs", language))
        results_layout.addWidget(self._tabs, stretch=1)
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("Muted")
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        results_layout.addWidget(self._status_label)

        self._split = AdaptiveSplit(controls, results, footer=footer, parent=self)
        outer.addWidget(self._split)

    def _build_papers_tab(self) -> QWidget:
        language = self._ui_language
        self._papers_model.setHorizontalHeaderLabels([
            t("results.col_title", language),
            t("results.col_year", language),
            t("library.col_sources", language),
            t("library.col_seen", language),
            t("library.col_last_seen", language),
        ])
        self._papers_table = _table(self._papers_model, self)
        header = self._papers_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 320)
        self._papers_table.selectionModel().currentRowChanged.connect(self._on_paper_selected)
        self._detail = QTextBrowser(self)
        self._detail.setOpenLinks(False)
        self._detail.setPlaceholderText(t("library.detail_hint", language))
        split = QSplitter(Qt.Orientation.Vertical, self)
        split.setChildrenCollapsible(False)
        split.addWidget(self._papers_table)
        split.addWidget(self._detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

    def _build_runs_tab(self) -> QWidget:
        language = self._ui_language
        self._runs_model.setHorizontalHeaderLabels([
            t("library.col_date", language),
            t("library.col_kind", language),
            t("library.col_keywords", language),
            t("library.col_papers", language),
        ])
        self._runs_table = _table(self._runs_model, self)
        self._runs_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        return self._runs_table

    # --- public ------------------------------------------------------------

    def apply_breakpoint(self, breakpoint: Breakpoint) -> None:
        self._split.apply_breakpoint(breakpoint)

    def split(self) -> AdaptiveSplit:
        return self._split

    def set_library_path(self, path: str) -> None:
        """Follow the library file named on the Search page."""
        self._path_input.setText(path.strip())

    def library_path(self) -> str:
        return self._path_input.text().strip()

    def snapshot(self) -> LibrarySnapshot | None:
        return self._snapshot

    def status_text(self) -> str:
        return self._status_label.text()

    def papers_model(self) -> QStandardItemModel:
        return self._papers_model

    def runs_model(self) -> QStandardItemModel:
        return self._runs_model

    def detail_text(self) -> str:
        return self._detail.toPlainText()

    def stat_text(self, key: str) -> str:
        return self._stat_labels[key].text()

    def select_paper(self, row: int) -> None:
        self._papers_table.selectRow(row)

    def save_form(self, store: QSettings) -> None:
        store.setValue(f"{_FORM_GROUP}/path", self._path_input.text())
        store.setValue(f"{_FORM_GROUP}/query", self._query_input.text())

    def restore_form(self, store: QSettings) -> None:
        self._path_input.setText(store.value(f"{_FORM_GROUP}/path", "", type=str))
        self._query_input.setText(store.value(f"{_FORM_GROUP}/query", "", type=str))

    # --- loading -------------------------------------------------------------

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("search.library_dialog_title", self._ui_language),
            self.library_path() or str(Path.cwd()),
            _LIBRARY_FILE_FILTER,
        )
        if path:
            self._path_input.setText(path)
            self._on_open_clicked()

    def _on_open_clicked(self) -> None:
        path = self.library_path()
        if not path:
            self._status_label.setText(t("search.error_no_library", self._ui_language))
            return
        query = self._query_input.text().strip()
        self._open_button.setEnabled(False)
        self._send_button.setEnabled(False)
        self.busy_changed.emit(True)
        worker = BlockingWorker(lambda: load_snapshot(path, query))
        worker.signals.finished.connect(self._on_loaded)
        worker.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_failed(self, err: object) -> None:
        self.busy_changed.emit(False)
        self._open_button.setEnabled(True)
        self._send_button.setEnabled(self._snapshot is not None)
        self._status_label.setText(t("library.error", self._ui_language, error=str(err)))

    def _on_loaded(self, result: object) -> None:
        self.busy_changed.emit(False)
        self._open_button.setEnabled(True)
        if not isinstance(result, LibrarySnapshot):  # pragma: no cover - defensive
            self._on_failed(RuntimeError(f"unexpected result {type(result)!r}"))
            return
        self._snapshot = result
        self._show_stats(result.stats)
        self._fill_papers(result.entries)
        self._fill_runs(result.runs)
        self._detail.clear()
        self._send_button.setEnabled(bool(result.entries))
        self._status_label.setText(
            t(
                "library.status_loaded", self._ui_language,
                shown=len(result.entries), papers=result.stats.papers,
                runs=result.stats.runs, relations=result.stats.relations,
            )
        )

    def _show_stats(self, stats: LibraryStats) -> None:
        years = (
            f"{stats.year_min} – {stats.year_max}"
            if stats.year_min is not None and stats.year_max is not None
            else _NO_VALUE
        )
        values = {
            "papers": str(stats.papers),
            "runs": str(stats.runs),
            "relations": str(stats.relations),
            "years": years,
            "sources": _counts(stats.sources),
            "checks": _counts(stats.verifications),
        }
        for key, value in values.items():
            self._stat_labels[key].setText(value)

    def _fill_papers(self, entries: tuple[LibraryEntry, ...]) -> None:
        self._papers_model.removeRows(0, self._papers_model.rowCount())
        for entry in entries:
            year = entry.paper.year
            title = _item(entry.paper.title)
            title.setData(entry.paper.dedup_key(), Qt.ItemDataRole.UserRole)
            self._papers_model.appendRow([
                title,
                _item(str(year) if year is not None else _NO_VALUE, -1 if year is None else year),
                _item(", ".join(entry.sources)),
                _item(str(entry.times_seen), entry.times_seen),
                _item(entry.last_seen[:10]),
            ])

    def _fill_runs(self, runs: tuple[LibraryRun, ...]) -> None:
        self._runs_model.removeRows(0, self._runs_model.rowCount())
        for run in runs:
            self._runs_model.appendRow([
                _item(run.started_at[:16].replace("T", " ")),
                _item(run.kind),
                _item(run.keywords),
                _item(str(run.papers), run.papers),
            ])

    # --- selection detail ------------------------------------------------------

    def _on_paper_selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._snapshot is None or not current.isValid():
            return
        key = self._papers_model.item(current.row(), 0).data(Qt.ItemDataRole.UserRole)
        entry = next((e for e in self._snapshot.entries if e.paper.dedup_key() == key), None)
        if entry is not None:
            self._detail.setHtml(self._detail_html(entry))

    def _detail_html(self, entry: LibraryEntry) -> str:
        """The selected paper's links and verdicts. Every value is escaped:
        titles and identifiers come from remote APIs."""
        assert self._snapshot is not None  # noqa: S101 # nosec B101  # only called with a snapshot
        language = self._ui_language
        key = entry.paper.dedup_key()
        titles = self._snapshot.paper_titles()
        cites: list[str] = []
        cited_by: list[str] = []
        for relation in self._snapshot.relations:
            if relation.citing_key == key and relation.cited_key != key:
                cites.append(titles.get(relation.cited_key, relation.cited_key))
            elif relation.cited_key == key:
                cited_by.append(titles.get(relation.citing_key, relation.citing_key))
        verdicts = [
            f"{v.kind.upper()} {v.value}: {v.status} ({v.checked_at})"
            for v in self._snapshot.verdicts.get(key, ())
        ]
        parts = [f"<h3>{html.escape(entry.paper.title)}</h3>"]
        if entry.paper.authors:
            parts.append(f"<p>{html.escape(', '.join(entry.paper.authors))}</p>")
        for label_key, items in (
            ("library.detail_cites", sorted(set(cites))),
            ("library.detail_cited_by", sorted(set(cited_by))),
            ("library.detail_checks", verdicts),
        ):
            parts.append(f"<p><b>{html.escape(t(label_key, language, count=len(items)))}</b></p>")
            if items:
                rows = "".join(f"<li>{html.escape(item)}</li>" for item in items)
                parts.append(f"<ul>{rows}</ul>")
            else:
                parts.append(f"<p>{html.escape(t('library.detail_none', language))}</p>")
        return "".join(parts)

    # --- hand-off ------------------------------------------------------------------

    def _on_send_clicked(self) -> None:
        if self._snapshot is None or not self._snapshot.collection.papers:
            return
        collection = self._snapshot.collection
        self.collection_ready.emit(collection)
        self._status_label.setText(
            t("library.status_sent", self._ui_language, count=len(collection.papers))
        )


def _item(text: str, sort: object | None = None) -> QStandardItem:
    """A read-only cell showing ``text`` and sorting by ``sort`` (the text by default)."""
    item = QStandardItem(text)
    item.setData(text.casefold() if sort is None else sort, _SORT_ROLE)
    return item


def _table(model: QStandardItemModel, parent: QWidget) -> QTableView:
    model.setSortRole(_SORT_ROLE)
    table = QTableView(parent)
    table.setModel(model)
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setSortingEnabled(True)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    return table


def _counts(counts: Mapping[str, int]) -> str:
    """``{"arxiv": 12, "openalex": 30}`` → ``"arxiv 12, openalex 30"``."""
    return ", ".join(f"{name} {count}" for name, count in counts.items()) or _NO_VALUE
