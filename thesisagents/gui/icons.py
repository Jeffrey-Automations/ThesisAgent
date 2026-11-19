"""Line icons for the sidebar, drawn with ``QPainter`` at runtime.

Why they are painted rather than loaded from SVG files: an SVG icon needs
Qt's ``qsvg`` image-format plugin at runtime, and whether a packager
(Nuitka's ``pyside6`` plugin, PyInstaller hooks) bundles it is a build
detail this module should not depend on. A missing plugin would show blank
sidebar buttons with no error. Painted icons also take their colour from the
current theme, which a fixed SVG file cannot.

Every icon is drawn on a 24-unit grid with round caps, so the set reads as
one family at any size.

Example::

    icon = nav_icon("search", normal="#B7C4DB", active="#FFFFFF")
    button.setIcon(icon)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: Icon edge in device-independent pixels. Pixmaps are drawn at twice the
#: size so they stay sharp on a 200 % display.
ICON_SIZE: Final[int] = 20
_SCALE: Final[int] = 2
_GRID: Final[float] = 24.0


def _search(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    painter.drawLine(QPointF(15.5, 15.5), QPointF(20.5, 20.5))


def _enrich(painter: QPainter) -> None:
    # A four-point sparkle plus a small one: "add intelligence".
    path = QPainterPath(QPointF(10, 3))
    path.quadTo(QPointF(11, 9), QPointF(17, 10))
    path.quadTo(QPointF(11, 11), QPointF(10, 17))
    path.quadTo(QPointF(9, 11), QPointF(3, 10))
    path.quadTo(QPointF(9, 9), QPointF(10, 3))
    painter.drawPath(path)
    painter.drawLine(QPointF(18, 15), QPointF(18, 21))
    painter.drawLine(QPointF(15, 18), QPointF(21, 18))


def _deck(painter: QPainter) -> None:
    painter.drawRoundedRect(QRectF(3, 4, 18, 12), 2, 2)
    painter.drawLine(QPointF(12, 16), QPointF(12, 20))
    painter.drawLine(QPointF(8, 20.5), QPointF(16, 20.5))
    painter.drawLine(QPointF(7, 8.5), QPointF(13, 8.5))
    painter.drawLine(QPointF(7, 12), QPointF(16, 12))


def _library(painter: QPainter) -> None:
    # Three book spines on a shelf, the last one leaning.
    painter.drawRect(QRectF(4, 5, 3.5, 14))
    painter.drawRect(QRectF(9, 3, 3.5, 16))
    path = QPainterPath(QPointF(15, 6.5))
    path.lineTo(QPointF(18.4, 5.6))
    path.lineTo(QPointF(21, 18.2))
    path.lineTo(QPointF(17.6, 19))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(3, 21), QPointF(21, 21))


def _settings(painter: QPainter) -> None:
    # Three sliders: reads as "preferences" and stays legible at 16 px,
    # where a gear's teeth blur together.
    for y, knob in ((6.0, 15.0), (12.0, 8.0), (18.0, 13.0)):
        painter.drawLine(QPointF(3, y), QPointF(21, y))
        painter.drawEllipse(QPointF(knob, y), 2.2, 2.2)


def _menu(painter: QPainter) -> None:
    for y in (7.0, 12.0, 17.0):
        painter.drawLine(QPointF(4, y), QPointF(20, y))


def _check(painter: QPainter) -> None:
    path = QPainterPath(QPointF(5, 12.5))
    path.lineTo(QPointF(10, 17.5))
    path.lineTo(QPointF(19, 7))
    painter.drawPath(path)


def _chevron_down(painter: QPainter) -> None:
    path = QPainterPath(QPointF(6, 9))
    path.lineTo(QPointF(12, 15))
    path.lineTo(QPointF(18, 9))
    painter.drawPath(path)


def _chevron_up(painter: QPainter) -> None:
    path = QPainterPath(QPointF(6, 15))
    path.lineTo(QPointF(12, 9))
    path.lineTo(QPointF(18, 15))
    painter.drawPath(path)


_PAINTERS: Final[dict[str, Callable[[QPainter], None]]] = {
    "search": _search,
    "library": _library,
    "enrich": _enrich,
    "deck": _deck,
    "settings": _settings,
    "menu": _menu,
}
#: The icon names :func:`nav_icon` accepts.
ICON_NAMES: Final[tuple[str, ...]] = tuple(_PAINTERS)
#: Glyphs the stylesheet references as image files (check-box tick, combo and
#: spin-box arrows). Styling those sub-controls in QSS removes the native
#: glyph, so the theme draws its own in the palette's colours.
_GLYPHS: Final[dict[str, Callable[[QPainter], None]]] = {
    "check": _check,
    "chevron_down": _chevron_down,
    "chevron_up": _chevron_up,
}


def _pixmap(
    name: str, colour: str, *, edge: int = ICON_SIZE * _SCALE, width: float = 1.8
) -> QPixmap:
    painter_fn = _PAINTERS.get(name) or _GLYPHS[name]
    pixmap = QPixmap(edge, edge)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(edge / _GRID, edge / _GRID)
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter_fn(painter)
    painter.end()
    pixmap.setDevicePixelRatio(_SCALE)
    return pixmap


def write_glyph(name: str, colour: str, path: str) -> None:
    """Save stylesheet glyph ``name`` in ``colour`` as a PNG at ``path``.

    Drawn at 32 px with a heavier stroke; the stylesheet scales it into a
    14-16 px sub-control. Raises ``KeyError`` for an unknown glyph.
    """
    if name not in _GLYPHS:
        raise KeyError(f"unknown glyph {name!r}; known: {', '.join(_GLYPHS)}")
    pixmap = _pixmap(name, colour, edge=32, width=3.0)
    pixmap.setDevicePixelRatio(1)
    if not pixmap.save(path, "PNG"):
        raise OSError(f"could not write {path}")


def nav_icon(name: str, normal: str, active: str) -> QIcon:
    """An icon drawn in ``normal`` colour, and in ``active`` when checked.

    A checkable ``QToolButton`` shows the ``On`` state while checked, so the
    selected sidebar entry brightens with no extra code. Raises ``KeyError``
    for a name outside :data:`ICON_NAMES`, a programming error.
    """
    if name not in _PAINTERS:
        raise KeyError(f"unknown icon {name!r}; known: {', '.join(ICON_NAMES)}")
    icon = QIcon()
    icon.addPixmap(_pixmap(name, normal), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_pixmap(name, active), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_pixmap(name, active), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(_pixmap(name, active), QIcon.Mode.Active, QIcon.State.On)
    return icon
