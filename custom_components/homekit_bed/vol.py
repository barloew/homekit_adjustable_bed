"""Schema library of the running Home Assistant.

Home Assistant 2026.10 replaced voluptuous with probatio (``import voluptuous`` then returns
probatio). Importing it from here keeps the types right for both, and the integration working
on 2026.9.
"""

from __future__ import annotations

try:
    import probatio as vol  # Home Assistant 2026.10+
except ImportError:  # pragma: no cover - Home Assistant 2026.9
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
