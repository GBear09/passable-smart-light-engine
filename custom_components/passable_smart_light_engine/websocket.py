"""WebSocket API handlers for Passable Smart Light Engine."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from homeassistant.components import recorder, websocket_api
from homeassistant.components.recorder import history
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
import homeassistant.util.dt as dt_util
import voluptuous as vol

from .const import (
    CONF_CIRCADIAN_ENABLED,
    CONF_DEFAULT_LUX_RATIO,
    CONF_LATE_NIGHT_LEARN_PREFS,
    CONF_LIGHT_ENTITY,
    CONF_LUX_SENSOR,
    CONF_MAX_COLOR_TEMP,
    CONF_MEDIA_LEARN_PREFS,
    CONF_MIN_COLOR_TEMP,
    CONF_OVERRIDE_TIMEOUT_MIN,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_SECONDARY_LIGHTS,
    CONF_TARGET_LUX,
    CONF_TIMEOUT_SCALE_ENTITIES,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_LATE_NIGHT_LEARN_PREFS,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LUX_RATIO,
    DEFAULT_MAX_COLOR_TEMP,
    DEFAULT_MEDIA_LEARN_PREFS,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_OVERRIDE_TIMEOUT_MIN,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_SECONDARY_LIGHTS,
    DEFAULT_TARGET_LUX,
    DEFAULT_TIMEOUT_SCALE_ENTITIES,
    DOMAIN,
    RESET_TYPES,
)
from .engine import (
    PassableLightingEngine,
    RoomController,
    calculate_learned_target_lux,
    compute_engine_summary,
    compute_room_active_mode,
    get_expected_lux,
    get_light_members,
)

_LOGGER = logging.getLogger(__name__)


def _resolve_entity_id(
    ent_reg: Any, platform: str, unique_id: str
) -> Optional[str]:
    """Resolve an entity ID from the entity registry by platform and unique ID."""
    if not ent_reg:
        return None
    try:
        resolved = ent_reg.async_get_entity_id(platform, DOMAIN, unique_id)
        if resolved:
            return resolved
    except Exception:
        pass
    for entry in getattr(ent_reg, "entities", {}).values():
        if (
            getattr(entry, "platform", None) == DOMAIN
            and getattr(entry, "domain", None) == platform
            and getattr(entry, "unique_id", None) == unique_id
        ):
            return entry.entity_id
    return None


def _find_controller_and_entry(
    hass: HomeAssistant, room_id: str
) -> Tuple[Optional[str], Optional[RoomController]]:
    """Locate (entry_id, RoomController) matching room_id."""
    data = hass.data.get(DOMAIN, {})
    controllers = data.get("controllers", {})
    for entry_id, ctrl in controllers.items():
        if ctrl.room_id == room_id:
            return entry_id, ctrl
    engine: Optional[PassableLightingEngine] = data.get("engine")
    if engine and room_id in engine.controllers:
        return None, engine.controllers[room_id]
    return None, None


def _serialize_holiday(holiday: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Serialize a holiday catalog entry into a concise JSON-safe dict."""
    if not holiday:
        return None
    return {
        "id": holiday.get("id"),
        "name": holiday.get("name"),
        "enabled": bool(holiday.get("enabled", True)),
        "start_date": holiday.get("start_date", ""),
        "end_date": holiday.get("end_date", ""),
        "icon": holiday.get("icon", "mdi:calendar-star"),
        "phrase": holiday.get("phrase", ""),
        "theme_color": holiday.get("theme_color", "#b45f06"),
        "light_mode": holiday.get("light_mode", "rgb"),
        "decorations_on": bool(holiday.get("decorations_on", True)),
    }


def _build_ha_hierarchy(hass: HomeAssistant) -> Dict[str, Any]:
    """Build Home Assistant floor/area/light hierarchy for fallback floor discovery."""
    try:
        floor_reg = fr.async_get(hass)
        area_reg = ar.async_get(hass)
        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        lights_by_area: Dict[str, List[str]] = {}
        for entity in getattr(ent_reg, "entities", {}).values():
            if getattr(entity, "domain", None) != "light":
                continue
            if getattr(entity, "disabled_by", None) is not None or getattr(entity, "disabled", False):
                continue
            area_id = getattr(entity, "area_id", None)
            if not area_id and getattr(entity, "device_id", None) and dev_reg:
                dev = dev_reg.async_get(entity.device_id)
                if dev:
                    area_id = getattr(dev, "area_id", None)
            if area_id:
                lights_by_area.setdefault(area_id, []).append(entity.entity_id)

        for area_lights in lights_by_area.values():
            area_lights.sort()

        floors_map: Dict[str, Dict[str, Any]] = {}
        raw_floors = list(getattr(floor_reg, "floors", {}).values()) if floor_reg else []
        raw_floors.sort(
            key=lambda f: (
                getattr(f, "level") if getattr(f, "level", None) is not None else 0,
                str(getattr(f, "name", "") or "").lower(),
            )
        )
        for f in raw_floors:
            floor_id = getattr(f, "floor_id", None) or getattr(f, "id", None)
            if not floor_id:
                continue
            floors_map[floor_id] = {
                "floor_id": floor_id,
                "name": getattr(f, "name", floor_id),
                "icon": getattr(f, "icon", None),
                "level": getattr(f, "level", None),
                "areas": [],
            }

        unassigned_areas: List[Dict[str, Any]] = []
        raw_areas = list(getattr(area_reg, "areas", {}).values()) if area_reg else []
        raw_areas.sort(key=lambda a: str(getattr(a, "name", "") or "").lower())

        for a in raw_areas:
            area_id = getattr(a, "id", None) or getattr(a, "area_id", None)
            if not area_id:
                continue
            area_record = {
                "area_id": area_id,
                "name": getattr(a, "name", area_id),
                "lights": lights_by_area.get(area_id, []),
            }
            floor_id = getattr(a, "floor_id", None)
            if floor_id and floor_id in floors_map:
                floors_map[floor_id]["areas"].append(area_record)
            else:
                unassigned_areas.append(area_record)

        return {
            "floors": list(floors_map.values()),
            "unassigned_areas": unassigned_areas,
        }
    except Exception as err:
        _LOGGER.debug("PassableSmartLighting: Could not build HA hierarchy: %s", err)
        return {"floors": [], "unassigned_areas": []}


