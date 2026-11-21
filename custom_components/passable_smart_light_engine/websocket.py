"""WebSocket API handlers for Passable Smart Light Engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
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
            "version": data.get("version") or "2.9.3",
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
        "version": data.get("version") or "2.9.3",
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
