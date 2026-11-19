"""Light / dark design tokens and the application stylesheet.

The boundary this module guards: every colour the desktop UI paints comes
from one :class:`Palette`, so a page never hard-codes a hex value that
would be unreadable in the other theme. Before this module the window used
the platform's default widgets with no stylesheet, which on Windows looked
like a 2010 dialog and ignored the system's dark mode entirely.

Three theme choices exist, stored under the QSettings key ``ui/theme``:

* ``"system"`` (the default) follows the operating system's colour scheme
  and keeps following it when the user flips it while the app is open.
* ``"light"`` and ``"dark"`` pin one palette.

The GUI theme is independent of the slide-deck dark mode (the Deck page's
*Dark mode* checkbox): one is how the app looks, the other how the exported
``.pptx`` looks.

Example::

    from thesisagents.gui.theme import apply_theme
    apply_theme(app, "system")   # once at boot, again whenever Settings saves
"""

from __future__ import annotations

import atexit
import functools
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from thesisagents.gui.icons import write_glyph

THEME_SYSTEM: Final[str] = "system"
THEME_LIGHT: Final[str] = "light"
THEME_DARK: Final[str] = "dark"
#: Every valid value of the ``ui/theme`` setting, in the order the Settings
#: page lists them.
THEME_CHOICES: Final[tuple[str, ...]] = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)


@dataclass(frozen=True)
class Palette:
    """The colour tokens one theme is built from, as ``#RRGGBB`` strings.

    ``window`` is the page background, ``surface`` the card fill drawn on it,
    ``nav`` the sidebar. ``accent`` is the primary-button and selection colour
    (the deck's ``_BRAND_HIGHLIGHT`` blue in light mode, its dark-mode swap
    ``#60A5FA`` in dark mode, so the app and its decks share one accent).
    ``muted`` is secondary text (subtitles, placeholders, status lines).
    """

    name: str
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    on_accent: str
    nav: str
    nav_text: str
    nav_muted: str
    nav_active: str
    selection: str


LIGHT: Final[Palette] = Palette(
    name=THEME_LIGHT,
    window="#F4F6FA",
    surface="#FFFFFF",
    surface_alt="#F8FAFC",
    border="#DDE3EC",
    text="#0F172A",
    muted="#5B6678",
    accent="#2563EB",
    accent_hover="#1D4ED8",
    on_accent="#FFFFFF",
    # The deck's navy (_BRAND_DARK #1F3A66), so the sidebar and the
    # exported cover share one identity colour.
    nav="#1F3A66",
    nav_text="#FFFFFF",
    nav_muted="#B7C4DB",
    nav_active="#2E4F85",
    selection="#DBE7FE",
)

DARK: Final[Palette] = Palette(
    name=THEME_DARK,
    window="#12151B",
    surface="#1A1E26",
    surface_alt="#151920",
    border="#2C3340",
    text="#E5E7EB",
    muted="#9AA3B2",
    accent="#60A5FA",
    accent_hover="#93C5FD",
    on_accent="#0B1220",
    nav="#0C0F14",
    nav_text="#E5E7EB",
    nav_muted="#8B95A7",
    nav_active="#1E2633",
    selection="#1E3A5F",
)


def resolve_theme(choice: str, system_is_dark: bool) -> Palette:
    """Map a ``ui/theme`` value to the palette to paint with.

    An unknown value (an old or hand-edited setting) is treated as
    ``"system"`` rather than raising, so a bad registry entry cannot stop the
    app from starting.

    >>> resolve_theme("system", system_is_dark=True).name
    'dark'
    >>> resolve_theme("light", system_is_dark=True).name
    'light'
    """
    if choice == THEME_LIGHT:
        return LIGHT
    if choice == THEME_DARK:
        return DARK
    return DARK if system_is_dark else LIGHT


