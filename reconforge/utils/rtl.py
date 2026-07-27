"""Arabic/RTL Localization and BIDI Formatting Utilities.

Provides BIDI directionality checks, Arabic text normalization,
and RTL HTML wrapper attributes for international financial UI rendering.
"""

from __future__ import annotations

import re
from typing import Literal

_ARABIC_CHAR_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def contains_arabic_text(text: str) -> bool:
    """Return True if string contains Arabic characters."""

    return bool(_ARABIC_CHAR_PATTERN.search(text))


def detect_direction(text: str) -> Literal["rtl", "ltr"]:
    """Detect text directionality based on dominant character script."""

    return "rtl" if contains_arabic_text(text) else "ltr"


def format_rtl_html_attributes(text: str) -> str:
    """Return HTML attribute string dir='rtl' lang='ar' if Arabic text detected."""

    if contains_arabic_text(text):
        return 'dir="rtl" lang="ar"'
    return 'dir="ltr" lang="en"'


def normalize_arabic_numbers(text: str) -> str:
    """Normalize Eastern Arabic digits (٠١٢٣٤٥٦٧٨٩) to Western digits (0123456789)."""

    eastern_to_western = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return text.translate(eastern_to_western)
