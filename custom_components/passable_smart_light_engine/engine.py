"""Core algorithmic lighting engine for Passable Adaptive Smart Lighting Controller."""

import asyncio
from datetime import datetime, time as dtime, timedelta
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
import homeassistant.util.dt as dt_util

from .const import (
    ACTIVE_STATES,
    CONF_BYPASS_FREEZE_ENTITIES,
    CONF_BYPASS_OFF_ENTITIES,
    CONF_LIGHT_ENTITY,
    CONF_LUX_SENSOR,
    CONF_MEDIA_ENTITIES,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_ROOM_ID,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
    DEFAULT_LATE_NIGHT_CONDITION_TYPE,
    DEFAULT_LATE_NIGHT_ENABLED,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LATE_NIGHT_START_TIME,
    DEFAULT_LATE_NIGHT_STOP_TIME,
    DEFAULT_LUX_RATIO,
    DEFAULT_MAX_COLOR_TEMP,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_MIN_OCCUPIED_PCT,
    DEFAULT_OVERRIDE_TIMEOUT_MIN,
    DEFAULT_POWER_GRID_ENTITY,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_TARGET_LUX,
    DOMAIN,
    ECHO_GUARD_TOLERANCE_PCT,
    ECHO_GUARD_WINDOW_SEC,
    MIN_VISIBLE_PCT,
)
from .storage import LearningDataStore

_LOGGER = logging.getLogger(__name__)


def safe_get_state(hass: HomeAssistant, entity_id: Optional[str], default: Any = 0) -> Any:
    """Safely fetch an entity state or attribute."""
    if not entity_id or not isinstance(entity_id, str):
        return default
    try:
        if "." in entity_id and len(entity_id.split(".")) == 3:
            domain, entity, attr = entity_id.split(".")
            st = hass.states.get(f"{domain}.{entity}")
            if st and st.attributes and attr in st.attributes:
                val = st.attributes[attr]
                if val is not None and val not in ("unknown", "unavailable"):
                    return val
            return default

        st = hass.states.get(entity_id)
        if st and st.state not in (None, "unknown", "unavailable"):
            return st.state
        return default
    except Exception:
        return default


def get_circadian_temp(
    hass: HomeAssistant, min_temp: int = DEFAULT_MIN_COLOR_TEMP, max_temp: int = DEFAULT_MAX_COLOR_TEMP
) -> int:
    """Calculate circadian color temperature (Kelvin) based on sun elevation."""
    try:
        sun_state = hass.states.get("sun.sun")
        elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
    except Exception:
        elev = 0.0

    elev = max(0.0, min(60.0, elev))
    factor = elev / 60.0
    return int(min_temp + factor * (max_temp - min_temp))


def get_expected_lux(curve: Dict[str, Any], pct: float, default_lux_ratio: float = DEFAULT_LUX_RATIO) -> float:
    """Calculate expected room lux for a given dimmer percentage based on learned curve."""
    if not curve:
        return float(pct) * float(default_lux_ratio)

    pts: List[Tuple[float, float]] = []
    for p_str, lux_val in curve.items():
        try:
            pts.append((float(p_str), float(lux_val)))
        except (ValueError, TypeError):
            continue

    if not pts:
        return float(pct) * float(default_lux_ratio)

    pts.sort(key=lambda x: x[0])

    if pct <= pts[0][0]:
        if pts[0][0] == 0:
            return pts[0][1]
        slope = pts[0][1] / pts[0][0]
        return max(0.0, slope * pct)

    if pct >= pts[-1][0]:
        slope = (pts[-1][1] - pts[-2][1]) / (pts[-1][0] - pts[-2][0]) if len(pts) > 1 else default_lux_ratio
        slope = max(0.1, slope)
        return pts[-1][1] + slope * (pct - pts[-1][0])

    for i in range(len(pts) - 1):
        p1, l1 = pts[i]
        p2, l2 = pts[i + 1]
        if p1 <= pct <= p2:
            if p2 == p1:
                return l1
            factor = (pct - p1) / (p2 - p1)
            return l1 + factor * (l2 - l1)

    return float(pct) * float(default_lux_ratio)


def calculate_required_pct(
    target_lux: float,
    current_lux: float,
    curve: Dict[str, Any],
    default_lux_ratio: float = DEFAULT_LUX_RATIO,
    min_pct: int = 0,
) -> int:
    """Calculate the light brightness % needed to reach target ambient lux."""
    lux_needed = target_lux - current_lux
    if lux_needed <= 0:
        return 0

    best_pct = 100
    for pct in range(1, 101):
        expected = get_expected_lux(curve, pct, default_lux_ratio)
        if expected >= lux_needed:
            best_pct = pct
            break

    effective_floor = max(MIN_VISIBLE_PCT, int(min_pct or 0))
    return max(effective_floor, min(100, best_pct))


