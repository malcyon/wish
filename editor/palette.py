"""The sixteen colours a C64 has, and no others."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from por.icons import C64_COLOURS, C64_PALETTE

COLOURS = [QColor(h) for h in C64_PALETTE]
NAMES = list(C64_COLOURS)


def colour(index: int) -> QColor:
    return COLOURS[index & 0x0F]


def name(index: int) -> str:
    return NAMES[index & 0x0F]
