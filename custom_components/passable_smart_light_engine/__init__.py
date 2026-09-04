"""Passable AI Smart Lighting Controller integration setup."""

import asyncio
import logging
import os
import pathlib
import shutil
from typing import Any, Dict

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_RESET_ROOM_ID,
    ATTR_RESET_TYPE,
    DOMAIN,
    EVENT_PASSABLE_SMART_LIGHT_ENGINE,
    EVENT_SMART_LIGHT_ENGINE,
    LEGACY_DOMAIN,
    PLATFORMS,
    RESET_TYPES,
    SERVICE_RESET_LEARNING_DATA,
)
from .engine import PassableLightingEngine, RoomController
from .storage import LearningDataStore

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

RESET_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RESET_ROOM_ID): cv.string,
        vol.Optional(ATTR_RESET_TYPE, default="all"): vol.In(RESET_TYPES),
    }
)


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the Passable AI Smart Lighting Controller integration."""
    hass.data.setdefault(DOMAIN, {})

    store = LearningDataStore(hass)
    await store.async_load()

    engine = PassableLightingEngine(hass, store)

    hass.data[DOMAIN] = {
        "store": store,
        "engine": engine,
        "controllers": {},
        "system_sensor_registered": False,
    }

    # ==============================================================
    # 1. BLUEPRINT EVENT BRIDGE (Backward Compatibility)
    # Allows existing blueprint automations to work seamlessly without Pyscript
    # ==============================================================
    async def _async_handle_blueprint_event(event: Event) -> None:
        """Handle incoming event fired by blueprint automations."""
        try:
            event_data = dict(event.data)
            _LOGGER.debug(
                "PassableSmartLighting: Received blueprint event '%s' for room '%s'",
                event.event_type,
                event_data.get("room_id"),
            )
            hass.async_create_task(engine.async_handle_engine_cycle(event_data))
        except Exception as err:
            _LOGGER.error("PassableSmartLighting: Error processing blueprint event: %s", err)

    hass.bus.async_listen(EVENT_SMART_LIGHT_ENGINE, _async_handle_blueprint_event)
    hass.bus.async_listen(EVENT_PASSABLE_SMART_LIGHT_ENGINE, _async_handle_blueprint_event)

    # ==============================================================
    # 2. DATA RESET SERVICES
    # ==============================================================
    async def _async_handle_reset_service(call: ServiceCall) -> None:
        """Reset learned lighting curves and user preferences."""
        room_id = call.data.get(ATTR_RESET_ROOM_ID)
        reset_type = call.data.get(ATTR_RESET_TYPE, "all")
        await store.async_reset(room_id, reset_type)

    hass.services.async_register(
        DOMAIN, SERVICE_RESET_LEARNING_DATA, _async_handle_reset_service, schema=RESET_SERVICE_SCHEMA
    )

    # Register legacy domain alias for existing dashboards/scripts
    if not hass.services.has_service(LEGACY_DOMAIN, SERVICE_RESET_LEARNING_DATA):
        hass.services.async_register(
            LEGACY_DOMAIN, SERVICE_RESET_LEARNING_DATA, _async_handle_reset_service, schema=RESET_SERVICE_SCHEMA
        )

    # ==============================================================
    # 3. AUTO-BUNDLE BLUEPRINT (Optional helper)
    # Automatically ensures blueprint is available in HA blueprints directory
    # ==============================================================
    await hass.async_add_executor_job(_copy_bundled_blueprint, hass)

    _LOGGER.info("Passable AI Smart Lighting Controller component initialized successfully.")
    return True


def _copy_bundled_blueprint(hass: HomeAssistant) -> None:
    """Safely copy bundled blueprint to Home Assistant blueprints folder if present."""
    try:
        source = pathlib.Path(__file__).parent.parent.parent / "blueprints" / "automation" / "gbear09" / "passable_smart_light_engine.yaml"
        target_dir = pathlib.Path(hass.config.path("blueprints", "automation", "gbear09"))
        target_file = target_dir / "passable_smart_light_engine.yaml"

        if source.is_file() and not target_file.is_file():
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_file)
            _LOGGER.info("PassableSmartLighting: Copied bundled blueprint to %s", target_file)
    except Exception as err:
        _LOGGER.debug("Could not copy bundled blueprint (normal during headless or testing): %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a room from a config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]

    controller = RoomController(hass, engine, dict(entry.data))
    data["controllers"][entry.entry_id] = controller
    engine.register_controller(controller.room_id, controller)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await controller.async_start()

    entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
    _LOGGER.info("PassableSmartLighting: Set up room '%s' successfully.", controller.room_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a room config entry."""
    data = hass.data[DOMAIN]
    controller: RoomController = data["controllers"].pop(entry.entry_id, None)

    if controller:
        controller.stop()
        engine: PassableLightingEngine = data["engine"]
        engine.unregister_controller(controller.room_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok


async def async_update_options_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
