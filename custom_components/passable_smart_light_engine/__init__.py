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
    ACTIVE_HOLIDAY_SENSOR_UNIQUE_ID,
    ATTR_CALIBRATE_FORCE,
    ATTR_CALIBRATE_ROOM_ID,
    ATTR_DURATION_SEC,
    ATTR_HOLIDAY_NAME,
    ATTR_OVERRIDE_ROOM_ID,
    ATTR_RESET_ROOM_ID,
    ATTR_RESET_TYPE,
    CONF_SIMULATION_ARRIVAL_GRACE_MIN,
    CONF_SIMULATION_ENABLED,
    CONF_SIMULATION_JITTER_MIN,
    CONF_SIMULATION_LABEL,
    CONF_SIMULATION_LOOKBACK_DAYS,
    CONF_SIMULATION_MAX_BRIGHTNESS_PCT,
    CONF_SIMULATION_MODE,
    DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
    DEFAULT_SIMULATION_ENABLED,
    DEFAULT_SIMULATION_JITTER_MIN,
    DEFAULT_SIMULATION_LABEL,
    DEFAULT_SIMULATION_LOOKBACK_DAYS,
    DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
    DEFAULT_SIMULATION_MODE,
    DOMAIN,
    EVENT_PASSABLE_SMART_LIGHT_ENGINE,
    EVENT_SMART_LIGHT_ENGINE,
    EXTERIOR_LIGHTING_SWITCH_ENTITY_ID,
    EXTERIOR_LIGHTING_SWITCH_UNIQUE_ID,
    FRONTEND_URL_PATH,
    HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
    HOLIDAY_DECORATIONS_SWITCH_UNIQUE_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_UNIQUE_ID,
    LEGACY_DOMAIN,
    PLATFORMS,
    PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID,
    PRESENCE_SIMULATION_MASTER_SWITCH_UNIQUE_ID,
    PRESENCE_SIMULATION_SWITCH_ENTITY_ID,
    PRESENCE_SIMULATION_SWITCH_UNIQUE_ID,
    RESET_TYPES,
    SERVICE_APPLY_HOLIDAY_LIGHTING,
    SERVICE_CALIBRATE_ROOM_CURVE,
    SERVICE_CLEAR_MANUAL_OVERRIDE,
    SERVICE_PREVIEW_HOLIDAY,
    SERVICE_RESET_LEARNING_DATA,
    SERVICE_START_PRESENCE_SIMULATION,
    SERVICE_STOP_PRESENCE_SIMULATION,
    SUMMARY_SENSOR_ENTITY_ID,
    SUMMARY_SENSOR_UNIQUE_ID,
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
        return str(data.get("version", "2.9.3"))
    except Exception:
        return "2.9.3"


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

    # Ensure a single unified general system entry holds all system devices & entities
    async def _async_ensure_system_entry() -> None:
        all_entries = list(hass.config_entries.async_entries(DOMAIN))
        system_entries = [
            e for e in all_entries if e.data.get("entry_type") == "system"
        ]
        legacy_entries = [
            e
            for e in all_entries
            if e.data.get("entry_type") in ("presence_simulation", "holiday_lighting")
        ]

        sim_defaults: Dict[str, Any] = {
            CONF_SIMULATION_ENABLED: DEFAULT_SIMULATION_ENABLED,
            CONF_SIMULATION_LABEL: DEFAULT_SIMULATION_LABEL,
            CONF_SIMULATION_MODE: DEFAULT_SIMULATION_MODE,
            CONF_SIMULATION_LOOKBACK_DAYS: DEFAULT_SIMULATION_LOOKBACK_DAYS,
            CONF_SIMULATION_JITTER_MIN: DEFAULT_SIMULATION_JITTER_MIN,
            CONF_SIMULATION_ARRIVAL_GRACE_MIN: DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
            CONF_SIMULATION_MAX_BRIGHTNESS_PCT: DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
        }
        for src in system_entries + [
            e for e in legacy_entries if e.data.get("entry_type") == "presence_simulation"
        ]:
            for key in list(sim_defaults):
                if key in src.data:
                    sim_defaults[key] = src.data[key]
            break

        promoted = False
        system_entry: Optional[ConfigEntry] = system_entries[0] if system_entries else None

        if system_entry is None:
            if legacy_entries:
                sim_first = [
                    e for e in legacy_entries if e.data.get("entry_type") == "presence_simulation"
                ]
                primary = sim_first[0] if sim_first else legacy_entries[0]
                _LOGGER.info(
                    "PassableSmartLighting: Consolidating legacy entry '%s' (%s) into unified 'Passable Smart Light Engine' system entry",
                    primary.title,
                    primary.entry_id,
                )
                hass.data.setdefault(DOMAIN, {}).setdefault(
                    "skip_reload_entries", set()
                ).add(primary.entry_id)
                hass.config_entries.async_update_entry(
                    primary,
                    title="Passable Smart Light Engine",
                    unique_id=f"{DOMAIN}_system",
                    data={"entry_type": "system", **sim_defaults},
                )
                system_entry = primary
                promoted = True
            else:
                _LOGGER.info(
                    "PassableSmartLighting: Auto-creating unified Passable Smart Light Engine system entry..."
                )
                await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data={"entry_type": "system", **sim_defaults},
                )
                refreshed = [
                    e
                    for e in hass.config_entries.async_entries(DOMAIN)
                    if e.data.get("entry_type") == "system"
                ]
                if refreshed:
                    await _async_migrate_system_registries(hass, refreshed[0].entry_id)
                return

        redundant_entries = [
            e
            for e in (legacy_entries + system_entries[1:])
            if e.entry_id != system_entry.entry_id
        ]

        if not promoted and not redundant_entries:
            await _async_migrate_system_registries(hass, system_entry.entry_id)
            return

        await _async_migrate_system_registries(hass, system_entry.entry_id)

        for old_entry in redundant_entries:
            _LOGGER.info(
                "PassableSmartLighting: Removing consolidated legacy entry '%s' (%s)",
                old_entry.title,
                old_entry.entry_id,
            )
            await hass.config_entries.async_remove(old_entry.entry_id)

        await _async_migrate_system_registries(hass, system_entry.entry_id)
        await hass.config_entries.async_reload(system_entry.entry_id)

    hass.async_create_task(_async_ensure_system_entry())

    _LOGGER.info("Passable Smart Light Engine component initialized successfully.")
    return True


