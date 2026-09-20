"""Shared page-level presentation helpers."""

import logging

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

DISCLAIMER = "This is a research measurement tool and is not a medical diagnostic or treatment device."
LOGGER = logging.getLogger("amble.ui")


def heading(title: str, subtitle: str = "") -> tuple[QVBoxLayout, QWidget]:
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(24, 20, 24, 20)
    label = QLabel(title)
    label.setObjectName("PageTitle")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return layout, root


__all__ = ["DISCLAIMER", "LOGGER", "heading"]
