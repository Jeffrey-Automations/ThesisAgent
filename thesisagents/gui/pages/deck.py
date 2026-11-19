"""Deck tab.

Granular export controls for a PaperCollection — supplements the Search
tab's one-button Export by exposing every ExportOptions knob:

* Output directory + filename stem
* Per-format checkboxes (pptx / xlsx / bib / md / json / ris / csv / csl)
* Deck language (independent of UI language)
* Max-slides cap (per-paper)
* Include-abstract toggle
* Dark-mode toggle
* Verify-identifiers toggle (the export preflight, on by default)

The page accepts either the raw collection from SearchPage or the
enriched one from EnrichPage. ``set_collection`` is the only entry
point — the page does not call the search pipeline itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QStandardItem, QStandardItemModel
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

from thesisagents.core.models import ExportOptions, PaperCollection
from thesisagents.exporters import export_collection
from thesisagents.exporters.i18n import SUPPORTED_LANGUAGES as DECK_LANGUAGES
from thesisagents.gui.i18n import LANGUAGE_DISPLAY_NAMES, t
from thesisagents.gui.widgets.responsive import (
    AdaptiveSplit,
    Breakpoint,
    ReflowGrid,
    adapt_form_rows,
    make_card,
)
from thesisagents.gui.workers import BlockingWorker
from thesisagents.library import Library

# Match thesisagents.exporters.__init__.SUPPORTED_FORMATS ordering.
_FORMAT_CHOICES: tuple[tuple[str, str], ...] = (
    ("pptx", "deck.format_pptx"),
    ("xlsx", "deck.format_xlsx"),
    ("bib", "deck.format_bib"),
    ("md", "deck.format_md"),
    ("json", "deck.format_json"),
    ("ris", "deck.format_ris"),
    ("csv", "deck.format_csv"),
    ("csl", "deck.format_csl"),
)
_DEFAULT_FORMATS: frozenset[str] = frozenset({"pptx", "xlsx", "bib"})
_DEFAULT_MAX_SLIDES = 25


class DeckPage(QWidget):
    """Granular export controls for the active collection."""

    #: ``True`` when an export starts on a worker thread, ``False`` when it
    #: ends either way. Drives the main window's progress indicator.
    busy_changed = Signal(bool)

    def __init__(self, ui_language: str = "en", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_language = ui_language
        self._collection: PaperCollection | None = None
        self._collection_is_enriched: bool = False
        self._last_written_dir: Path | None = None
        self._library_path = ""
        self._files_model = QStandardItemModel(0, 2, self)
        self._files_model.setHorizontalHeaderLabels([
            t("deck.column_format", ui_language),
            t("deck.column_path", ui_language),
        ])
        self._build_ui()

    def _build_ui(self) -> None:
        """Output, format and option cards beside / above the written files."""
        language = self._ui_language
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        controls = QWidget(self)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 6, 0)
        controls_layout.setSpacing(12)

        # Output dir + filename + deck language
        output_card, output_layout = make_card(t("deck.output_group", language), controls)
        output_form = QFormLayout()
        output_layout.addLayout(output_form)

        dir_row = QWidget(self)
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self._out_dir_input = QLineEdit(self)
        self._out_dir_input.setText(str(Path.cwd() / "exports"))
        browse = QPushButton(t("deck.browse_button", language), self)
        browse.clicked.connect(self._on_browse_out_dir)
        dir_layout.addWidget(self._out_dir_input, stretch=1)
        dir_layout.addWidget(browse)
        output_form.addRow(t("deck.out_dir_label", language), dir_row)

        self._filename_stem_input = QLineEdit(self)
        self._filename_stem_input.setPlaceholderText(
            t("deck.filename_stem_placeholder", language),
        )
        output_form.addRow(t("deck.filename_stem_label", language), self._filename_stem_input)

        self._language_combo = QComboBox(self)
        for code in DECK_LANGUAGES:
            display = LANGUAGE_DISPLAY_NAMES.get(code, code)
            self._language_combo.addItem(display, code)
        output_form.addRow(t("deck.language_label", language), self._language_combo)
        adapt_form_rows(output_card, output_form)
        controls_layout.addWidget(output_card)

        # Format check boxes, re-flowed to the pane width
        format_card, format_layout = make_card(t("deck.format_group", language), controls)
        self._format_checks: dict[str, QCheckBox] = {}
        for fmt, label_key in _FORMAT_CHOICES:
            chk = QCheckBox(t(label_key, language))
            chk.setChecked(fmt in _DEFAULT_FORMATS)
            self._format_checks[fmt] = chk
        self._format_grid = ReflowGrid(list(self._format_checks.values()), parent=format_card)
        format_layout.addWidget(self._format_grid)
        controls_layout.addWidget(format_card)

        # Options
        options_card, options_layout = make_card(t("deck.options_group", language), controls)
        options_form = QFormLayout()
        options_layout.addLayout(options_form)
        self._max_slides_spin = QSpinBox(self)
        self._max_slides_spin.setRange(0, 200)
        self._max_slides_spin.setValue(_DEFAULT_MAX_SLIDES)
        self._max_slides_spin.setSpecialValueText(t("deck.unlimited", language))
        options_form.addRow(t("deck.max_slides_label", language), self._max_slides_spin)
        self._include_abstract_check = QCheckBox(t("deck.include_abstract_label", language), self)
        self._include_abstract_check.setChecked(True)
        options_form.addRow(self._include_abstract_check)
        # Default is the light navy-band deck; this checkbox is the
        # opt-IN toggle for dark mode (OLED / low-light venues).
        self._dark_mode_check = QCheckBox(t("deck.dark_mode_label", language), self)
        self._dark_mode_check.setChecked(False)
        options_form.addRow(self._dark_mode_check)
        # Export preflight: on by default. Unchecking it is the GUI form of
        # the CLI's --no-verify-identifiers, for a machine with no network.
        self._verify_identifiers_check = QCheckBox(
            t("deck.verify_identifiers_label", language), self,
        )
        self._verify_identifiers_check.setChecked(True)
        options_form.addRow(self._verify_identifiers_check)
        # Deck template: the GUI form of --pptx-template and
        # --pptx-template-config. Empty means the built-in design.
        self._template_input = self._file_row(
            options_form, "deck.template_label", "deck.template_placeholder",
            "deck.template_dialog_title", "PowerPoint (*.pptx *.potx);;All files (*)",
        )
        self._template_config_input = self._file_row(
            options_form, "deck.template_config_label", "deck.template_config_placeholder",
            "deck.template_config_dialog_title", "Config (*.toml *.json);;All files (*)",
        )
        adapt_form_rows(options_card, options_form)
        controls_layout.addWidget(options_card)
        controls_layout.addStretch(1)

        # Action row, pinned below the cards
        footer = QWidget(self)
        button_row = QHBoxLayout(footer)
        button_row.setContentsMargins(0, 0, 6, 0)
        self._export_button = QPushButton(t("deck.export_button", language), self)
        self._export_button.setProperty("primary", True)
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._on_export_clicked)
        self._open_folder_button = QPushButton(t("deck.open_folder_button", language), self)
        self._open_folder_button.setEnabled(False)
        self._open_folder_button.clicked.connect(self._on_open_folder_clicked)
        button_row.addWidget(self._export_button, stretch=1)
        button_row.addWidget(self._open_folder_button)

        # Written files
        results = QWidget(self)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(6, 0, 0, 0)
        self._table = QTableView(self)
        self._table.setModel(self._files_model)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setEditTriggers(QTableView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        results_layout.addWidget(self._table, stretch=1)

        self._status_label = QLabel(t("deck.status_no_collection", language), self)
        self._status_label.setObjectName("Muted")
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        results_layout.addWidget(self._status_label)

        self._split = AdaptiveSplit(controls, results, footer=footer, parent=self)
        outer.addWidget(self._split)

    def apply_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Re-arrange for the window size class (called by the main window)."""
        self._split.apply_breakpoint(breakpoint)

    def split(self) -> AdaptiveSplit:
        return self._split

    def format_grid(self) -> ReflowGrid:
        return self._format_grid

    # --- public API -----------------------------------------------------

    def set_collection(self, collection: object) -> None:
        if collection is None or not isinstance(collection, PaperCollection):
            self._collection = None
            self._collection_is_enriched = False
            self._export_button.setEnabled(False)
            self._status_label.setText(
                t("deck.status_no_collection", self._ui_language),
            )
            return
        self._collection = collection
        # Heuristic: when any paper has a populated summary, the
        # collection has been through EnrichPage. Surface the distinction
        # because the user wants to know whether the exported deck will
        # be lightweight or thesis-style before clicking Export.
        self._collection_is_enriched = any(
            p.summary is not None for p in collection.papers
        )
        self._export_button.setEnabled(bool(collection.papers))
        status_key = (
            "deck.status_ready_enriched"
            if self._collection_is_enriched
            else "deck.status_ready_raw"
        )
        self._status_label.setText(
            t(status_key, self._ui_language, count=len(collection.papers)),
        )

    def collection(self) -> PaperCollection | None:
        return self._collection

    def status_text(self) -> str:
        return self._status_label.text()

    def files_model(self) -> QStandardItemModel:
        return self._files_model

    def format_checkbox(self, fmt: str) -> QCheckBox:
        return self._format_checks[fmt]

    def verify_identifiers_checkbox(self) -> QCheckBox:
        return self._verify_identifiers_check

    def set_library_path(self, path: str) -> None:
        """Use the library file named on the Search tab as the identifier cache.

        Connected to ``SearchPage.library_path_changed``. With a path set, an
        export keeps its DOI / URL verdicts in that library, so identifiers
        verified by an earlier export are not checked again. Empty switches
        it off.
        """
        self._library_path = path.strip()

    def set_template_path(self, path: str) -> None:
        self._template_input.setText(path)

    def set_template_config_path(self, path: str) -> None:
        self._template_config_input.setText(path)

    # --- internals ------------------------------------------------------

    def _file_row(
        self, form: QFormLayout, label_key: str, placeholder_key: str,
        dialog_title_key: str, file_filter: str,
    ) -> QLineEdit:
        """Add a "path + Browse" row to ``form`` and return its line edit."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(self)
        field.setPlaceholderText(t(placeholder_key, self._ui_language))
        browse = QPushButton(t("deck.browse_button", self._ui_language), self)

        def choose() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, t(dialog_title_key, self._ui_language),
                field.text() or str(Path.cwd()), file_filter,
            )
            if path:
                field.setText(path)

        browse.clicked.connect(choose)
        layout.addWidget(field, stretch=1)
        layout.addWidget(browse)
        form.addRow(t(label_key, self._ui_language), row)
        return field

    def _on_browse_out_dir(self) -> None:
        start = self._out_dir_input.text() or str(Path.cwd())
        path = QFileDialog.getExistingDirectory(
            self, t("deck.out_dir_dialog_title", self._ui_language), start,
        )
        if path:
            self._out_dir_input.setText(path)

    def _selected_formats(self) -> tuple[str, ...]:
        return tuple(
            fmt for fmt, _label in _FORMAT_CHOICES
            if self._format_checks[fmt].isChecked()
        )

    def _on_export_clicked(self) -> None:
        if self._collection is None or not self._collection.papers:
            self._status_label.setText(
                t("deck.error_no_collection", self._ui_language),
            )
            return
        formats = self._selected_formats()
        if not formats:
            self._status_label.setText(
                t("deck.error_no_formats", self._ui_language),
            )
            return
        out_dir = self._out_dir_input.text().strip()
        if not out_dir:
            self._status_label.setText(
                t("deck.error_no_out_dir", self._ui_language),
            )
            return
        stem = self._filename_stem_input.text().strip() or None
        language = self._language_combo.currentData() or "en"
        try:
            options = ExportOptions(
                formats=formats,
                out_dir=out_dir,
                filename_stem=stem,
                include_abstract=self._include_abstract_check.isChecked(),
                language=language,
                max_slides_per_paper=self._max_slides_spin.value(),
                dark_mode=self._dark_mode_check.isChecked(),
                verify_identifiers=self._verify_identifiers_check.isChecked(),
                pptx_template=self._template_input.text().strip() or None,
                pptx_template_config=self._template_config_input.text().strip() or None,
            )
        except ValueError as err:
            # A template config with no template: say so here, the options
            # object refuses the combination before any worker starts.
            self._on_export_failed(err)
            return
        collection = self._collection
        self._export_button.setEnabled(False)
        self._open_folder_button.setEnabled(False)
        self._files_model.removeRows(0, self._files_model.rowCount())
        self._status_label.setText(t("deck.status_running", self._ui_language))
        self.busy_changed.emit(True)

        library_path = self._library_path

        def call() -> dict[str, Path]:
            if not library_path:
                return export_collection(collection, options)
            with Library(library_path) as library:
                return export_collection(
                    collection, options, verification_cache=library.verification_cache()
                )

        worker = BlockingWorker(call)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.failed.connect(self._on_export_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_export_finished(self, written: object) -> None:
        self.busy_changed.emit(False)
        self._export_button.setEnabled(True)
        if not isinstance(written, dict) or not written:
            self._status_label.setText(
                t("deck.error_no_output", self._ui_language),
            )
            return
        any_path: Path | None = None
        for fmt, path in written.items():
            self._files_model.appendRow([
                QStandardItem(fmt),
                QStandardItem(str(path)),
            ])
            any_path = path
        if any_path is not None:
            self._last_written_dir = any_path.parent
            self._open_folder_button.setEnabled(True)
        self._status_label.setText(
            t("deck.status_done", self._ui_language, count=len(written)),
        )

    def _on_export_failed(self, err: object) -> None:
        self.busy_changed.emit(False)
        self._export_button.setEnabled(True)
        self._status_label.setText(
            t("deck.error_generic", self._ui_language, error=str(err)),
        )

    def _on_open_folder_clicked(self) -> None:
        if self._last_written_dir is None:
            return
        # QDesktopServices is the cross-platform "open in file manager"
        # — Windows Explorer, macOS Finder, xdg-open on Linux. Subprocess
        # would be more controllable but also leaks the host OS into the
        # GUI layer; this is the right abstraction.
        url = QUrl.fromLocalFile(str(self._last_written_dir))
        QDesktopServices.openUrl(url)