async def _async_migrate_system_registries(
    hass: HomeAssistant, system_entry_id: str
) -> None:
    """Attach all system entities and system devices exclusively to the unified system entry."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    system_targets = [
        ("sensor", SUMMARY_SENSOR_UNIQUE_ID, SUMMARY_SENSOR_ENTITY_ID),
        ("sensor", f"{DOMAIN}_ready", "sensor.passable_smart_light_engine_ready"),
        (
            "sensor",
            f"{DOMAIN}_presence_simulation_status",
            "sensor.presence_simulation_status",
        ),
        ("sensor", ACTIVE_HOLIDAY_SENSOR_UNIQUE_ID, ACTIVE_HOLIDAY_SENSOR_ENTITY_ID),
        (
            "switch",
            PRESENCE_SIMULATION_MASTER_SWITCH_UNIQUE_ID,
            PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID,
        ),
        (
            "switch",
            PRESENCE_SIMULATION_SWITCH_UNIQUE_ID,
            PRESENCE_SIMULATION_SWITCH_ENTITY_ID,
        ),
        (
            "switch",
            HOLIDAY_LIGHTING_MASTER_SWITCH_UNIQUE_ID,
            HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
        ),
        (
            "switch",
            HOLIDAY_DECORATIONS_SWITCH_UNIQUE_ID,
            HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
        ),
        (
            "switch",
            EXTERIOR_LIGHTING_SWITCH_UNIQUE_ID,
            EXTERIOR_LIGHTING_SWITCH_ENTITY_ID,
        ),
    ]

    migrated_device_ids = set()
    for platform_domain, unique_id, fallback_entity_id in system_targets:
        entity_id: Optional[str] = None
        if hasattr(ent_reg, "async_get_entity_id"):
            entity_id = ent_reg.async_get_entity_id(platform_domain, DOMAIN, unique_id)
        if not entity_id and fallback_entity_id and ent_reg.async_get(fallback_entity_id):
            entity_id = fallback_entity_id
        if not entity_id:
            for reg_ent in getattr(ent_reg, "entities", {}).values():
                if (
                    getattr(reg_ent, "platform", None) == DOMAIN
                    and getattr(reg_ent, "domain", None) == platform_domain
                    and getattr(reg_ent, "unique_id", None) == unique_id
                ):
                    entity_id = reg_ent.entity_id
                    break
        if not entity_id:
            continue

        reg_entry = ent_reg.async_get(entity_id)
        if not reg_entry:
            continue
        if reg_entry.device_id:
            migrated_device_ids.add(reg_entry.device_id)
        if reg_entry.config_entry_id != system_entry_id:
            _LOGGER.info(
                "PassableSmartLighting: Migrating entity %s from entry %s to system entry %s",
                entity_id,
                reg_entry.config_entry_id,
                system_entry_id,
            )
            ent_reg.async_update_entity(entity_id, config_entry_id=system_entry_id)

    for ident_key in ("system_hub", "presence_simulation", "holiday_lighting"):
        device = None
        if hasattr(dev_reg, "async_get_device"):
            device = dev_reg.async_get_device(identifiers={(DOMAIN, ident_key)})
        if not device:
            for dev in getattr(dev_reg, "devices", {}).values():
                if (DOMAIN, ident_key) in getattr(dev, "identifiers", set()):
                    device = dev
                    break
        if device:
            migrated_device_ids.add(device.id)

    for dev_id in migrated_device_ids:
        device = dev_reg.async_get(dev_id)
        if not device:
            continue
        config_entries = list(getattr(device, "config_entries", ()))
        if system_entry_id not in config_entries:
            dev_reg.async_update_device(dev_id, add_config_entry_id=system_entry_id)
        for old_cid in [cid for cid in config_entries if cid != system_entry_id]:
            _LOGGER.info(
                "PassableSmartLighting: Detaching device %s from non-system entry %s",
                dev_id,
                old_cid,
            )
            dev_reg.async_update_device(dev_id, remove_config_entry_id=old_cid)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a room, unified system entry, or legacy subsystem from a config entry."""
    await _async_register_frontend(hass)
    async_register_websocket_commands(hass)

    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]

    if entry.data.get("entry_type") == "system":
        if entry.title != "Passable Smart Light Engine":
            data.setdefault("skip_reload_entries", set()).add(entry.entry_id)
            hass.config_entries.async_update_entry(
                entry, title="Passable Smart Light Engine"
            )

        coordinator = data.get("coordinator")
        if coordinator:
            coordinator.update_options(dict(entry.data))

        holiday_coord: Optional[HolidayLightingCoordinator] = data.get(
            "holiday_coordinator"
        )
        if holiday_coord:
            await holiday_coord.async_start()

        await _async_migrate_system_registries(hass, entry.entry_id)
        await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor"])
        entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
        _LOGGER.info(
            "PassableSmartLighting: Set up unified Passable Smart Light Engine system entry successfully."
        )
        return True

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
    """Unload a room, unified system entry, or legacy subsystem config entry."""
    data = hass.data[DOMAIN]

    if entry.data.get("entry_type") == "system":
        coordinator = data.get("coordinator")
        if coordinator:
            coordinator.stop()
        holiday_coord = data.get("holiday_coordinator")
        if holiday_coord:
            holiday_coord.stop()
        data["system_simulation_sensor_registered"] = False
        data["system_sensor_registered"] = False
        data["system_switch_registered"] = False
        data["system_sensor_entry_id"] = None
        return await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor"])

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
