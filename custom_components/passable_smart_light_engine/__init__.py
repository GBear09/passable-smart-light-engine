"""Passable Smart Light Engine integration setup."""

import asyncio
import json
import logging
import os
import pathlib
import shutil
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .const import (
    ACTIVE_HOLIDAY_SENSOR_ENTITY_ID,
    ATTR_CALIBRATE_FORCE,
    ATTR_CALIBRATE_ROOM_ID,
    ATTR_DURATION_SEC,
    ATTR_HOLIDAY_NAME,
    ATTR_OVERRIDE_ROOM_ID,
    ATTR_RESET_ROOM_ID,
    ATTR_RESET_TYPE,
    DOMAIN,
    EVENT_PASSABLE_SMART_LIGHT_ENGINE,
    EVENT_SMART_LIGHT_ENGINE,
    FRONTEND_URL_PATH,
    HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
    LEGACY_DOMAIN,
    PLATFORMS,
    PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID,
    PRESENCE_SIMULATION_SWITCH_ENTITY_ID,
    RESET_TYPES,
    SERVICE_APPLY_HOLIDAY_LIGHTING,
    SERVICE_CALIBRATE_ROOM_CURVE,
    SERVICE_CLEAR_MANUAL_OVERRIDE,
    SERVICE_PREVIEW_HOLIDAY,
    SERVICE_RESET_LEARNING_DATA,
    SERVICE_START_PRESENCE_SIMULATION,
    SERVICE_STOP_PRESENCE_SIMULATION,
)
from .engine import PassableLightingEngine, RoomController
from .holiday_lighting import HolidayLightingCoordinator, HolidayStore
from .presence_simulation import PresenceSimulationCoordinator
from .storage import LearningDataStore
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

RESET_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_RESET_ROOM_ID): cv.string,
        vol.Optional(ATTR_RESET_TYPE, default="all"): vol.In(RESET_TYPES),
    }
)

CALIBRATE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CALIBRATE_ROOM_ID): cv.string,
        vol.Optional(ATTR_CALIBRATE_FORCE, default=False): cv.boolean,
    }
)

APPLY_HOLIDAY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_HOLIDAY_NAME): cv.string,
    }
)

PREVIEW_HOLIDAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_HOLIDAY_NAME): cv.string,
        vol.Optional(ATTR_DURATION_SEC, default=60): cv.positive_int,
    }
)

CLEAR_OVERRIDE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_OVERRIDE_ROOM_ID): vol.Any(cv.string, None),
    }
)


def _get_integration_version() -> str:
    """Read integration version from manifest.json."""
    try:
        manifest_path = pathlib.Path(__file__).parent / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(data.get("version", "2.9.0"))
    except Exception:
        return "2.9.0"