def calculate_learned_target_lux(
    seed_lux: float, user_prefs: List[Dict[str, Any]], current_elevation: float
) -> float:
    """Blend seed lux with historical user preferences weighted by sun elevation proximity."""
    if not user_prefs:
        return float(seed_lux)

    total_weight = 0.0
    weighted_lux = 0.0

    for pref in user_prefs:
        pref_elev = float(pref.get("sun_elev", 0.0))
        pref_lux = float(pref.get("preferred_lux", seed_lux))
        diff = abs(current_elevation - pref_elev)
        weight = math.exp(-0.5 * (diff / 15.0) ** 2)
        weighted_lux += pref_lux * weight
        total_weight += weight

    if total_weight < 0.01:
        return float(seed_lux)

    learned_avg = weighted_lux / total_weight
    # Blend with seed: 5 samples reach full weight
    blend_factor = min(1.0, len(user_prefs) / 5.0)
    return (learned_avg * blend_factor) + (float(seed_lux) * (1.0 - blend_factor))


class PassableLightingEngine:
    """Central engine managing memory, echo guards, timers, and execution."""

    def __init__(self, hass: HomeAssistant, store: LearningDataStore) -> None:
        """Initialize the lighting engine."""
        self.hass = hass
        self.store = store
        self._lux_history: Dict[str, List[float]] = {}
        self._room_locks: Dict[str, asyncio.Lock] = {}
        self._echo_guards: Dict[str, Dict[str, Any]] = {}
        self._override_timers: Dict[str, Dict[str, Any]] = {}
        self._vacancy_timers: Dict[str, CALLBACK_TYPE] = {}
        self._stabilizing_tasks: Dict[str, asyncio.Task] = {}
        self._controllers: Dict[str, "RoomController"] = {}

    def get_lock(self, room_id: str) -> asyncio.Lock:
        """Return or create a mutex lock for a room."""
        if room_id not in self._room_locks:
            self._room_locks[room_id] = asyncio.Lock()
        return self._room_locks[room_id]

    def register_controller(self, room_id: str, controller: "RoomController") -> None:
        """Register an active native room controller."""
        self._controllers[room_id] = controller

    def unregister_controller(self, room_id: str) -> None:
        """Unregister an active native room controller."""
        self._controllers.pop(room_id, None)

    def get_smoothed_lux(self, room_id: str, lux_sensor: str, max_readings: int = 5) -> float:
        """Compute spike-smoothed ambient lux reading."""
        raw_val = safe_get_state(self.hass, lux_sensor, 0.0)
        try:
            current_lux = float(raw_val)
        except (ValueError, TypeError):
            current_lux = 0.0

        if room_id not in self._lux_history:
            self._lux_history[room_id] = []

        history = self._lux_history[room_id]
        history.append(current_lux)
        if len(history) > max_readings:
            history.pop(0)

        if len(history) >= 3:
            sorted_readings = sorted(history)
            trimmed = sorted_readings[1:-1]
            return sum(trimmed) / len(trimmed)
        return sum(history) / len(history)

    def set_echo_guard(
        self, room_id: str, target_pct: int, start_pct: int, duration_sec: float = 1.0
    ) -> None:
        """Record an intended lighting adjustment for trajectory-bounded echo guarding."""
        now = time.time()
        self._echo_guards[room_id] = {
            "expires_at": now + ECHO_GUARD_WINDOW_SEC + duration_sec,
            "target_pct": target_pct,
            "start_pct": start_pct,
            "duration": duration_sec,
            "timestamp": now,
        }

    def check_echo_guard(self, room_id: str, current_pct: int) -> bool:
        """Check if an incoming light state update is an echo of an automated change."""
        guard = self._echo_guards.get(room_id)
        if not guard:
            return False

        now = time.time()
        if now > guard["expires_at"]:
            self._echo_guards.pop(room_id, None)
            return False

        target_pct = guard["target_pct"]
        start_pct = guard["start_pct"]
        tolerance = ECHO_GUARD_TOLERANCE_PCT

        if abs(current_pct - target_pct) <= tolerance:
            return True

        if abs(current_pct - start_pct) <= tolerance:
            return True

        # In-flight trajectory check
        min_p = min(start_pct, target_pct) - tolerance
        max_p = max(start_pct, target_pct) + tolerance
        if min_p <= current_pct <= max_p:
            return True

        return False

    def is_manual_override_active(self, room_id: str) -> bool:
        """Check if manual override is currently active for a room."""
        override = self._override_timers.get(room_id)
        if not override:
            return False
        if time.time() > override.get("expires_at", 0):
            self._override_timers.pop(room_id, None)
            return False
        return True

    def get_override_remaining_sec(self, room_id: str) -> int:
        """Return remaining seconds of manual override."""
        override = self._override_timers.get(room_id)
        if not override:
            return 0
        rem = int(override.get("expires_at", 0) - time.time())
        return max(0, rem)

    def set_manual_override(
        self, room_id: str, timeout_min: int, cancel_cb: Optional[CALLBACK_TYPE] = None
    ) -> None:
        """Activate manual override for a room."""
        # Cancel any previous HA timer callback
        prev = self._override_timers.get(room_id)
        if prev and prev.get("cancel_cb"):
            prev["cancel_cb"]()

        expires_at = time.time() + (timeout_min * 60)
        self._override_timers[room_id] = {
            "expires_at": expires_at,
            "cancel_cb": cancel_cb,
        }
        _LOGGER.info("PassableSmartLighting [%s]: 🔒 Manual override ACTIVE for %s min", room_id, timeout_min)

    def clear_manual_override(self, room_id: str) -> None:
        """Clear manual override for a room."""
        prev = self._override_timers.pop(room_id, None)
        if prev and prev.get("cancel_cb"):
            try:
                prev["cancel_cb"]()
            except Exception:
                pass
        _LOGGER.info("PassableSmartLighting [%s]: 🔓 Manual override CLEARED", room_id)

    async def async_turn_on_light(
        self,
        room_id: str,
        light_entity: str,
        brightness_pct: int,
        circadian_enabled: bool,
        min_temp: int,
        max_temp: int,
        transition: float = 1.0,
    ) -> None:
        """Send turn_on command to Home Assistant light with echo guard."""
        current_state = self.hass.states.get(light_entity)
        start_pct = 0
        if current_state and current_state.state == "on":
            start_pct = int(round((current_state.attributes.get("brightness", 0) / 255.0) * 100))

        service_data: Dict[str, Any] = {
            "entity_id": light_entity,
            "brightness_pct": max(1, min(100, brightness_pct)),
            "transition": transition,
        }

        if circadian_enabled:
            kelvin = get_circadian_temp(self.hass, min_temp, max_temp)
            service_data["color_temp_kelvin"] = kelvin

        self.set_echo_guard(room_id, brightness_pct, start_pct, transition)
        await self.hass.services.async_call("light", "turn_on", service_data)

    async def async_turn_off_light(self, room_id: str, light_entity: str, transition: float = 2.0) -> None:
        """Send turn_off command to Home Assistant light with echo guard."""
        current_state = self.hass.states.get(light_entity)
        start_pct = 0
        if current_state and current_state.state == "on":
            start_pct = int(round((current_state.attributes.get("brightness", 0) / 255.0) * 100))

        self.set_echo_guard(room_id, 0, start_pct, transition)
        await self.hass.services.async_call(
            "light", "turn_off", {"entity_id": light_entity, "transition": transition}
        )

    async def async_sync_helper(self, entity_id: Optional[str], target_state: bool) -> None:
        """Synchronize an existing helper entity (e.g. input_boolean)."""
        if not entity_id or not isinstance(entity_id, str):
            return
        domain = entity_id.split(".")[0]
        svc = "turn_on" if target_state else "turn_off"
        try:
            curr = safe_get_state(self.hass, entity_id, "unknown")
            expected = "on" if target_state else "off"
            if curr != expected:
                await self.hass.services.async_call(domain, svc, {"entity_id": entity_id})
        except Exception as err:
            _LOGGER.debug("Could not sync helper entity %s: %s", entity_id, err)

    def is_late_night_active(
        self,
        enabled: bool,
        cond_type: str,
        entity_id: Optional[str],
        start_time_str: str,
        stop_time_str: str,
        start_entity: Optional[str] = None,
        stop_entity: Optional[str] = None,
    ) -> bool:
        """Determine if late night mode is currently active."""
        if not enabled:
            return False

        if cond_type == "entity_state" and entity_id:
            val = str(safe_get_state(self.hass, entity_id, "off")).lower()
            return val in ("on", "true", "home", "active")

        # Time evaluation
        now_dt = dt_util.now()
        now_t = now_dt.time()

        s_time_str = safe_get_state(self.hass, start_entity, start_time_str) if start_entity else start_time_str
        e_time_str = safe_get_state(self.hass, stop_entity, stop_time_str) if stop_entity else stop_time_str

        def _parse_time(t_str: Any, default_val: dtime) -> dtime:
            if not t_str or not isinstance(t_str, str):
                return default_val
            try:
                parts = [int(p) for p in t_str.strip().split(":")]
                if len(parts) == 2:
                    return dtime(parts[0], parts[1])
                if len(parts) >= 3:
                    return dtime(parts[0], parts[1], parts[2])
            except Exception:
                pass
            return default_val

        start_t = _parse_time(s_time_str, dtime(22, 0))
        stop_t = _parse_time(e_time_str, dtime(6, 0))

        if start_t <= stop_t:
            return start_t <= now_t <= stop_t
        # Overnight wrapping
        return now_t >= start_t or now_t <= stop_t

    def check_bypasses(self, freeze_entities: List[str], off_entities: List[str]) -> Tuple[bool, bool]:
        """Check if any freeze or force-off bypasses are active. Returns (is_frozen, is_off)."""
        is_frozen = False
        is_off = False

        for ent in freeze_entities:
            val = str(safe_get_state(self.hass, ent, "off")).lower()
            if val in ACTIVE_STATES:
                is_frozen = True
                break

        for ent in off_entities:
            val = str(safe_get_state(self.hass, ent, "off")).lower()
            if val in ACTIVE_STATES:
                is_off = True
                break

        return is_frozen, is_off

    def check_presence(self, presence_entities: List[str]) -> bool:
        """Check if any configured presence sensor is ON."""
        for ent in presence_entities:
            val = str(safe_get_state(self.hass, ent, "off")).lower()
            if val in ("on", "home", "true", "active"):
                return True
        return False

    def check_media(self, media_entities: List[str]) -> bool:
        """Check if any configured media player is active."""
        for ent in media_entities:
            val = str(safe_get_state(self.hass, ent, "off")).lower()
            if val in ACTIVE_STATES:
                return True
        return False

    async def async_handle_engine_cycle(self, params: Dict[str, Any]) -> None:
        """Execute one complete evaluation cycle for a room."""
        room_id = params.get("room_id", "default_room")
        async with self.get_lock(room_id):
            await self._async_execute_cycle(params)

    async def _async_execute_cycle(self, p: Dict[str, Any]) -> None:
        """Internal execution of lighting engine logic with all safety guards."""
        room_id = str(p.get("room_id", "default"))
        light_entity = str(p.get("light_entity", ""))
        lux_sensor = str(p.get("lux_sensor", ""))
        trigger_id = str(p.get("trigger_id", "none"))

        if not light_entity:
            return

        # Configuration unpacking
        presence_entities = p.get("presence_entity", [])
        if isinstance(presence_entities, str):
            presence_entities = [presence_entities] if presence_entities else []

        media_entities = p.get("media_entities", [])
        if isinstance(media_entities, str):
            media_entities = [media_entities] if media_entities else []

        bypass_freeze_entities = p.get("bypass_freeze_entities", [])
        if isinstance(bypass_freeze_entities, str):
            bypass_freeze_entities = [bypass_freeze_entities] if bypass_freeze_entities else []

        bypass_off_entities = p.get("bypass_off_entities", [])
        if isinstance(bypass_off_entities, str):
            bypass_off_entities = [bypass_off_entities] if bypass_off_entities else []

        target_lux_seed = float(p.get("target_lux", DEFAULT_TARGET_LUX))
        default_lux_ratio = float(p.get("default_lux_ratio", DEFAULT_LUX_RATIO))
        presence_timeout_min = int(p.get("presence_timeout_min", DEFAULT_PRESENCE_TIMEOUT_MIN))
        min_occupied_pct = int(p.get("min_occupied_pct", DEFAULT_MIN_OCCUPIED_PCT))
        circadian_enabled = bool(p.get("circadian_enabled", DEFAULT_CIRCADIAN_ENABLED))
        min_color_temp = int(p.get("min_color_temp", DEFAULT_MIN_COLOR_TEMP))
        max_color_temp = int(p.get("max_color_temp", DEFAULT_MAX_COLOR_TEMP))
        media_seed_pct = int(p.get("media_seed_pct", DEFAULT_MEDIA_SEED_PCT))
        override_timeout_min = int(p.get("override_timeout_min", DEFAULT_OVERRIDE_TIMEOUT_MIN))
        manual_override_entity = p.get("manual_override_entity")
        ignore_max_override = bool(p.get("ignore_max_brightness_override", DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE))

        late_night_enabled = bool(p.get("late_night_enabled", DEFAULT_LATE_NIGHT_ENABLED))
        late_night_pct = int(p.get("late_night_pct", DEFAULT_LATE_NIGHT_PCT))
        late_night_cond_type = str(p.get("late_night_condition_type", DEFAULT_LATE_NIGHT_CONDITION_TYPE))
        late_night_entity = p.get("late_night_entity")
        late_night_start_time = str(p.get("late_night_start_time", DEFAULT_LATE_NIGHT_START_TIME))
        late_night_start_entity = p.get("late_night_start_entity")
        late_night_stop_time = str(p.get("late_night_stop_time", DEFAULT_LATE_NIGHT_STOP_TIME))
        late_night_stop_entity = p.get("late_night_stop_entity")

        # Light current state
        light_state = self.hass.states.get(light_entity)
        is_light_on = light_state is not None and light_state.state == "on"
        current_pct = (
            int(round((light_state.attributes.get("brightness", 0) / 255.0) * 100))
            if is_light_on and light_state
            else 0
        )

        # 1. Power grid restoration protection
        grid_entity = p.get("power_grid_entity")
        if grid_entity:
            grid_entity_str = str(grid_entity).strip()
            if grid_entity_str and grid_entity_str.lower() != "none":
                grid_state = safe_get_state(self.hass, grid_entity_str, "on")
                if str(grid_state).lower() in ("off", "unavailable", "unknown"):
                    _LOGGER.debug("PassableSmartLighting [%s]: Power grid offline. Halting cycle.", room_id)
                    return

        # 2. Bypass check
        is_frozen, is_forced_off = self.check_bypasses(bypass_freeze_entities, bypass_off_entities)
        if is_forced_off:
            if is_light_on:
                _LOGGER.info("PassableSmartLighting [%s]: Force-off bypass active. Turning off lights.", room_id)
                await self.async_turn_off_light(room_id, light_entity)
            self.clear_manual_override(room_id)
            await self.async_sync_helper(manual_override_entity, False)
            return

        if is_frozen:
            _LOGGER.debug("PassableSmartLighting [%s]: Freeze bypass active. Holding current state.", room_id)
            return

        # 3. Hardware Echo Guard & Manual Override Detection
        if trigger_id == "light_change":
            if self.check_echo_guard(room_id, current_pct):
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Echo guard absorbed light change (%s%%)", room_id, current_pct
                )
                return

            # Detect manual override
            is_manual_action = True
            trigger_context_id = p.get("trigger_context_id", "none")
            trigger_user_id = p.get("trigger_user_id", "none")

            # Max brightness ignore rule (e.g. flicked switch to 100% to cancel bedtime)
            if ignore_max_override and current_pct >= 95 and p.get("trigger_from_state") == "off":
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Light turned on to 100%%. Bypassing override lock.", room_id
                )
                is_manual_action = False

            if is_manual_action and is_light_on:
                @callback
                def _on_override_expired() -> None:
                    self.clear_manual_override(room_id)
                    self.hass.async_create_task(self.async_sync_helper(manual_override_entity, False))
                    # Trigger a room re-evaluation
                    ctrl = self._controllers.get(room_id)
                    if ctrl:
                        self.hass.async_create_task(ctrl.async_evaluate("override_expired"))

                cancel_listener = async_call_later(
                    self.hass, override_timeout_min * 60, lambda _: _on_override_expired()
                )
                self.set_manual_override(room_id, override_timeout_min, cancel_listener)
                await self.async_sync_helper(manual_override_entity, True)

                # Trigger background learning from manual override
                self._schedule_preference_learning(room_id, lux_sensor, current_pct, p)
                return

            if not is_light_on:
                # Turned off manually
                self.clear_manual_override(room_id)
                await self.async_sync_helper(manual_override_entity, False)
                return

        # 4. Check if manual override is currently locked
        if self.is_manual_override_active(room_id):
            _LOGGER.debug("PassableSmartLighting [%s]: Manual override active. Skipping auto-adjustment.", room_id)
            return

        # 5. Presence & Vacancy Evaluation
        is_occupied = self.check_presence(presence_entities)

        if not is_occupied:
            # Vacancy timeout handling
            if trigger_id == "presence_off_timeout" or (
                trigger_id == "heartbeat" and not is_occupied and is_light_on
            ):
                _LOGGER.info("PassableSmartLighting [%s]: Vacancy timeout elapsed. Turning lights OFF.", room_id)
                await self.async_turn_off_light(room_id, light_entity)
                self.clear_manual_override(room_id)
                await self.async_sync_helper(manual_override_entity, False)
            return

        # 6. Mode & Target Calculation (Occupied Room)
        learning_data = self.store.data
        room_curves = learning_data.get("room_curves", {}).get(room_id, {})
        user_prefs = learning_data.get("user_prefs", {}).get(room_id, [])
        media_prefs = learning_data.get("media_prefs", {}).get(room_id, [])
        late_night_prefs = learning_data.get("late_night_prefs", {}).get(room_id, [])

        # Mode A: Media Playing
        if self.check_media(media_entities):
            target_pct = int(sum(media_prefs) / len(media_prefs)) if media_prefs else media_seed_pct
            if target_pct <= 0:
                if is_light_on:
                    await self.async_turn_off_light(room_id, light_entity)
                return
            if abs(current_pct - target_pct) >= 3:
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Media active. Setting lights to %s%% (learned/seed)",
                    room_id,
                    target_pct,
                )
                await self.async_turn_on_light(
                    room_id, light_entity, target_pct, circadian_enabled, min_color_temp, max_color_temp
                )
            return

        # Mode B: Late Night Mode
        if self.is_late_night_active(
            late_night_enabled,
            late_night_cond_type,
            late_night_entity,
            late_night_start_time,
            late_night_stop_time,
            late_night_start_entity,
            late_night_stop_entity,
        ):
            target_pct = (
                int(sum(late_night_prefs) / len(late_night_prefs)) if late_night_prefs else late_night_pct
            )
            if target_pct <= 0:
                if is_light_on:
                    await self.async_turn_off_light(room_id, light_entity)
                return
            if abs(current_pct - target_pct) >= 3:
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Late night mode active. Setting lights to %s%%",
                    room_id,
                    target_pct,
                )
                await self.async_turn_on_light(
                    room_id, light_entity, target_pct, circadian_enabled, min_color_temp, max_color_temp
                )
            return

        # Mode C: Daytime Ambient Lux Targeting
        sun_state = self.hass.states.get("sun.sun")
        elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
        target_lux = calculate_learned_target_lux(target_lux_seed, user_prefs, elev)
        current_lux = self.get_smoothed_lux(room_id, lux_sensor)

        needed_pct = calculate_required_pct(
            target_lux, current_lux, room_curves, default_lux_ratio, min_occupied_pct
        )

        # Check hysteresis
        pct_diff = abs(current_pct - needed_pct)
        if not is_light_on and needed_pct > 0:
            _LOGGER.info(
                "PassableSmartLighting [%s]: Occupancy detected. Turning lights ON to %s%% (Target Lux: %.1f, Current: %.1f)",
                room_id,
                needed_pct,
                target_lux,
                current_lux,
            )
            await self.async_turn_on_light(
                room_id, light_entity, needed_pct, circadian_enabled, min_color_temp, max_color_temp
            )
        elif is_light_on:
            if needed_pct == 0 and min_occupied_pct == 0:
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Ambient lux sufficient (%.1f >= %.1f). Turning lights OFF.",
                    room_id,
                    current_lux,
                    target_lux,
                )
                await self.async_turn_off_light(room_id, light_entity)
            elif pct_diff >= 4:
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Adjusting brightness from %s%% to %s%% (Target: %.1f, Lux: %.1f)",
                    room_id,
                    current_pct,
                    needed_pct,
                    target_lux,
                    current_lux,
                )
                await self.async_turn_on_light(
                    room_id, light_entity, needed_pct, circadian_enabled, min_color_temp, max_color_temp
                )

    def _schedule_preference_learning(
        self, room_id: str, lux_sensor: str, current_pct: int, p: Dict[str, Any]
    ) -> None:
        """Schedule asynchronous sensor lag compensation and preference saving."""
        if room_id in self._stabilizing_tasks:
            self._stabilizing_tasks[room_id].cancel()

        task = self.hass.async_create_task(
            self._async_stabilize_and_learn(room_id, lux_sensor, current_pct, p)
        )
        self._stabilizing_tasks[room_id] = task

    async def _async_stabilize_and_learn(
        self, room_id: str, lux_sensor: str, current_pct: int, p: Dict[str, Any]
    ) -> None:
        """Wait up to 120s for sensor lag compensation, filter flare, and save user preference."""
        try:
            lux_before = float(safe_get_state(self.hass, lux_sensor, 0.0))
            current_lux_str = str(safe_get_state(self.hass, lux_sensor, 0.0))

            _LOGGER.info(
                "PassableSmartLighting [%s]: ⏳ Waiting up to 120s for lux sensor to stabilize at %s%%...",
                room_id,
                current_pct,
            )

            # Wait for state change on lux sensor
            event_received = asyncio.Event()

            @callback
            def _lux_listener(evt: Event) -> None:
                new_st = evt.data.get("new_state")
                if new_st and new_st.state != current_lux_str:
                    event_received.set()

            unsub = async_track_state_change_event(self.hass, [lux_sensor], _lux_listener)
            try:
                await asyncio.wait_for(event_received.wait(), timeout=120.0)
            finally:
                unsub()

            # Wait an extra 2s for hardware report settling
            await asyncio.sleep(2.0)

            lux_after = float(safe_get_state(self.hass, lux_sensor, 0.0))
            if lux_after <= 0:
                _LOGGER.warning(
                    "PassableSmartLighting [%s]: Rejecting pref — lux_after is %.1f", room_id, lux_after
                )
                return

            smoothed = self.get_smoothed_lux(room_id, lux_sensor)
            if abs(lux_after - smoothed) > 20:
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Lux reading %.1f contaminated (smoothed=%.1f). Using smoothed.",
                    room_id,
                    lux_after,
                    smoothed,
                )
                lux_after = smoothed

            # Sun elevation
            sun_state = self.hass.states.get("sun.sun")
            elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0

            # Flare filter (M3)
            curve = self.store.data.get("room_curves", {}).get(room_id, {})
            seed_lux = float(p.get("target_lux", DEFAULT_TARGET_LUX))
            default_lux_ratio = float(p.get("default_lux_ratio", DEFAULT_LUX_RATIO))
            from_pct = float(p.get("trigger_from_brightness", 0))

            ambient_est = max(0.0, lux_before - get_expected_lux(curve, from_pct, default_lux_ratio))
            if ambient_est > seed_lux:
                artificial_at_new = get_expected_lux(curve, current_pct, default_lux_ratio)
                target_save_lux = artificial_at_new + seed_lux
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Flare filter — ambient_est=%.1f exceeds seed=%.1f. Saving %.1f instead of %.1f",
                    room_id,
                    ambient_est,
                    seed_lux,
                    target_save_lux,
                    lux_after,
                )
            else:
                target_save_lux = lux_after

            target_save_lux = max(1.0, min(target_save_lux, seed_lux * 2.0))

            # Store in preferences
            prefs = self.store.data.setdefault("user_prefs", {}).setdefault(room_id, [])
            prefs.append({"sun_elev": elev, "preferred_lux": target_save_lux})
            if len(prefs) > 50:
                prefs.pop(0)

            # Update yield curve data point
            curves = self.store.data.setdefault("room_curves", {}).setdefault(room_id, {})
            curves[str(current_pct)] = target_save_lux

            await self.store.async_save()
            _LOGGER.info(
                "PassableSmartLighting [%s]: 💾 Saved learned preference: Elev=%.1f°, Lux=%.1f at %s%%",
                room_id,
                elev,
                target_save_lux,
                current_pct,
            )

        except asyncio.TimeoutError:
            _LOGGER.warning("PassableSmartLighting [%s]: Lux sensor wait timed out. Discarding preference.", room_id)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.error("PassableSmartLighting [%s]: Error during preference learning: %s", room_id, err)
        finally:
            self._stabilizing_tasks.pop(room_id, None)


