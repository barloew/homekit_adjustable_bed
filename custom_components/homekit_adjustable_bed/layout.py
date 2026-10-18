"""Predict how the Home app lays out the controls of the bed tile.

Observed on a paired Jensen bed (Barloew's bed, 4 sliders + 2 switches):

    Hoofdeinde   | Bed vlak
    Hoofdmassage | Memory 1
    Voeteinde    | Voetmassage

Hoofdeinde was the primary service; the other five are exactly alphabetical
and mixed across types (sliders and switches interleave). So the rule is:
the primary service first, then all other controls sorted by name, filled
into rows of two. HAP offers no other ordering hook for these services
(DisplayOrder only exists for TV inputs), and creation order (iid) is ignored.

The integration therefore lets you pick the primary control and shows this
preview, so captions can be chosen that produce the wanted grid.
"""

from __future__ import annotations

import unicodedata


def sort_key(label: str) -> str:
    """Approximate Apple's localized, case- and accent-insensitive compare."""
    decomposed = unicodedata.normalize("NFKD", label)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def predicted_order(
    controls: list[tuple[str, str]], primary_key: str | None
) -> list[tuple[str, str]]:
    """Return (key, label) in the order the Home app is expected to show."""
    primary = [c for c in controls if c[0] == primary_key]
    rest = sorted((c for c in controls if c[0] != primary_key), key=lambda c: sort_key(c[1]))
    return primary + rest


def preview_markdown(controls: list[tuple[str, str]], primary_key: str | None) -> str:
    """Render the expected tile as a two-column markdown table."""
    order = [label for _, label in predicted_order(controls, primary_key)]
    if not order:
        return "-"
    rows = ["| | |", "|---|---|"]
    for i in range(0, len(order), 2):
        left = order[i]
        right = order[i + 1] if i + 1 < len(order) else ""
        rows.append(f"| {left} | {right} |")
    return "\n".join(rows)


def homekit_name(label: str, fallback: str) -> str:
    """Make a caption valid for HomeKit.

    HomeKit names may only contain letters, digits, spaces and apostrophes and
    must start and end with a letter or digit ("aan/uit" is rejected by iOS).
    """
    cleaned = "".join(c if c.isalnum() or c in " '" else " " for c in label)
    cleaned = " ".join(cleaned.split())
    while cleaned and not cleaned[0].isalnum():
        cleaned = cleaned[1:]
    while cleaned and not cleaned[-1].isalnum():
        cleaned = cleaned[:-1]
    return cleaned or fallback