async def _async_register_lovelace_resource(
    hass: HomeAssistant, version: str
) -> None:
    """Register or version-bump the bundled card as a Lovelace module resource."""
    try:
        lovelace = hass.data.get("lovelace")
        if not lovelace:
            domain_data = hass.data.setdefault(DOMAIN, {})
            if not domain_data.get("lovelace_listener_scheduled"):
                domain_data["lovelace_listener_scheduled"] = True

                @callback
                def _on_started(_event: Event) -> None:
                    hass.async_create_task(
                        _async_register_lovelace_resource(hass, version)
                    )

                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
            return

        resources = getattr(lovelace, "resources", None)
        if not resources or not hasattr(resources, "async_create_item"):
            return

        if not resources.loaded:
            await resources.async_load()

        url_path = f"{FRONTEND_URL_PATH}?v={version}"
        for resource in resources.async_items():
            existing_url = str(resource.get("url", ""))
            if existing_url.startswith(FRONTEND_URL_PATH):
                if (
                    existing_url != url_path
                    and resource.get("id") is not None
                    and hasattr(resources, "async_update_item")
                ):
                    await resources.async_update_item(
                        resource["id"], {"res_type": "module", "url": url_path}
                    )
                    _LOGGER.info(
                        "Updated Lovelace resource for cache busting: %s", url_path
                    )
                return

        await resources.async_create_item(
            {"res_type": "module", "url": url_path}
        )
        _LOGGER.info("Automatically registered Lovelace resource: %s", url_path)
    except Exception as err:
        _LOGGER.debug(
            "Could not automatically register Lovelace resource: %s", err
        )


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register static frontend path and Lovelace resource for the bundled lighting card."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    card_path = pathlib.Path(__file__).parent / "frontend" / "passable-lighting-card.js"
    if not await hass.async_add_executor_job(card_path.is_file):
        _LOGGER.warning("Passable Lighting Card file not found at %s", card_path)
        return

    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_PATH, str(card_path), cache_headers=False)]
        )
        domain_data["frontend_registered"] = True
        _LOGGER.info("Passable Lighting Card registered at %s", FRONTEND_URL_PATH)
    except Exception:
        try:
            hass.http.register_static_path(
                FRONTEND_URL_PATH, str(card_path), cache_headers=False
            )
            domain_data["frontend_registered"] = True
            _LOGGER.info(
                "Passable Lighting Card registered at %s (legacy)", FRONTEND_URL_PATH
            )
        except Exception as legacy_err:
            _LOGGER.error("Failed to register static path: %s", legacy_err)
            return

    version = await hass.async_add_executor_job(_get_integration_version)
    domain_data["version"] = version
    hass.async_create_task(_async_register_lovelace_resource(hass, version))