class RoomController:
    """Manages an individual room's lifecycle and event listeners when configured via native UI."""

    def __init__(self, hass: HomeAssistant, engine: PassableLightingEngine, entry_data: Dict[str, Any]) -> None:
        """Initialize room controller."""
        self.hass = hass
        self.engine = engine
        self.entry_data = entry_data
        self.room_id = entry_data[CONF_ROOM_ID]
        self._unsub_listeners: List[CALLBACK_TYPE] = []
        self._is_enabled = True
        self._freeze_bypass_active = False
        self._vacancy_task: Optional[asyncio.Task] = None
        self.selected_reset_target: str = "all"

    @property
    def is_enabled(self) -> bool:
        """Return whether automation is enabled for this room."""
        return self._is_enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable automation for this room."""
        self._is_enabled = enabled
        if not enabled:
            self.engine.clear_manual_override(self.room_id)
        else:
            self.hass.async_create_task(self.async_evaluate("enabled_toggle"))

    @property
    def freeze_bypass_active(self) -> bool:
        """Return dedicated freeze switch state."""
        return self._freeze_bypass_active

    def set_freeze_bypass(self, active: bool) -> None:
        """Set dedicated freeze switch state."""
        self._freeze_bypass_active = active

    async def async_start(self) -> None:
        """Start tracking state changes for this room."""
        light_entity = self.entry_data.get(CONF_LIGHT_ENTITY)
        lux_sensor = self.entry_data.get(CONF_LUX_SENSOR)
        presence_entities = self.entry_data.get(CONF_PRESENCE_ENTITIES, [])
        if isinstance(presence_entities, str):
            presence_entities = [presence_entities]
        elif presence_entities is None:
            presence_entities = []

        media_entities = self.entry_data.get(CONF_MEDIA_ENTITIES, [])
        if isinstance(media_entities, str):
            media_entities = [media_entities]
        elif media_entities is None:
            media_entities = []

        bypasses = list(self.entry_data.get(CONF_BYPASS_FREEZE_ENTITIES) or []) + list(
            self.entry_data.get(CONF_BYPASS_OFF_ENTITIES) or []
        )

        # Track presence changes
        if presence_entities:
            @callback
            def _on_presence_change(evt: Event) -> None:
                new_st = evt.data.get("new_state")
                old_st = evt.data.get("old_state")
                if not new_st:
                    return
                if new_st.state == "on":
                    if self._vacancy_task and not self._vacancy_task.done():
                        self._vacancy_task.cancel()
                    self.hass.async_create_task(self.async_evaluate("presence_on"))
                elif new_st.state == "off":
                    if not self.engine.check_presence(presence_entities):
                        timeout_m = int(self.entry_data.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN))
                        if self._vacancy_task and not self._vacancy_task.done():
                            self._vacancy_task.cancel()
                        self._vacancy_task = self.hass.async_create_task(self._async_schedule_vacancy_off(timeout_m))

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, presence_entities, _on_presence_change)
            )

        # Track light changes
        if light_entity:
            @callback
            def _on_light_change(evt: Event) -> None:
                new_st = evt.data.get("new_state")
                old_st = evt.data.get("old_state")
                from_b = old_st.attributes.get("brightness", 0) if old_st else 0
                from_s = old_st.state if old_st else "off"
                params = {
                    "trigger_id": "light_change",
                    "trigger_from_state": from_s,
                    "trigger_from_brightness": from_b,
                }
                self.hass.async_create_task(self.async_evaluate("light_change", params))

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, [light_entity], _on_light_change)
            )

        # Track lux changes
        if lux_sensor:
            @callback
            def _on_lux_change(evt: Event) -> None:
                self.hass.async_create_task(self.async_evaluate("lux_change"))

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, [lux_sensor], _on_lux_change)
            )

        # Track media changes
        if media_entities:
            @callback
            def _on_media_change(evt: Event) -> None:
                self.hass.async_create_task(self.async_evaluate("media_change"))

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, media_entities, _on_media_change)
            )

        # Track bypasses
        if bypasses:
            @callback
            def _on_bypass_change(evt: Event) -> None:
                self.hass.async_create_task(self.async_evaluate("bypass_change"))

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, bypasses, _on_bypass_change)
            )

        # Initial evaluation
        await self.async_evaluate("startup")

    async def _async_schedule_vacancy_off(self, timeout_minutes: int) -> None:
        """Schedule a delayed check to turn off lights after vacancy timeout."""
        presence_entities = self.entry_data.get(CONF_PRESENCE_ENTITIES, [])
        if isinstance(presence_entities, str):
            presence_entities = [presence_entities]

        try:
            await asyncio.sleep(timeout_minutes * 60)
            if not self.engine.check_presence(presence_entities):
                await self.async_evaluate("presence_off_timeout")
        except asyncio.CancelledError:
            pass

    async def async_evaluate(self, trigger_id: str, extra_params: Optional[Dict[str, Any]] = None) -> None:
        """Evaluate room state and dispatch to engine."""
        if not self._is_enabled:
            return

        params = dict(self.entry_data)
        params["trigger_id"] = trigger_id
        if extra_params:
            params.update(extra_params)

        # Inject internal freeze bypass state if active
        if self._freeze_bypass_active:
            freezes = list(params.get(CONF_BYPASS_FREEZE_ENTITIES, []))
            params["internal_freeze"] = True

        await self.engine.async_handle_engine_cycle(params)

    def stop(self) -> None:
        """Unsubscribe all active listeners."""
        if self._vacancy_task and not self._vacancy_task.done():
            self._vacancy_task.cancel()
        for unsub in self._unsub_listeners:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_listeners.clear()