def system_prefers_dark() -> bool:
    """Whether the OS colour scheme is dark (Qt 6.5+ ``styleHints``).

    Returns ``False`` without a ``QGuiApplication`` or when the platform
    reports ``Unknown`` (older Linux desktops), so the light theme is the
    fallback.
    """
    app = QGuiApplication.instance()
    if app is None:
        return False
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def build_palette(tokens: Palette) -> QPalette:
    """A ``QPalette`` matching ``tokens``.

    The stylesheet does not restyle check boxes, radio buttons or the
    combo / spin arrows (styling them in QSS drops the native glyphs), so the
    Fusion style paints those from this palette instead. Without it a dark
    theme would draw black check marks on a dark card.
    """
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.window,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.surface,
        QPalette.ColorRole.AlternateBase: tokens.surface_alt,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.surface,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.Highlight: tokens.accent,
        QPalette.ColorRole.HighlightedText: tokens.on_accent,
        QPalette.ColorRole.ToolTipBase: tokens.surface,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.muted,
        QPalette.ColorRole.Link: tokens.accent,
        QPalette.ColorRole.Mid: tokens.border,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    disabled = QColor(tokens.muted)
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return palette


@functools.lru_cache(maxsize=1)
def _asset_dir() -> Path:
    """A private per-process directory for the stylesheet's glyph images.

    ``mkdtemp`` creates it readable by this user only, so no other account
    can swap the images, and it is removed when the process exits.
    """
    path = Path(tempfile.mkdtemp(prefix="thesisagents-gui-"))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def write_theme_assets(tokens: Palette) -> dict[str, str]:
    """Draw the check-box tick and the arrow glyphs for ``tokens``.

    Returns ``{"check": path, "down": path, "up": path}`` with forward-slash
    paths, the form a stylesheet ``url(...)`` accepts on every platform.
    Each theme's files are drawn once per process.
    """
    specs = {
        "check": ("check", tokens.on_accent),
        "down": ("chevron_down", tokens.muted),
        "up": ("chevron_up", tokens.muted),
    }
    assets: dict[str, str] = {}
    for key, (glyph, colour) in specs.items():
        path = _asset_dir() / f"{tokens.name}-{key}.png"
        if not path.is_file():
            write_glyph(glyph, colour, str(path))
        assets[key] = path.as_posix()
    return assets


def _glyph_rules(p: Palette, assets: dict[str, str]) -> str:
    """Check-box, combo-box and spin-box sub-controls drawn with ``assets``."""
    return f"""
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.muted};
    border-radius: 4px;
    background: {p.surface};
}}
QCheckBox::indicator:hover {{
    border-color: {p.accent};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: url({assets["check"]});
}}
QCheckBox::indicator:disabled {{
    background: {p.surface_alt};
    border-color: {p.border};
}}
QComboBox {{
    padding-right: 28px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url({assets["down"]});
    width: 12px;
    height: 12px;
}}
QSpinBox {{
    padding-right: 26px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 24px;
    border: none;
    border-left: 1px solid {p.border};
    background: transparent;
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 6px;
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 6px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {p.surface_alt};
}}
QSpinBox::up-arrow {{
    image: url({assets["up"]});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow {{
    image: url({assets["down"]});
    width: 10px;
    height: 10px;
}}
"""


