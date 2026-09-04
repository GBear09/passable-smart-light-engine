"""Storage manager for Passable Adaptive Smart Lighting Controller learning data."""

import copy
import json
import logging
import os
import pathlib
from typing import Any, Callable, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    LEGACY_DATA_PATHS,
    RESET_TYPES,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

EMPTY_DATA: Dict[str, Any] = {
    "user_prefs": {},
    "room_curves": {},
    "media_prefs": {},
    "late_night_prefs": {},
}


class LearningDataStore:
    """Manages asynchronous persistence and legacy migration for lighting learning data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage helper."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: Dict[str, Any] = copy.deepcopy(EMPTY_DATA)
        self._update_listeners: List[Callable[[], None]] = []

    @property
    def data(self) -> Dict[str, Any]:
        """Return the in-memory learning data snapshot."""
        return self._data

    def register_update_listener(self, listener: Callable[[], None]) -> None:
        """Register a callback when learning data changes."""
        if listener not in self._update_listeners:
            self._update_listeners.append(listener)

    def _notify_listeners(self) -> None:
        """Notify registered listeners of updated learning data."""
        for listener in self._update_listeners:
            try:
                listener()
            except Exception as err:
                _LOGGER.error("Error notifying learning data listener: %s", err)

    async def async_load(self) -> None:
        """Load data from Home Assistant storage, with fallback to legacy JSON files."""
        stored = await self._store.async_load()

        if stored and isinstance(stored, dict):
            self._data = {
                "user_prefs": stored.get("user_prefs", {}),
                "room_curves": stored.get("room_curves", {}),
                "media_prefs": stored.get("media_prefs", {}),
                "late_night_prefs": stored.get("late_night_prefs", {}),
            }
            _LOGGER.info(
                "PassableSmartLighting: Loaded learning data from HA storage. (Rooms: %s)",
                sorted(list(self.get_active_rooms())),
            )
            self._notify_listeners()
            return

        # Attempt legacy migration if storage was empty
        migrated = await self._async_migrate_legacy_data()
        if migrated:
            await self.async_save()
            _LOGGER.info(
                "PassableSmartLighting: Migrated legacy learning data into HA storage."
            )
        else:
            self._data = copy.deepcopy(EMPTY_DATA)
            _LOGGER.info("PassableSmartLighting: Initialized empty learning data store.")

        self._notify_listeners()

    async def _async_migrate_legacy_data(self) -> bool:
        """Inspect known legacy pyscript paths for an existing learning_data.json."""

        def _load_file_sync(path_str: str) -> Optional[Dict[str, Any]]:
            path = pathlib.Path(path_str)
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data
                except Exception as err:
                    _LOGGER.warning("Could not read legacy learning data from %s: %s", path_str, err)
            return None

        for path_str in LEGACY_DATA_PATHS:
            data = await self.hass.async_add_executor_job(_load_file_sync, path_str)
            if data:
                self._data = {
                    "user_prefs": data.get("user_prefs", {}),
                    "room_curves": data.get("room_curves", {}),
                    "media_prefs": data.get("media_prefs", {}),
                    "late_night_prefs": data.get("late_night_prefs", {}),
                }
                _LOGGER.info("PassableSmartLighting: Found legacy data at %s", path_str)
                return True

        return False

    def _data_to_save(self) -> Dict[str, Any]:
        """Return data snapshot for storage persistence."""
        return copy.deepcopy(self._data)

    def schedule_save(self, delay: float = 30.0) -> None:
        """Schedule atomic delayed persistence to eliminate flash write amplification."""
        self._store.async_delay_save(self._data_to_save, delay=delay)
        self._notify_listeners()

    async def async_save(self) -> None:
        """Persist current in-memory learning data to HA storage immediately."""
        try:
            snapshot = copy.deepcopy(self._data)
            await self._store.async_save(snapshot)
            self._notify_listeners()
        except Exception as err:
            _LOGGER.error("PassableSmartLighting: Failed to save learning data to storage: %s", err)

    def get_room_datasets(self) -> Dict[str, List[str]]:
        """Return a mapping of room_id to non-empty dataset categories."""
        room_datasets: Dict[str, List[str]] = {}
        for category_key, category_dict in self._data.items():
            if isinstance(category_dict, dict):
                for rid, data in category_dict.items():
                    if data:
                        if rid not in room_datasets:
                            room_datasets[rid] = []
                        room_datasets[rid].append(category_key)
        return room_datasets

    def get_active_rooms(self) -> List[str]:
        """Return a sorted list of room IDs with stored learning data."""
        return sorted(list(self.get_room_datasets().keys()))

    async def async_reset(self, room_id: Optional[str] = None, reset_type: str = "all") -> None:
        """Reset learned data for a room or all rooms."""
        targets = (
            [reset_type]
            if reset_type != "all" and reset_type in RESET_TYPES
            else ["user_prefs", "room_curves", "media_prefs", "late_night_prefs"]
        )

        if not room_id:
            _LOGGER.warning("PassableSmartLighting: Resetting ALL rooms (%s)", reset_type)
            for key in targets:
                if key in self._data:
                    for rid in list(self._data[key].keys()):
                        self._data[key][rid] = [] if "prefs" in key else {}
            await self.async_save()
            return

        for key in targets:
            if key in self._data and room_id in self._data[key]:
                self._data[key][room_id] = [] if "prefs" in key else {}
                _LOGGER.info("PassableSmartLighting [%s]: Reset dataset %s", room_id, key)

        await self.async_save()
        _LOGGER.info("PassableSmartLighting [%s]: Reset complete (%s)", room_id, reset_type)
