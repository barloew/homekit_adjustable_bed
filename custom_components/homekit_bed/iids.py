"""Stable HomeKit instance IDs (IIDs) across restarts and config changes.

The Home app identifies every service and characteristic of an accessory by
its IID. pyhap's default manager simply counts in creation order, so adding a
control (or a colour characteristic) in the middle shifts the IIDs of every
later control: the Home app then sees "new" controls and forgets their
names, scenes and automations. Like the HA HomeKit Bridge (HomeIIDManager),
we remember each IID under a stable key and give new objects the next free
number.

Upgrade path: on the first start without a stored map the counter runs in
creation order, which reproduces the IIDs of earlier versions exactly, as
long as new characteristics are appended after all existing ones (see
BedAccessory.add_late_char).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pyhap.characteristic import Characteristic
from pyhap.iid_manager import IIDManager

_LOGGER = logging.getLogger(__name__)


def _key(obj: Any) -> str:
    if isinstance(obj, Characteristic):
        service = obj.service
        if service is None:
            return f"|{obj.type_id}"
        return f"{service.type_id}|{service.unique_id}|{obj.type_id}"
    return f"{obj.type_id}|{obj.unique_id}"


class StableIIDManager(IIDManager):
    """IID manager backed by a {key: iid} map."""

    def __init__(self, stored: dict[str, int]) -> None:
        super().__init__()
        self.map: dict[str, int] = dict(stored)
        self.counter = max(self.map.values(), default=0)
        self.changed = False

    def get_iid_for_obj(self, obj: Any) -> int:
        key = _key(obj)
        iid = self.map.get(key)
        if iid is None or iid in self.objs:
            self.counter += 1
            iid = self.counter
            self.map[key] = iid
            self.changed = True
        return iid


def load_iids(path: str) -> dict[str, int]:
    """Read the stored map (executor)."""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        return {str(k): int(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        _LOGGER.warning("Ignoring unreadable IID map %s: %s", path, err)
        return {}


def save_iids(path: str, mapping: dict[str, int]) -> None:
    """Write the map atomically (executor)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(mapping, file, indent=1, sort_keys=True)
    os.replace(tmp, path)