def build_stylesheet(tokens: Palette, assets: dict[str, str] | None = None) -> str:
    """The application-wide Qt stylesheet for ``tokens``.

    Widgets opt into the special looks with object names and dynamic
    properties rather than per-widget stylesheets, so one string themes the
    whole window and a theme switch is a single ``setStyleSheet`` call:

    * ``QPushButton[primary="true"]``: the one main action of a page.
    * ``#NavRail`` / ``#NavButton``: the sidebar.
    * ``#Card``: a rounded panel (``QFrame``) grouping one form section.
    * ``#PageTitle`` / ``#PageSubtitle`` / ``#CardTitle`` / ``#Muted``: type.

    ``assets`` (from :func:`write_theme_assets`) adds the check-box and arrow
    rules. Without it those controls keep the Fusion style's own drawing,
    which is what tests that only inspect the text use.
    """
    p = tokens
    glyphs = _glyph_rules(p, assets) if assets else ""
    return glyphs + f"""
QWidget {{
    color: {p.text};
}}
QMainWindow, QStackedWidget, #PageBody, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {p.window};
}}
QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 6px 8px;
    border-radius: 6px;
}}

/* Sidebar ---------------------------------------------------------- */
#NavRail {{
    background: {p.nav};
}}
#NavRail QLabel#NavBrand {{
    color: {p.nav_text};
    font-weight: 700;
    padding: 4px 6px;
}}
#NavRail QLabel#NavTagline {{
    color: {p.nav_muted};
    padding: 0 6px;
}}
#NavButton {{
    background: transparent;
    color: {p.nav_muted};
    border: none;
    border-radius: 8px;
    padding: 9px 10px;
    text-align: left;
}}
#NavButton:hover {{
    background: {p.nav_active};
    color: {p.nav_text};
}}
#NavButton:checked {{
    background: {p.nav_active};
    color: {p.nav_text};
    font-weight: 600;
}}

/* Page chrome ------------------------------------------------------ */
#PageHeader {{
    background: {p.window};
}}
QLabel#PageTitle {{
    font-size: 18pt;
    font-weight: 700;
}}
QLabel#PageSubtitle, QLabel#Muted {{
    color: {p.muted};
}}
QLabel#CardTitle {{
    font-weight: 700;
}}
#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
#Card QLabel, #Card QCheckBox {{
    background: transparent;
}}

/* Inputs ----------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 20px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {p.accent};
}}
QLineEdit:read-only {{
    background: {p.surface_alt};
}}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}

/* Buttons ---------------------------------------------------------- */
QPushButton {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    border-color: {p.accent};
}}
QPushButton:disabled {{
    color: {p.muted};
    background: {p.surface_alt};
}}
QPushButton[primary="true"] {{
    background: {p.accent};
    color: {p.on_accent};
    border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton[primary="true"]:disabled {{
    background: {p.border};
    border-color: {p.border};
    color: {p.muted};
}}

/* Tables ----------------------------------------------------------- */
QTableView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 8px;
    gridline-color: {p.border};
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {p.surface_alt};
    border: none;
}}

/* Status bar, progress, splitter, scroll bars ---------------------- */
QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.muted};
}}
QProgressBar {{
    background: {p.border};
    border: none;
    border-radius: 3px;
    max-height: 6px;
}}
QProgressBar::chunk {{
    background: {p.accent};
    border-radius: 3px;
}}
QSplitter::handle {{
    background: {p.window};
}}
QSplitter::handle:hover {{
    background: {p.border};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle {{
    background: {p.border};
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:hover {{
    background: {p.muted};
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
    width: 0;
    height: 0;
}}
"""


def apply_theme(app: QApplication, choice: str) -> Palette:
    """Paint ``app`` with the theme ``choice`` and return the palette used.

    Switches the style to Fusion first: the native Windows style ignores
    most palette roles, so a dark palette on it gives dark text on dark
    buttons. Safe to call again at any time (Settings does on save, and the
    system-scheme listener does when the OS flips between light and dark).
    """
    tokens = resolve_theme(choice, system_prefers_dark())
    app.setStyle("Fusion")
    app.setPalette(build_palette(tokens))
    app.setStyleSheet(build_stylesheet(tokens, write_theme_assets(tokens)))
    app.setProperty("thesisagents_theme", tokens.name)
    return tokens


def current_palette() -> Palette:
    """The palette last applied by :func:`apply_theme` (light before that).

    Widgets that paint their own pixels (the sidebar icons) read it so their
    colours follow a theme switch.
    """
    app = QApplication.instance()
    name = app.property("thesisagents_theme") if app is not None else None
    return DARK if name == THEME_DARK else LIGHT