async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the Passable Adaptive Smart Lighting Controller integration."""
    hass.data.setdefault(DOMAIN, {})

    store = LearningDataStore(hass)
    await store.async_load()

    holiday_store = HolidayStore(hass)
    await holiday_store.async_load()

    engine = PassableLightingEngine(hass, store)
    await engine.async_start()

    coordinator = PresenceSimulationCoordinator(hass, engine)
    engine.presence_simulation = coordinator

    holiday_coordinator = HolidayLightingCoordinator(hass, engine, holiday_store)
    engine.holiday_lighting = holiday_coordinator

    @callback
    def _on_hass_stop(_event: Event) -> None:
        engine.stop()
        coordinator.stop()
        holiday_coordinator.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_hass_stop)

    hass.data[DOMAIN] = {
        "store": store,
        "holiday_store": holiday_store,
        "engine": engine,
        "coordinator": coordinator,
        "holiday_coordinator": holiday_coordinator,
        "controllers": {},
        "skip_reload_entries": set(),
        "system_sensor_registered": False,
        "system_switch_registered": False,
    }

    await _async_register_frontend(hass)
    async_register_websocket_commands(hass)

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
    # 2. DATA RESET & CALIBRATION SERVICES
    # ==============================================================
    async def _async_handle_reset_service(call: ServiceCall) -> None:
        """Reset learned lighting curves and user preferences."""
        room_id = call.data.get(ATTR_RESET_ROOM_ID)
        reset_type = call.data.get(ATTR_RESET_TYPE, "all")
        await store.async_reset(room_id, reset_type)

    hass.services.async_register(
        DOMAIN, SERVICE_RESET_LEARNING_DATA, _async_handle_reset_service, schema=RESET_SERVICE_SCHEMA
    )

    async def _async_handle_calibrate_service(call: ServiceCall) -> None:
        """Calibrate yield curve for a room across test brightness levels."""
        room_id = call.data[ATTR_CALIBRATE_ROOM_ID]
        force = call.data.get(ATTR_CALIBRATE_FORCE, False)
        hass.async_create_task(engine.async_calibrate_room_curve(room_id, force=force))

    hass.services.async_register(
        DOMAIN, SERVICE_CALIBRATE_ROOM_CURVE, _async_handle_calibrate_service, schema=CALIBRATE_SERVICE_SCHEMA
    )

    async def _async_handle_start_simulation(call: ServiceCall) -> None:
        """Start presence simulation."""
        await coordinator.async_start()

    hass.services.async_register(DOMAIN, SERVICE_START_PRESENCE_SIMULATION, _async_handle_start_simulation)

    async def _async_handle_stop_simulation(call: ServiceCall) -> None:
        """Stop presence simulation."""
        await coordinator.async_stop()

    hass.services.async_register(DOMAIN, SERVICE_STOP_PRESENCE_SIMULATION, _async_handle_stop_simulation)

    async def _async_handle_apply_holiday(call: ServiceCall) -> None:
        """Manually trigger or test holiday lighting."""
        h_name = call.data.get(ATTR_HOLIDAY_NAME)
        holiday_obj = None
        if h_name:
            for h in holiday_store.holidays.values():
                if h["name"].lower() == h_name.lower() or h["id"].lower() == h_name.lower():
                    holiday_obj = h
                    break
        await holiday_coordinator.async_turn_on_holiday_lighting(preview_holiday=holiday_obj)

    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_HOLIDAY_LIGHTING, _async_handle_apply_holiday, schema=APPLY_HOLIDAY_SCHEMA
    )

    async def _async_handle_preview_holiday(call: ServiceCall) -> None:
        """Preview a holiday configuration for a set duration."""
        h_name = call.data[ATTR_HOLIDAY_NAME]
        dur = call.data.get(ATTR_DURATION_SEC, 60)
        h_id = None
        for hid, h in holiday_store.holidays.items():
            if h["name"].lower() == h_name.lower() or hid.lower() == h_name.lower():
                h_id = hid
                break
        if h_id:
            await holiday_coordinator.async_preview_holiday(h_id, duration_sec=dur)
        else:
            _LOGGER.warning("PassableSmartLighting: Holiday '%s' not found for preview.", h_name)

    hass.services.async_register(
        DOMAIN, SERVICE_PREVIEW_HOLIDAY, _async_handle_preview_holiday, schema=PREVIEW_HOLIDAY_SCHEMA
    )

    async def _async_handle_clear_manual_override(call: ServiceCall) -> None:
        """Clear manual override for a specific room or all rooms."""
        room_id = call.data.get(ATTR_OVERRIDE_ROOM_ID)
        await engine.async_clear_manual_override(room_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_MANUAL_OVERRIDE,
        _async_handle_clear_manual_override,
        schema=CLEAR_OVERRIDE_SERVICE_SCHEMA,
    )

    # Ensure dedicated presence simulation entry is created
    async def _async_ensure_simulation_entry() -> None:
        sim_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.data.get("entry_type") == "presence_simulation"
        ]
        if not sim_entries:
            _LOGGER.info("PassableSmartLighting: Auto-creating dedicated Presence Simulation config entry...")
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={"entry_type": "presence_simulation"},
            )

    hass.async_create_task(_async_ensure_simulation_entry())

    # Ensure dedicated holiday lighting entry is created
    async def _async_ensure_holiday_entry() -> None:
        h_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.data.get("entry_type") == "holiday_lighting"
        ]
        if not h_entries:
            _LOGGER.info("PassableSmartLighting: Auto-creating dedicated Holiday & Exterior Lighting config entry...")
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={"entry_type": "holiday_lighting"},
            )

    hass.async_create_task(_async_ensure_holiday_entry())

    _LOGGER.info("Passable Smart Light Engine component initialized successfully.")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a room, presence simulation, or holiday lighting from a config entry."""
    await _async_register_frontend(hass)
    async_register_websocket_commands(hass)

    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]

    if entry.data.get("entry_type") == "presence_simulation":
        coordinator = data.get("coordinator")
        if coordinator:
            coordinator.update_options(dict(entry.data))

        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        for entity_id in [
            PRESENCE_SIMULATION_SWITCH_ENTITY_ID,
            PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID,
            "sensor.presence_simulation_status",
        ]:
            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry and reg_entry.config_entry_id != entry.entry_id:
                old_entry_id = reg_entry.config_entry_id
                _LOGGER.info(
                    "PassableSmartLighting: Migrating %s from config entry %s to dedicated entry %s",
                    entity_id,
                    old_entry_id,
                    entry.entry_id,
                )
                ent_reg.async_update_entity(entity_id, config_entry_id=entry.entry_id)
                if reg_entry.device_id:
                    device = dev_reg.async_get(reg_entry.device_id)
                    if device and old_entry_id in device.config_entries:
                        dev_reg.async_update_device(
                            device.id,
                            add_config_entry_id=entry.entry_id,
                            remove_config_entry_id=old_entry_id,
                        )

        await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor"])
        entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
        _LOGGER.info("PassableSmartLighting: Set up Presence Simulation entry successfully.")
        return True

    if entry.data.get("entry_type") == "holiday_lighting":
        if entry.title != "Holiday & Exterior Lighting":
            _LOGGER.info(
                "PassableSmartLighting: Updating config entry title from '%s' to 'Holiday & Exterior Lighting'",
                entry.title,
            )
            data.setdefault("skip_reload_entries", set()).add(entry.entry_id)
            hass.config_entries.async_update_entry(entry, title="Holiday & Exterior Lighting")

        holiday_coord: Optional[HolidayLightingCoordinator] = data.get("holiday_coordinator")
        if holiday_coord:
            await holiday_coord.async_start()

        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        for entity_id in [
            HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
            HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
            ACTIVE_HOLIDAY_SENSOR_ENTITY_ID,
        ]:
            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry and reg_entry.config_entry_id != entry.entry_id:
                old_entry_id = reg_entry.config_entry_id
                _LOGGER.info(
                    "PassableSmartLighting: Migrating %s from config entry %s to dedicated entry %s",
                    entity_id,
                    old_entry_id,
                    entry.entry_id,
                )
                ent_reg.async_update_entity(entity_id, config_entry_id=entry.entry_id)
                if reg_entry.device_id:
                    device = dev_reg.async_get(reg_entry.device_id)
                    if device and old_entry_id in device.config_entries:
                        dev_reg.async_update_device(
                            device.id,
                            add_config_entry_id=entry.entry_id,
                            remove_config_entry_id=old_entry_id,
                        )

        await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor"])
        entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
        _LOGGER.info("PassableSmartLighting: Set up Holiday & Exterior Lighting entry successfully.")
        return True

    controller = RoomController(hass, engine, dict(entry.data))
    data["controllers"][entry.entry_id] = controller
    engine.register_controller(controller.room_id, controller)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await controller.async_start()

    entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
    _LOGGER.info("PassableSmartLighting: Set up room '%s' successfully.", controller.room_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a room, presence simulation, or holiday lighting config entry."""
    data = hass.data[DOMAIN]

    if entry.data.get("entry_type") == "presence_simulation":
        coordinator = data.get("coordinator")
        if coordinator:
            coordinator.stop()
        data["system_simulation_sensor_registered"] = False
        data["system_switch_registered"] = False
        return await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor"])

    if entry.data.get("entry_type") == "holiday_lighting":
        holiday_coord = data.get("holiday_coordinator")
        if holiday_coord:
            holiday_coord.stop()
        return await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor"])


    controller: RoomController = data["controllers"].pop(entry.entry_id, None)

    if controller:
        controller.stop()
        engine: PassableLightingEngine = data["engine"]
        engine.unregister_controller(controller.room_id)

    if data.get("system_sensor_entry_id") == entry.entry_id:
        data["system_sensor_registered"] = False
        data["system_sensor_entry_id"] = None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok


async def async_update_options_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated, unless marked for in-memory skip."""
    skip_set = hass.data.get(DOMAIN, {}).get("skip_reload_entries")
    if isinstance(skip_set, set) and entry.entry_id in skip_set:
        skip_set.discard(entry.entry_id)
        return
    await hass.config_entries.async_reload(entry.entry_id)