def build_engine_snapshot(hass: HomeAssistant) -> Dict[str, Any]:
    """Build complete JSON-serializable state snapshot for the frontend card."""
    data = hass.data.get(DOMAIN, {})
    engine: Optional[PassableLightingEngine] = data.get("engine")
    if not engine:
        return {
            "version": data.get("version") or "2.10.1",
            "summary": {},
            "rooms": [],
            "holiday_exterior": {},
            "presence_simulation": {},
            "ha_hierarchy": {"floors": [], "unassigned_areas": []},
        }

    store = engine.store
    learning_data = store.data
    room_datasets = store.get_room_datasets()
    controllers_by_entry: Dict[str, RoomController] = data.get("controllers", {})
    entry_id_by_room = {
        ctrl.room_id: entry_id for entry_id, ctrl in controllers_by_entry.items()
    }

    try:
        ent_reg = er.async_get(hass)
    except Exception:
        ent_reg = None

    sun_state = hass.states.get("sun.sun")
    elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
    azim = (
        float(sun_state.attributes.get("azimuth", 0))
        if sun_state and "azimuth" in sun_state.attributes
        else None
    )

    rooms_payload: List[Dict[str, Any]] = []
    for room_id, ctrl in sorted(
        engine.controllers.items(),
        key=lambda item: item[0].replace("_", " ").lower(),
    ):
        try:
            entry_data = ctrl.entry_data
            light_entity = entry_data.get(CONF_LIGHT_ENTITY)
            sec_lights = entry_data.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS) or []
            if isinstance(sec_lights, str):
                sec_lights = [sec_lights] if sec_lights else []
            else:
                sec_lights = [s for s in sec_lights if s]

            raw_leaves: List[str] = []
            if light_entity:
                raw_leaves.extend(get_light_members(hass, light_entity))
            for sec in sec_lights:
                raw_leaves.extend(get_light_members(hass, sec))
            leaf_lights = list(dict.fromkeys(raw_leaves))

            lux_sensor = entry_data.get(CONF_LUX_SENSOR)
            smoothed_lux = (
                engine.get_smoothed_lux_optional(room_id, lux_sensor)
                if lux_sensor
                else None
            )
            ambient_lux = round(smoothed_lux, 1) if smoothed_lux is not None else None

            seed_lux = float(entry_data.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX))
            user_prefs = learning_data.get("user_prefs", {}).get(room_id, [])
            blended_target_lux = round(
                calculate_learned_target_lux(seed_lux, user_prefs, elev, azim), 1
            )

            curves = learning_data.get("room_curves", {}).get(room_id, {})
            default_ratio = float(
                entry_data.get(CONF_DEFAULT_LUX_RATIO, DEFAULT_LUX_RATIO)
            )
            lux_yield = (
                round(get_expected_lux(curves, 50, default_ratio) / 50.0, 2)
                if curves
                else round(default_ratio, 2)
            )

            media_prefs = learning_data.get("media_prefs", {}).get(room_id, [])
            late_night_prefs = learning_data.get("late_night_prefs", {}).get(room_id, [])
            media_seed = int(entry_data.get("media_seed_pct", DEFAULT_MEDIA_SEED_PCT))
            late_night_seed = int(
                entry_data.get("late_night_pct", DEFAULT_LATE_NIGHT_PCT)
            )
            media_learn = bool(
                entry_data.get(CONF_MEDIA_LEARN_PREFS, DEFAULT_MEDIA_LEARN_PREFS)
            )
            late_night_learn = bool(
                entry_data.get(CONF_LATE_NIGHT_LEARN_PREFS, DEFAULT_LATE_NIGHT_LEARN_PREFS)
            )
            media_target_pct = (
                int(sum(media_prefs) / len(media_prefs))
                if media_learn and media_prefs
                else media_seed
            )
            late_night_target_pct = (
                int(sum(late_night_prefs) / len(late_night_prefs))
                if late_night_learn and late_night_prefs
                else late_night_seed
            )

            presence = entry_data.get(CONF_PRESENCE_ENTITIES, [])
            if isinstance(presence, str):
                presence = [presence] if presence else []
            is_occupied = engine.check_presence(presence)

            eff_timeout_min = engine.get_effective_presence_timeout_min(entry_data)
            vacancy_rem_sec = (
                round(ctrl.get_vacancy_remaining_sec(presence, eff_timeout_min * 60.0), 1)
                if ctrl.vacancy_cancel is not None
                else 0.0
            )

            scale_entities = entry_data.get(
                CONF_TIMEOUT_SCALE_ENTITIES, DEFAULT_TIMEOUT_SCALE_ENTITIES
            )
            if isinstance(scale_entities, str):
                scale_entities = [scale_entities] if scale_entities else []
            elif scale_entities is None:
                scale_entities = []

            rooms_payload.append(
                {
                    "room_id": room_id,
                    "name": room_id.replace("_", " ").title(),
                    "entry_id": entry_id_by_room.get(room_id),
                    "light_entity": light_entity,
                    "secondary_lights": sec_lights,
                    "leaf_lights": leaf_lights,
                    "lux_sensor": lux_sensor,
                    "ambient_lux": ambient_lux,
                    "seed_target_lux": int(round(seed_lux)),
                    "blended_target_lux": blended_target_lux,
                    "lux_yield": lux_yield,
                    "room_curves": dict(curves),
                    "curve_points_count": len(curves),
                    "user_prefs_count": len(user_prefs),
                    "active_mode": compute_room_active_mode(hass, engine, ctrl),
                    "is_enabled": ctrl.is_enabled,
                    "circadian_enabled": bool(
                        entry_data.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED)
                    ),
                    "min_color_temp": int(
                        entry_data.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP)
                    ),
                    "max_color_temp": int(
                        entry_data.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP)
                    ),
                    "is_occupied": is_occupied,
                    "override_active": engine.is_manual_override_active(room_id),
                    "override_remaining_sec": engine.get_override_remaining_sec(room_id),
                    "override_timeout_min": int(
                        entry_data.get(CONF_OVERRIDE_TIMEOUT_MIN, DEFAULT_OVERRIDE_TIMEOUT_MIN)
                    ),
                    "vacancy_remaining_sec": vacancy_rem_sec,
                    "freeze_bypass_active": ctrl.freeze_bypass_active,
                    "notification_enabled": ctrl.is_notification_enabled,
                    "notification_showing": ctrl.is_notification_showing,
                    "notification_pending": ctrl.is_notification_pending,
                    "notification_light_entity": ctrl.notification_light_entity,
                    "media_target_pct": media_target_pct,
                    "late_night_target_pct": late_night_target_pct,
                    "base_presence_timeout_min": int(
                        entry_data.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN)
                    ),
                    "effective_presence_timeout_min": eff_timeout_min,
                    "timeout_scaling_active": engine.is_timeout_scaling_active(
                        scale_entities
                    ),
                    "available_datasets": room_datasets.get(room_id, []),
                    "entities": {
                        "auto_switch": _resolve_entity_id(
                            ent_reg, "switch", f"{DOMAIN}_{room_id}_automation_switch"
                        ),
                        "circadian_switch": _resolve_entity_id(
                            ent_reg, "switch", f"{DOMAIN}_{room_id}_circadian_switch"
                        ),
                        "target_lux_number": _resolve_entity_id(
                            ent_reg, "number", f"{DOMAIN}_{room_id}_target_lux_number"
                        ),
                        "override_switch": _resolve_entity_id(
                            ent_reg, "switch", f"{DOMAIN}_{room_id}_manual_override_switch"
                        ),
                        "freeze_switch": _resolve_entity_id(
                            ent_reg, "switch", f"{DOMAIN}_{room_id}_freeze_switch"
                        ),
                        "active_mode_sensor": _resolve_entity_id(
                            ent_reg, "sensor", f"{DOMAIN}_{room_id}_active_mode"
                        ),
                    },
                }
            )
        except Exception as err:
            _LOGGER.debug("PassableSmartLighting: Skipping room '%s' in snapshot: %s", room_id, err)

    holiday_payload: Dict[str, Any] = {
        "holiday_enabled": False,
        "holiday_active_now": False,
        "decorations_enabled": False,
        "exterior_enabled": False,
        "exterior_active": False,
        "baseline_active": False,
        "active_holiday": None,
        "participating_lights": [],
        "participating_decorations": [],
        "exterior_lights": [],
        "active_lights": [],
        "active_decorations": [],
        "catalog": [],
    }
    holiday_coord = engine.holiday_lighting
    if holiday_coord:
        try:
            curr_holiday = holiday_coord.active_holiday
            catalog = [
                _serialize_holiday(h)
                for h in holiday_coord.store.holidays.values()
                if isinstance(h, dict)
            ]
            catalog.sort(key=lambda h: (h.get("start_date") or "99-99", h.get("name") or ""))
            holiday_payload = {
                "holiday_enabled": holiday_coord.enabled,
                "holiday_active_now": holiday_coord.is_holiday_active_now,
                "decorations_enabled": holiday_coord.decorations_enabled,
                "exterior_enabled": holiday_coord.exterior_enabled,
                "exterior_active": holiday_coord.is_exterior_active,
                "baseline_active": holiday_coord.is_baseline_active,
                "active_holiday": _serialize_holiday(curr_holiday),
                "participating_lights": holiday_coord.resolve_participating_lights(curr_holiday),
                "participating_decorations": holiday_coord.resolve_participating_decorations(curr_holiday),
                "exterior_lights": holiday_coord.resolve_exterior_lights(),
                "active_lights": holiday_coord.active_lights,
                "active_decorations": holiday_coord.active_decorations,
                "catalog": catalog,
            }
        except Exception as err:
            _LOGGER.debug("PassableSmartLighting: Could not serialize holiday state: %s", err)

    sim_payload: Dict[str, Any] = {
        "enabled": False,
        "is_on": False,
        "status": "idle",
        "mode": "hybrid",
        "label": "",
        "lookback_days": 7,
        "jitter_minutes": 15,
        "arrival_grace_minutes": 5,
        "next_event": None,
        "configured_lights": [],
        "active_simulated_lights": [],
    }
    sim_coord = engine.presence_simulation
    if sim_coord:
        try:
            sim_payload = {
                "enabled": sim_coord.enabled,
                "is_on": sim_coord.is_on,
                "status": sim_coord.status,
                "mode": sim_coord.mode,
                "label": sim_coord.label,
                "lookback_days": sim_coord.lookback_days,
                "jitter_minutes": sim_coord.jitter_min,
                "arrival_grace_minutes": sim_coord.arrival_grace_min,
                "next_event": sim_coord.next_event,
                "configured_lights": sim_coord.configured_target_entities,
                "active_simulated_lights": sim_coord.active_simulated_lights,
            }
        except Exception as err:
            _LOGGER.debug("PassableSmartLighting: Could not serialize simulation state: %s", err)

    try:
        summary_payload = compute_engine_summary(hass, engine)
    except Exception as err:
        _LOGGER.debug("PassableSmartLighting: Could not compute engine summary: %s", err)
        summary_payload = {}

    return {
        "version": data.get("version") or "2.10.1",
        "summary": summary_payload,
        "rooms": rooms_payload,
        "holiday_exterior": holiday_payload,
        "presence_simulation": sim_payload,
        "ha_hierarchy": _build_ha_hierarchy(hass),
    }


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands for frontend card interaction."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("websocket_registered"):
        return

    websocket_api.async_register_command(hass, ws_get_data)
    websocket_api.async_register_command(hass, ws_get_stats)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_clear_override)
    websocket_api.async_register_command(hass, ws_set_room_auto)
    websocket_api.async_register_command(hass, ws_set_room_circadian)
    websocket_api.async_register_command(hass, ws_set_target_lux)
    websocket_api.async_register_command(hass, ws_calibrate_room)
    websocket_api.async_register_command(hass, ws_reset_learning_data)
    websocket_api.async_register_command(hass, ws_preview_holiday)
    websocket_api.async_register_command(hass, ws_apply_holiday)
    domain_data["websocket_registered"] = True


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_data",
    }
)
@websocket_api.async_response
async def ws_get_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Return full smart light engine snapshot."""
    engine: Optional[PassableLightingEngine] = hass.data.get(DOMAIN, {}).get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return
    connection.send_result(msg["id"], build_engine_snapshot(hass))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/subscribe",
    }
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Subscribe to real-time debounced engine state snapshots."""
    data = hass.data.get(DOMAIN, {})
    engine: Optional[PassableLightingEngine] = data.get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    pending_handle: Optional[asyncio.TimerHandle] = None
    unsubs: List[Callable[[], None]] = []

    @callback
    def _push_now() -> None:
        nonlocal pending_handle
        pending_handle = None
        try:
            connection.send_message(
                websocket_api.event_message(msg["id"], build_engine_snapshot(hass))
            )
        except Exception as err:
            _LOGGER.debug("PassableSmartLighting: WS snapshot push failed: %s", err)

    @callback
    def _schedule_push() -> None:
        nonlocal pending_handle
        if pending_handle is not None:
            return
        pending_handle = hass.loop.call_later(0.15, _push_now)

    unsubs.append(engine.register_summary_listener(_schedule_push))
    unsubs.append(engine.store.register_update_listener(_schedule_push))
    holiday_coord = engine.holiday_lighting
    if holiday_coord and getattr(holiday_coord, "store", None):
        unsubs.append(holiday_coord.store.register_update_listener(_schedule_push))

    @callback
    def _cleanup() -> None:
        nonlocal pending_handle
        if pending_handle is not None:
            pending_handle.cancel()
            pending_handle = None
        for unsub in unsubs:
            try:
                unsub()
            except Exception:
                pass
        unsubs.clear()

    connection.subscriptions[msg["id"]] = _cleanup
    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(msg["id"], build_engine_snapshot(hass))
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/clear_override",
        vol.Optional("room_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_clear_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Clear manual override for one room or all rooms."""
    engine: Optional[PassableLightingEngine] = hass.data.get(DOMAIN, {}).get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    cleared = await engine.async_clear_manual_override(msg.get("room_id"))
    connection.send_result(msg["id"], {"success": True, "cleared": cleared})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_room_auto",
        vol.Optional("room_id"): vol.Any(str, None),
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_room_auto(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Enable or disable room automation for one room or all rooms."""
    engine: Optional[PassableLightingEngine] = hass.data.get(DOMAIN, {}).get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    room_id = msg.get("room_id")
    enabled = msg["enabled"]
    if room_id and room_id not in ("all", "*", ""):
        ctrl = engine.controllers.get(room_id)
        if not ctrl:
            connection.send_error(
                msg["id"], "not_found", f"Room '{room_id}' was not found."
            )
            return
        targets = [ctrl]
    else:
        targets = list(engine.controllers.values())

    updated: List[str] = []
    for ctrl in targets:
        ctrl.set_enabled(enabled)
        updated.append(ctrl.room_id)

    connection.send_result(
        msg["id"], {"success": True, "updated": updated, "enabled": enabled}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_room_circadian",
        vol.Required("room_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_room_circadian(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Toggle circadian rhythm setting on a room's config entry."""
    data = hass.data.get(DOMAIN, {})
    engine: Optional[PassableLightingEngine] = data.get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    room_id = msg["room_id"]
    enabled = msg["enabled"]
    entry_id, ctrl = _find_controller_and_entry(hass, room_id)
    if not ctrl:
        connection.send_error(
            msg["id"], "not_found", f"Room '{room_id}' was not found."
        )
        return

    new_data = {**ctrl.entry_data, CONF_CIRCADIAN_ENABLED: enabled}
    ctrl.entry_data = new_data
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry:
            data.setdefault("skip_reload_entries", set()).add(entry.entry_id)
            hass.config_entries.async_update_entry(entry, data=new_data)

    ctrl.notify_entities()
    if enabled:
        hass.async_create_task(engine.async_evaluate_dynamic_circadian(room_id))

    connection.send_result(
        msg["id"], {"success": True, "room_id": room_id, "enabled": enabled}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_target_lux",
        vol.Required("room_id"): str,
        vol.Required("target_lux"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1000)
        ),
    }
)
@websocket_api.async_response
async def ws_set_target_lux(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Update baseline target lux on a room's config entry and re-evaluate."""
    data = hass.data.get(DOMAIN, {})
    engine: Optional[PassableLightingEngine] = data.get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    room_id = msg["room_id"]
    target_lux = msg["target_lux"]
    entry_id, ctrl = _find_controller_and_entry(hass, room_id)
    if not ctrl:
        connection.send_error(
            msg["id"], "not_found", f"Room '{room_id}' was not found."
        )
        return

    new_data = {**ctrl.entry_data, CONF_TARGET_LUX: target_lux}
    ctrl.entry_data = new_data
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry:
            data.setdefault("skip_reload_entries", set()).add(entry.entry_id)
            hass.config_entries.async_update_entry(entry, data=new_data)

    ctrl.notify_entities()
    await ctrl.async_evaluate("target_lux_adjusted")
    connection.send_result(
        msg["id"], {"success": True, "room_id": room_id, "target_lux": target_lux}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/calibrate_room",
        vol.Required("room_id"): str,
        vol.Optional("force", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_calibrate_room(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Trigger automated yield curve calibration for a room."""
    engine: Optional[PassableLightingEngine] = hass.data.get(DOMAIN, {}).get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    room_id = msg["room_id"]
    if room_id not in engine.controllers:
        connection.send_error(
            msg["id"], "not_found", f"Room '{room_id}' was not found."
        )
        return

    hass.async_create_task(
        engine.async_calibrate_room_curve(room_id, force=msg.get("force", False))
    )
    connection.send_result(msg["id"], {"success": True, "room_id": room_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reset_learning_data",
        vol.Optional("room_id"): vol.Any(str, None),
        vol.Optional("reset_type", default="all"): vol.In(RESET_TYPES),
    }
)
@websocket_api.async_response
async def ws_reset_learning_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Reset learned lighting datasets for one room or all rooms."""
    store = hass.data.get(DOMAIN, {}).get("store")
    if not store:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    room_id = msg.get("room_id")
    reset_type = msg.get("reset_type", "all")
    await store.async_reset(room_id, reset_type)
    connection.send_result(
        msg["id"],
        {"success": True, "room_id": room_id, "reset_type": reset_type},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/preview_holiday",
        vol.Required("holiday_id"): str,
        vol.Optional("duration_sec", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=300)
        ),
    }
)
@websocket_api.async_response
async def ws_preview_holiday(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Preview a holiday lighting configuration temporarily."""
    holiday_coord = hass.data.get(DOMAIN, {}).get("holiday_coordinator")
    if not holiday_coord:
        connection.send_error(
            msg["id"], "not_found", "Holiday Lighting Coordinator is not loaded."
        )
        return

    target = msg["holiday_id"].strip().lower()
    matched_id: Optional[str] = None
    for hid, h in holiday_coord.store.holidays.items():
        if hid.lower() == target or str(h.get("name", "")).lower() == target:
            matched_id = hid
            break

    if not matched_id:
        connection.send_error(
            msg["id"], "not_found", f"Holiday '{msg['holiday_id']}' was not found."
        )
        return

    await holiday_coord.async_preview_holiday(
        matched_id, duration_sec=msg.get("duration_sec", 60)
    )
    connection.send_result(
        msg["id"], {"success": True, "holiday_id": matched_id}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/apply_holiday",
        vol.Optional("holiday_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_apply_holiday(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Apply a specific holiday lighting configuration or re-evaluate active holiday."""
    holiday_coord = hass.data.get(DOMAIN, {}).get("holiday_coordinator")
    if not holiday_coord:
        connection.send_error(
            msg["id"], "not_found", "Holiday Lighting Coordinator is not loaded."
        )
        return

    raw_id = msg.get("holiday_id")
    holiday_obj: Optional[Dict[str, Any]] = None
    if raw_id:
        target = raw_id.strip().lower()
        for hid, h in holiday_coord.store.holidays.items():
            if hid.lower() == target or str(h.get("name", "")).lower() == target:
                holiday_obj = h
                break
        if not holiday_obj:
            connection.send_error(
                msg["id"], "not_found", f"Holiday '{raw_id}' was not found."
            )
            return

    await holiday_coord.async_turn_on_holiday_lighting(preview_holiday=holiday_obj)
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "holiday_id": holiday_obj.get("id") if holiday_obj else None,
        },
    )


# ==========================================
# LIGHT STATS ANALYTICS HELPERS & WS COMMAND
# ==========================================


def _safe_float(val: Any) -> Optional[float]:
    """Parse a value to a finite float, returning None for invalid/unavailable states."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        fval = float(val)
        return None if (math.isnan(fval) or math.isinf(fval)) else fval
    text = str(val).strip()
    if not text or text.lower() in ("unknown", "unavailable", "none", "nan", "null"):
        return None
    try:
        fval = float(text)
    except (ValueError, TypeError):
        return None
    return None if (math.isnan(fval) or math.isinf(fval)) else fval


def _ensure_utc(ts_raw: Any) -> Optional[datetime]:
    """Normalize a datetime or ISO timestamp string to timezone-aware UTC."""
    if ts_raw is None:
        return None
    dt_obj: Optional[datetime] = None
    if isinstance(ts_raw, datetime):
        dt_obj = ts_raw
    elif isinstance(ts_raw, str):
        dt_obj = dt_util.parse_datetime(ts_raw)
        if dt_obj is None:
            try:
                dt_obj = datetime.fromisoformat(ts_raw)
            except ValueError:
                return None
    if dt_obj is None:
        return None
    if dt_obj.tzinfo is None:
        return dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(timezone.utc)


def _extract_state_ts(st: Any) -> Tuple[str, Dict[str, Any], Optional[datetime]]:
    """Safely extract (state, attributes, timestamp) preferring last_updated over last_changed."""
    if isinstance(st, Mapping):
        raw_state = st.get("state")
        raw_attrs = st.get("attributes")
        ts_raw = st.get("last_updated") or st.get("last_changed")
    else:
        raw_state = getattr(st, "state", None)
        raw_attrs = getattr(st, "attributes", None)
        ts_raw = getattr(st, "last_updated", None) or getattr(st, "last_changed", None)

    state_str = str(raw_state) if raw_state is not None else ""
    attrs = dict(raw_attrs) if isinstance(raw_attrs, Mapping) else {}
    return state_str, attrs, _ensure_utc(ts_raw)


def _resolve_room_floor(
    hass: HomeAssistant, light_entity: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve (floor_id, floor_name) for a room light entity via HA registries."""
    if not light_entity:
        return None, None
    try:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        area_reg = ar.async_get(hass)
        floor_reg = fr.async_get(hass)
    except Exception:
        return None, None

    candidates = [light_entity]
    for member in get_light_members(hass, light_entity):
        if member and member not in candidates:
            candidates.append(member)

    for eid in candidates:
        ent = ent_reg.async_get(eid) if ent_reg and hasattr(ent_reg, "async_get") else None
        if not ent:
            continue
        area_id = getattr(ent, "area_id", None)
        if not area_id and getattr(ent, "device_id", None) and dev_reg:
            dev = dev_reg.async_get(ent.device_id)
            if dev:
                area_id = getattr(dev, "area_id", None)
        if not area_id or not area_reg:
            continue

        area = (
            area_reg.async_get_area(area_id)
            if hasattr(area_reg, "async_get_area")
            else getattr(area_reg, "areas", {}).get(area_id)
        )
        if not area:
            continue
        floor_id = getattr(area, "floor_id", None)
        if not floor_id or not floor_reg:
            continue

        floor = (
            floor_reg.async_get_floor(floor_id)
            if hasattr(floor_reg, "async_get_floor")
            else getattr(floor_reg, "floors", {}).get(floor_id)
        )
        floor_name = getattr(floor, "name", None) if floor else None
        return str(floor_id), str(floor_name or floor_id)

    return None, None


def _bucket_numeric_series(
    states: List[Any],
    start_dt: datetime,
    end_dt: datetime,
    bucket_sec: int,
    n_buckets: int,
) -> Tuple[List[Optional[float]], Optional[float], Optional[float], Optional[float]]:
    """Downsample numeric sensor states into n_buckets using carry-forward and in-bucket mean."""
    records: List[Tuple[datetime, float]] = []
    for st in states or []:
        state_str, _, ts = _extract_state_ts(st)
        val = _safe_float(state_str)
        if ts is None or val is None:
            continue
        records.append((ts, val))
    records.sort(key=lambda item: item[0])

    idx = 0
    n_rec = len(records)
    carry_val: Optional[float] = None
    while idx < n_rec and records[idx][0] < start_dt:
        carry_val = records[idx][1]
        idx += 1

    all_observed: List[float] = []
    if carry_val is not None:
        all_observed.append(carry_val)

    series: List[Optional[float]] = []
    for b_idx in range(n_buckets):
        b_end = (
            end_dt
            if b_idx == n_buckets - 1
            else start_dt + timedelta(seconds=(b_idx + 1) * bucket_sec)
        )
        bucket_vals: List[float] = []
        while idx < n_rec:
            ts, val = records[idx]
            if (ts <= b_end) if b_idx == n_buckets - 1 else (ts < b_end):
                bucket_vals.append(val)
                all_observed.append(val)
                carry_val = val
                idx += 1
            else:
                break

        if bucket_vals:
            series.append(round(sum(bucket_vals) / len(bucket_vals), 1))
        elif carry_val is not None:
            series.append(round(carry_val, 1))
        else:
            series.append(None)

    valid_buckets = [v for v in series if v is not None]
    if not valid_buckets or not all_observed:
        return series, None, None, None

    min_val = round(min(all_observed), 1)
    max_val = round(max(all_observed), 1)
    avg_val = round(sum(valid_buckets) / len(valid_buckets), 1)
    return series, min_val, avg_val, max_val


def _light_state_to_pct(state_str: str, attrs: Dict[str, Any]) -> int:
    """Convert a Home Assistant light state and attributes to brightness 0..100."""
    if state_str.strip().lower() != "on":
        return 0
    raw_b = _safe_float(attrs.get("brightness"))
    if raw_b is not None:
        return max(1, min(100, int(round((raw_b / 255.0) * 100.0))))
    raw_bp = _safe_float(attrs.get("brightness_pct"))
    if raw_bp is not None:
        return max(1, min(100, int(round(raw_bp))))
    return 100


def _bucket_light_brightness(
    states: List[Any],
    start_dt: datetime,
    end_dt: datetime,
    bucket_sec: int,
    n_buckets: int,
) -> Tuple[List[int], float]:
    """Compute time-weighted per-bucket brightness (0-100) and exact lit_hours."""
    records: List[Tuple[datetime, int]] = []
    for st in states or []:
        state_str, attrs, ts = _extract_state_ts(st)
        if ts is None or not state_str:
            continue
        records.append((ts, _light_state_to_pct(state_str, attrs)))
    records.sort(key=lambda item: item[0])

    idx = 0
    n_rec = len(records)
    cur_pct = 0
    while idx < n_rec and records[idx][0] <= start_dt:
        cur_pct = records[idx][1]
        idx += 1

    # Build piecewise-constant intervals over [start_dt, end_dt]
    intervals: List[Tuple[datetime, datetime, int]] = []
    cursor = start_dt
    while idx < n_rec and records[idx][0] < end_dt:
        ev_ts, next_pct = records[idx]
        if ev_ts > cursor:
            intervals.append((cursor, ev_ts, cur_pct))
            cursor = ev_ts
        cur_pct = next_pct
        idx += 1
    if cursor < end_dt:
        intervals.append((cursor, end_dt, cur_pct))

    lit_sec = sum((t1 - t0).total_seconds() for t0, t1, pct in intervals if pct > 0)
    lit_hours = round(lit_sec / 3600.0, 2)

    series: List[int] = []
    iv_idx = 0
    n_iv = len(intervals)
    for b_idx in range(n_buckets):
        b_start = start_dt + timedelta(seconds=b_idx * bucket_sec)
        b_end = (
            end_dt
            if b_idx == n_buckets - 1
            else start_dt + timedelta(seconds=(b_idx + 1) * bucket_sec)
        )
        b_dur = max(1.0, (b_end - b_start).total_seconds())
        while iv_idx < n_iv and intervals[iv_idx][1] <= b_start:
            iv_idx += 1

        weighted = 0.0
        scan = iv_idx
        while scan < n_iv and intervals[scan][0] < b_end:
            iv_start, iv_end, pct = intervals[scan]
            ov_start = max(b_start, iv_start)
            ov_end = min(b_end, iv_end)
            if ov_end > ov_start and pct > 0:
                weighted += (ov_end - ov_start).total_seconds() * pct
            if iv_end <= b_end:
                iv_idx = scan + 1
            scan += 1

        series.append(max(0, min(100, int(round(weighted / b_dur)))))

    return series, lit_hours


def _compute_mode_timeline(
    states: List[Any],
    start_dt: datetime,
    end_dt: datetime,
    fallback_mode: str = "vacant",
    hours: int = 24,
) -> Tuple[List[Dict[str, Any]], Dict[str, float], int]:
    """Build merged mode segments, exact per-mode durations (sec), and override transition count."""
    records: List[Tuple[datetime, str]] = []
    for st in states or []:
        state_str, _, ts = _extract_state_ts(st)
        cleaned = state_str.strip().lower()
        if ts is None or not cleaned or cleaned in ("unknown", "unavailable", "none"):
            continue
        records.append((ts, cleaned))
    records.sort(key=lambda item: item[0])

    total_sec = max(0.0, (end_dt - start_dt).total_seconds())
    start_ms = int(round(start_dt.timestamp() * 1000))
    end_ms = int(round(end_dt.timestamp() * 1000))

    if not records:
        safe_mode = (fallback_mode or "vacant").strip().lower()
        return (
            [{"start_ms": start_ms, "end_ms": end_ms, "mode": safe_mode}],
            {safe_mode: round(total_sec, 3)},
            0,
        )

    idx = 0
    n_rec = len(records)
    cur_mode: Optional[str] = None
    while idx < n_rec and records[idx][0] <= start_dt:
        cur_mode = records[idx][1]
        idx += 1
    if cur_mode is None:
        cur_mode = records[0][1]

    raw_intervals: List[Tuple[datetime, datetime, str]] = []
    override_events = 0
    cursor = start_dt
    prev_mode = cur_mode

    while idx < n_rec and records[idx][0] < end_dt:
        ev_ts, next_mode = records[idx]
        if ev_ts > cursor:
            raw_intervals.append((cursor, ev_ts, cur_mode))
            cursor = ev_ts
        if next_mode != prev_mode:
            if next_mode == "manual_override":
                override_events += 1
            prev_mode = next_mode
        cur_mode = next_mode
        idx += 1

    # Also catch an event exactly at end_dt for transition counting if distinct
    while idx < n_rec and records[idx][0] == end_dt:
        next_mode = records[idx][1]
        if next_mode != prev_mode:
            if next_mode == "manual_override":
                override_events += 1
            prev_mode = next_mode
        idx += 1

    if cursor < end_dt:
        raw_intervals.append((cursor, end_dt, cur_mode))

    # Merge adjacent identical intervals
    merged_intervals: List[List[Any]] = []
    for t0, t1, mode in raw_intervals:
        if t1 <= t0:
            continue
        if merged_intervals and merged_intervals[-1][2] == mode:
            merged_intervals[-1][1] = t1
        else:
            merged_intervals.append([t0, t1, mode])

    # Exact durations across the window
    mode_durations_sec: Dict[str, float] = {}
    for t0, t1, mode in merged_intervals:
        dur = (t1 - t0).total_seconds()
        mode_durations_sec[mode] = mode_durations_sec.get(mode, 0.0) + dur
    for k in list(mode_durations_sec.keys()):
        mode_durations_sec[k] = round(mode_durations_sec[k], 3)

    # Smooth transient (< 15s) non-override blips on >=24h views for clean timeline rendering
    smoothed = [list(iv) for iv in merged_intervals]
    if hours >= 24 and len(smoothed) > 1:
        changed = True
        while changed and len(smoothed) > 1:
            changed = False
            for i, (t0, t1, mode) in enumerate(smoothed):
                if mode != "manual_override" and (t1 - t0).total_seconds() < 15.0:
                    if i > 0:
                        smoothed[i - 1][1] = t1
                    else:
                        smoothed[i + 1][0] = t0
                    smoothed.pop(i)
                    # Re-merge adjacent identical modes
                    remerged: List[List[Any]] = []
                    for st0, st1, sm in smoothed:
                        if remerged and remerged[-1][2] == sm:
                            remerged[-1][1] = st1
                        else:
                            remerged.append([st0, st1, sm])
                    smoothed = remerged
                    changed = True
                    break

    segments = [
        {
            "start_ms": int(round(t0.timestamp() * 1000)),
            "end_ms": int(round(t1.timestamp() * 1000)),
            "mode": mode,
        }
        for t0, t1, mode in smoothed
    ]
    return segments, mode_durations_sec, override_events


def _compute_daylight_harvest(
    mode_states: List[Any],
    light_states: List[Any],
    start_dt: datetime,
    end_dt: datetime,
    fallback_mode: str = "vacant",
    fallback_light_on: bool = False,
) -> Tuple[float, float]:
    """Compute (occupied_sec, occupied_lights_off_sec) across [start_dt, end_dt]."""
    mode_events: List[Tuple[datetime, str]] = []
    for st in mode_states or []:
        state_str, _, ts = _extract_state_ts(st)
        cleaned = state_str.strip().lower()
        if ts is None or not cleaned or cleaned in ("unknown", "unavailable", "none"):
            continue
        mode_events.append((ts, cleaned))
    mode_events.sort(key=lambda item: item[0])

    light_events: List[Tuple[datetime, bool]] = []
    for st in light_states or []:
        state_str, _, ts = _extract_state_ts(st)
        if ts is None or not state_str:
            continue
        light_events.append((ts, state_str.strip().lower() == "on"))
    light_events.sort(key=lambda item: item[0])

    m_idx = 0
    cur_mode = (fallback_mode or "vacant").strip().lower()
    if mode_events:
        while m_idx < len(mode_events) and mode_events[m_idx][0] <= start_dt:
            cur_mode = mode_events[m_idx][1]
            m_idx += 1
        if m_idx == 0:
            cur_mode = mode_events[0][1]

    l_idx = 0
    cur_light_on = bool(fallback_light_on)
    if light_events:
        while l_idx < len(light_events) and light_events[l_idx][0] <= start_dt:
            cur_light_on = light_events[l_idx][1]
            l_idx += 1

    boundaries = {start_dt, end_dt}
    for ts, _ in mode_events[m_idx:]:
        if start_dt < ts < end_dt:
            boundaries.add(ts)
    for ts, _ in light_events[l_idx:]:
        if start_dt < ts < end_dt:
            boundaries.add(ts)

    sorted_bounds = sorted(boundaries)
    occupied_sec = 0.0
    occupied_lights_off_sec = 0.0

    for i in range(len(sorted_bounds) - 1):
        t0 = sorted_bounds[i]
        t1 = sorted_bounds[i + 1]
        while m_idx < len(mode_events) and mode_events[m_idx][0] <= t0:
            cur_mode = mode_events[m_idx][1]
            m_idx += 1
        while l_idx < len(light_events) and light_events[l_idx][0] <= t0:
            cur_light_on = light_events[l_idx][1]
            l_idx += 1

        dt_sec = (t1 - t0).total_seconds()
        if cur_mode == "occupied" and dt_sec > 0:
            occupied_sec += dt_sec
            if not cur_light_on:
                occupied_lights_off_sec += dt_sec

    return round(occupied_sec, 3), round(occupied_lights_off_sec, 3)


def _compute_night_bands(
    sun_states: List[Any],
    start_dt: datetime,
    end_dt: datetime,
) -> List[Dict[str, int]]:
    """Extract below-horizon intervals from sun.sun history clipped to [start_dt, end_dt]."""
    events: List[Tuple[datetime, str]] = []
    for st in sun_states or []:
        state_str, _, ts = _extract_state_ts(st)
        cleaned = state_str.strip().lower()
        if ts is None or cleaned not in ("below_horizon", "above_horizon"):
            continue
        events.append((ts, cleaned))
    events.sort(key=lambda item: item[0])

    if not events:
        return []

    idx = 0
    n_ev = len(events)
    cur_state: Optional[str] = None
    while idx < n_ev and events[idx][0] <= start_dt:
        cur_state = events[idx][1]
        idx += 1
    if cur_state is None:
        # Infer state prior to first transition within window
        cur_state = "above_horizon" if events[0][1] == "below_horizon" else "below_horizon"

    bands: List[Dict[str, int]] = []
    cursor = start_dt
    while idx < n_ev and events[idx][0] < end_dt:
        ev_ts, next_state = events[idx]
        if ev_ts > cursor and cur_state == "below_horizon":
            s_ms = int(round(cursor.timestamp() * 1000))
            e_ms = int(round(ev_ts.timestamp() * 1000))
            if bands and bands[-1]["end_ms"] == s_ms:
                bands[-1]["end_ms"] = e_ms
            else:
                bands.append({"start_ms": s_ms, "end_ms": e_ms})
        if ev_ts > cursor:
            cursor = ev_ts
        cur_state = next_state
        idx += 1

    if cursor < end_dt and cur_state == "below_horizon":
        s_ms = int(round(cursor.timestamp() * 1000))
        e_ms = int(round(end_dt.timestamp() * 1000))
        if bands and bands[-1]["end_ms"] == s_ms:
            bands[-1]["end_ms"] = e_ms
        else:
            bands.append({"start_ms": s_ms, "end_ms": e_ms})

    return bands


def _compute_lights_on_timeline(
    hist_map: Dict[str, List[Any]],
    light_ids: List[str],
    start_dt: datetime,
    end_dt: datetime,
    bucket_sec: int,
    n_buckets: int,
) -> Dict[str, Any]:
    """Compute per-bucket peak concurrent lights ON across all tracked lights."""
    unique_lights = list(dict.fromkeys(eid for eid in light_ids if eid))
    delta_events: List[Tuple[datetime, int]] = []
    active = 0

    for eid in unique_lights:
        states = hist_map.get(eid) or []
        per_light: List[Tuple[datetime, bool]] = []
        for st in states:
            state_str, _, ts = _extract_state_ts(st)
            if ts is None or not state_str:
                continue
            per_light.append((ts, state_str.strip().lower() == "on"))
        per_light.sort(key=lambda item: item[0])

        idx = 0
        was_on = False
        while idx < len(per_light) and per_light[idx][0] <= start_dt:
            was_on = per_light[idx][1]
            idx += 1
        if was_on:
            active += 1

        while idx < len(per_light) and per_light[idx][0] < end_dt:
            ev_ts, is_on = per_light[idx]
            if is_on != was_on:
                delta_events.append((ev_ts, 1 if is_on else -1))
                was_on = is_on
            idx += 1

    delta_events.sort(key=lambda item: item[0])
    ev_idx = 0
    n_ev = len(delta_events)

    counts: List[int] = []
    total_weighted_sec = 0.0
    for b_idx in range(n_buckets):
        b_start = start_dt + timedelta(seconds=b_idx * bucket_sec)
        b_end = (
            end_dt
            if b_idx == n_buckets - 1
            else start_dt + timedelta(seconds=(b_idx + 1) * bucket_sec)
        )
        while ev_idx < n_ev and delta_events[ev_idx][0] <= b_start:
            active = max(0, active + delta_events[ev_idx][1])
            ev_idx += 1

        b_peak = active
        cursor = b_start
        while ev_idx < n_ev and delta_events[ev_idx][0] < b_end:
            ev_ts, delta = delta_events[ev_idx]
            if ev_ts > cursor:
                total_weighted_sec += active * (ev_ts - cursor).total_seconds()
                cursor = ev_ts
            active = max(0, active + delta)
            if active > b_peak:
                b_peak = active
            ev_idx += 1

        if b_end > cursor:
            total_weighted_sec += active * (b_end - cursor).total_seconds()

        counts.append(max(0, b_peak))

    window_sec = max(1.0, (end_dt - start_dt).total_seconds())
    return {
        "counts": counts,
        "peak_on": max(counts) if counts else 0,
        "avg_on": round(total_weighted_sec / window_sec, 1),
        "total_tracked": len(unique_lights),
    }


def _build_sun_pref_curve(
    seed_lux: float, user_prefs: List[Dict[str, Any]]
) -> List[List[float]]:
    """Evaluate blended target lux across sun elevations -30..70 degrees."""
    return [
        [
            float(elev),
            round(calculate_learned_target_lux(seed_lux, user_prefs, float(elev), None), 1),
        ]
        for elev in range(-30, 75, 5)
    ]


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_stats",
        vol.Optional("hours", default=24): vol.All(vol.Coerce(int), vol.In([6, 24, 168])),
        vol.Optional("light_entities", default=[]): [str],
    }
)
@websocket_api.async_response
async def ws_get_stats(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: Dict[str, Any],
) -> None:
    """Return Recorder-backed historical lighting analytics and learned sun preferences."""
    engine: Optional[PassableLightingEngine] = hass.data.get(DOMAIN, {}).get("engine")
    if not engine:
        connection.send_error(
            msg["id"], "not_found", "Passable Smart Light Engine is not loaded."
        )
        return

    hours = int(msg.get("hours", 24))
    bucket_map = {6: (72, 300), 24: (96, 900), 168: (168, 3600)}
    n_buckets, bucket_sec = bucket_map.get(hours, (96, 900))

    end_dt = dt_util.utcnow()
    start_dt = end_dt - timedelta(hours=hours)
    start_ms = int(round(start_dt.timestamp() * 1000))
    end_ms = int(round(end_dt.timestamp() * 1000))
    timestamps_ms = [
        int(round((start_dt + timedelta(seconds=(i + 0.5) * bucket_sec)).timestamp() * 1000))
        for i in range(n_buckets)
    ]

    try:
        ent_reg = er.async_get(hass)
    except Exception:
        ent_reg = None

    sun_state = hass.states.get("sun.sun")
    elev = _safe_float(sun_state.attributes.get("elevation")) if sun_state else 0.0
    elev = elev if elev is not None else 0.0
    azim = (
        _safe_float(sun_state.attributes.get("azimuth"))
        if sun_state and "azimuth" in sun_state.attributes
        else None
    )

    store = engine.store
    learning_data = store.data

    # Collect entities to query in Query 1 (room telemetry + sun.sun)
    room_meta: List[Dict[str, Any]] = []
    query1_entities: List[str] = ["sun.sun"]
    for room_id, ctrl in sorted(
        engine.controllers.items(),
        key=lambda item: item[0].replace("_", " ").lower(),
    ):
        entry_data = ctrl.entry_data
        light_entity = entry_data.get(CONF_LIGHT_ENTITY)
        lux_sensor = entry_data.get(CONF_LUX_SENSOR)
        target_lux_sensor = _resolve_entity_id(
            ent_reg, "sensor", f"{DOMAIN}_{room_id}_target_lux_sensor"
        )
        active_mode_sensor = _resolve_entity_id(
            ent_reg, "sensor", f"{DOMAIN}_{room_id}_active_mode"
        )
        for eid in (lux_sensor, target_lux_sensor, active_mode_sensor, light_entity):
            if eid and eid not in query1_entities:
                query1_entities.append(eid)

        sec_lights = entry_data.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS) or []
        if isinstance(sec_lights, str):
            sec_lights = [sec_lights] if sec_lights else []
        raw_leaves: List[str] = []
        if light_entity:
            raw_leaves.extend(get_light_members(hass, light_entity))
        for sec in sec_lights:
            if sec:
                raw_leaves.extend(get_light_members(hass, sec))
        leaf_lights = list(dict.fromkeys(raw_leaves))

        room_meta.append(
            {
                "room_id": room_id,
                "ctrl": ctrl,
                "entry_data": entry_data,
                "light_entity": light_entity,
                "leaf_lights": leaf_lights,
                "lux_sensor": lux_sensor,
                "target_lux_sensor": target_lux_sensor,
                "active_mode_sensor": active_mode_sensor,
            }
        )

    req_lights = [
        eid
        for eid in dict.fromkeys(msg.get("light_entities") or [])
        if isinstance(eid, str) and eid.startswith("light.")
    ][:120]
    if not req_lights:
        fallback_lights: List[str] = []
        for rm in room_meta:
            for lid in rm["leaf_lights"] or ([rm["light_entity"]] if rm["light_entity"] else []):
                if lid and lid not in fallback_lights:
                    fallback_lights.append(lid)
        req_lights = fallback_lights[:120]

    extra_lights = [eid for eid in req_lights if eid not in query1_entities][:120]

    hist_map: Dict[str, List[Any]] = {}
    recorder_available = True

    def _fetch_room_history() -> Dict[str, List[Any]]:
        return history.get_significant_states(
            hass,
            start_time=start_dt,
            end_time=end_dt,
            entity_ids=query1_entities,
            include_start_time_state=True,
            significant_changes_only=False,
        )

    def _fetch_extra_lights_history() -> Dict[str, List[Any]]:
        try:
            return history.get_significant_states(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                entity_ids=extra_lights,
                include_start_time_state=True,
                significant_changes_only=True,
                no_attributes=True,
            )
        except TypeError:
            return history.get_significant_states(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                entity_ids=extra_lights,
                include_start_time_state=True,
                significant_changes_only=True,
            )

    try:
        rec = recorder.get_instance(hass)
        if query1_entities:
            q1_res = await rec.async_add_executor_job(_fetch_room_history)
            if isinstance(q1_res, dict):
                hist_map.update(q1_res)
        if extra_lights:
            q2_res = await rec.async_add_executor_job(_fetch_extra_lights_history)
            if isinstance(q2_res, dict):
                hist_map.update(q2_res)
    except Exception as err:
        _LOGGER.debug("PassableSmartLighting: Recorder stats query unavailable: %s", err)
        recorder_available = False

    sun_states = hist_map.get("sun.sun") or ([sun_state] if sun_state else [])
    night_bands = _compute_night_bands(sun_states, start_dt, end_dt)

    floors_dict: Dict[str, str] = {}
    rooms_stats: List[Dict[str, Any]] = []
    total_active_sec = 0.0
    total_override_sec = 0.0
    total_override_events = 0
    total_occupied_sec = 0.0
    total_occupied_off_sec = 0.0
    total_pref_samples = 0

    for rm in room_meta:
        room_id = rm["room_id"]
        ctrl = rm["ctrl"]
        entry_data = rm["entry_data"]
        light_entity = rm["light_entity"]
        lux_sensor = rm["lux_sensor"]
        target_lux_sensor = rm["target_lux_sensor"]
        active_mode_sensor = rm["active_mode_sensor"]

        floor_id, floor_name = _resolve_room_floor(hass, light_entity)
        if floor_id:
            floors_dict.setdefault(floor_id, floor_name or floor_id)

        seed_lux = float(entry_data.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX))
        user_prefs = learning_data.get("user_prefs", {}).get(room_id, [])
        blended_target_lux = round(
            calculate_learned_target_lux(seed_lux, user_prefs, elev, azim), 1
        )
        curves = learning_data.get("room_curves", {}).get(room_id, {})

        live_mode = compute_room_active_mode(hass, engine, ctrl)
        live_light_st = hass.states.get(light_entity) if light_entity else None
        is_light_on = bool(live_light_st and live_light_st.state == "on")

        smoothed_lux = (
            engine.get_smoothed_lux_optional(room_id, lux_sensor)
            if lux_sensor
            else None
        )
        ambient_lux = round(smoothed_lux, 1) if smoothed_lux is not None else None
        if ambient_lux is None and lux_sensor:
            raw_lux_st = hass.states.get(lux_sensor)
            ambient_lux = _safe_float(raw_lux_st.state) if raw_lux_st else None
            if ambient_lux is not None:
                ambient_lux = round(ambient_lux, 1)

        if lux_sensor:
            lux_states = hist_map.get(lux_sensor) or (
                [hass.states.get(lux_sensor)] if hass.states.get(lux_sensor) else []
            )
            lux_series, lux_min, lux_avg, lux_max = _bucket_numeric_series(
                lux_states, start_dt, end_dt, bucket_sec, n_buckets
            )
        else:
            lux_series = [None] * n_buckets
            lux_min = lux_avg = lux_max = None

        tgt_states = hist_map.get(target_lux_sensor) if target_lux_sensor else []
        target_lux_series, _, _, _ = _bucket_numeric_series(
            tgt_states or [], start_dt, end_dt, bucket_sec, n_buckets
        )
        if all(v is None for v in target_lux_series):
            target_lux_series = [blended_target_lux] * n_buckets

        light_states = hist_map.get(light_entity) if light_entity else []
        if not light_states and live_light_st:
            light_states = [live_light_st]
        brightness_series, lit_hours = _bucket_light_brightness(
            light_states or [], start_dt, end_dt, bucket_sec, n_buckets
        )

        mode_states = hist_map.get(active_mode_sensor) if active_mode_sensor else []
        mode_segments, mode_durations_sec, override_events = _compute_mode_timeline(
            mode_states or [], start_dt, end_dt, fallback_mode=live_mode, hours=hours
        )
        mode_hours = {
            m: round(dur / 3600.0, 2) for m, dur in mode_durations_sec.items() if dur > 0
        }

        override_sec = mode_durations_sec.get("manual_override", 0.0)
        override_hours = round(override_sec / 3600.0, 2)
        room_active_sec = sum(
            dur
            for m, dur in mode_durations_sec.items()
            if m not in ("vacant", "disabled", "forced_off", "frozen")
        )
        lit_sec = lit_hours * 3600.0
        denom_sec = room_active_sec if room_active_sec > 0 else lit_sec
        if denom_sec > 0:
            auto_pct = round(max(0.0, min(100.0, 100.0 * (1.0 - override_sec / denom_sec))), 1)
        else:
            auto_pct = 100.0 if override_sec == 0 else 0.0

        total_active_sec += denom_sec
        total_override_sec += override_sec
        total_override_events += override_events

        occ_sec, occ_off_sec = _compute_daylight_harvest(
            mode_states or [],
            light_states or [],
            start_dt,
            end_dt,
            fallback_mode=live_mode,
            fallback_light_on=is_light_on,
        )
        daylight_harvest_pct = (
            round(100.0 * occ_off_sec / occ_sec, 1) if occ_sec > 0 else None
        )
        if lux_sensor and occ_sec > 0:
            total_occupied_sec += occ_sec
            total_occupied_off_sec += occ_off_sec

        samples = []
        for pref in user_prefs:
            if not isinstance(pref, Mapping):
                continue
            p_elev = _safe_float(pref.get("sun_elev"))
            p_lux = _safe_float(pref.get("preferred_lux"))
            if p_elev is None or p_lux is None:
                continue
            p_azim = _safe_float(pref.get("sun_azimuth"))
            samples.append(
                {
                    "elev": round(p_elev, 1),
                    "azim": round(p_azim, 1) if p_azim is not None else None,
                    "lux": round(p_lux, 1),
                }
            )
        total_pref_samples += len(samples)

        rooms_stats.append(
            {
                "room_id": room_id,
                "name": room_id.replace("_", " ").title(),
                "floor_id": floor_id,
                "floor_name": floor_name,
                "light_entity": light_entity,
                "lux_sensor": lux_sensor,
                "has_lux_sensor": bool(lux_sensor),
                "active_mode": live_mode,
                "is_light_on": is_light_on,
                "ambient_lux": ambient_lux,
                "seed_target_lux": int(round(seed_lux)),
                "blended_target_lux": blended_target_lux,
                "lux_series": lux_series,
                "target_lux_series": target_lux_series,
                "brightness_series": brightness_series,
                "mode_segments": mode_segments,
                "mode_hours": mode_hours,
                "lit_hours": lit_hours,
                "override_events": override_events,
                "override_hours": override_hours,
                "auto_pct": auto_pct,
                "daylight_harvest_pct": daylight_harvest_pct,
                "lux_min": lux_min,
                "lux_avg": lux_avg,
                "lux_max": lux_max,
                "curve_points_count": len(curves),
                "sun_prefs": {
                    "seed_lux": int(round(seed_lux)),
                    "blended_lux": blended_target_lux,
                    "samples": samples,
                    "curve": _build_sun_pref_curve(seed_lux, user_prefs),
                },
            }
        )

    # Whole-home lights ON timeline
    # Include fallback current states for lights with empty recorder history
    for eid in req_lights:
        if eid not in hist_map:
            cur_st = hass.states.get(eid)
            if cur_st is not None:
                hist_map[eid] = [cur_st]
    lights_on_timeline = _compute_lights_on_timeline(
        hist_map, req_lights, start_dt, end_dt, bucket_sec, n_buckets
    )

    busiest_room = max(rooms_stats, key=lambda r: r["lit_hours"], default=None)
    busiest_hours = busiest_room["lit_hours"] if busiest_room else 0.0

    try:
        summary_payload = compute_engine_summary(hass, engine)
    except Exception:
        summary_payload = {}

    if total_active_sec > 0:
        overall_auto_pct = round(
            max(0.0, min(100.0, 100.0 * (1.0 - total_override_sec / total_active_sec))),
            1,
        )
    else:
        overall_auto_pct = 100.0 if total_override_sec == 0 else 0.0

    overall_daylight_pct = (
        round(100.0 * total_occupied_off_sec / total_occupied_sec, 1)
        if total_occupied_sec > 0
        else None
    )

    floors_list = [
        {"id": fid, "name": fname}
        for fid, fname in sorted(floors_dict.items(), key=lambda item: item[1].lower())
    ]

    connection.send_result(
        msg["id"],
        {
            "hours": hours,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "bucket_sec": bucket_sec,
            "timestamps_ms": timestamps_ms,
            "recorder_available": recorder_available,
            "current_sun_elev": round(elev, 1),
            "current_sun_azim": round(azim, 1) if azim is not None else None,
            "night_bands": night_bands,
            "floors": floors_list,
            "kpis": {
                "total_lit_hours": round(sum(r["lit_hours"] for r in rooms_stats), 1),
                "busiest_room_name": (
                    busiest_room["name"] if busiest_room and busiest_hours > 0 else None
                ),
                "busiest_room_hours": round(busiest_hours, 1),
                "auto_pct": overall_auto_pct,
                "override_events": total_override_events,
                "override_hours": round(total_override_sec / 3600.0, 1),
                "daylight_harvest_pct": overall_daylight_pct,
                "calibrated_rooms": sum(
                    1 for r in rooms_stats if r["curve_points_count"] > 0
                ),
                "total_rooms": len(rooms_stats),
                "total_pref_samples": total_pref_samples,
                "current_circadian_kelvin": summary_payload.get("current_circadian_kelvin"),
            },
            "lights_on_timeline": lights_on_timeline,
            "rooms": rooms_stats,
        },
    )
