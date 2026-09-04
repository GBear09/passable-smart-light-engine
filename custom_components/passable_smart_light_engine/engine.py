"""Core algorithmic lighting engine for Passable Adaptive Smart Lighting Controller."""

import asyncio
from datetime import datetime, time as dtime, timedelta
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
import homeassistant.util.dt as dt_util

from .const import (
    ACTIVE_STATES,
    BRIGHTNESS_HYSTERESIS_PCT,
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
    DEFAULT_MESH_SETTLE_SEC,
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_MIN_OCCUPIED_PCT,
    DEFAULT_OVERRIDE_TIMEOUT_MIN,
    DEFAULT_POWER_GRID_ENTITY,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_TARGET_LUX,
    DOMAIN,
    DWELL_TIME_SEC,
    ECHO_CONVERGENCE_SETTLE_SEC,
    ECHO_GUARD_TOLERANCE_PCT,
    ECHO_GUARD_WINDOW_SEC,
    LUX_ADJUST_RATE_LIMIT_SEC,
    LUX_DEADBAND_PCT,
    MIN_LUX_DEADBAND,
    MIN_VISIBLE_PCT,
    OVERRIDE_FADE_TRANSITION_SEC,
    SENSOR_DEBOUNCE_SEC,
    STARTUP_SETTLE_SEC,
)
from .storage import LearningDataStore

_LOGGER = logging.getLogger(__name__)


def safe_get_state(hass: HomeAssistant, entity_id: Optional[str], default: Any = 0) -> Any:
    """Safely fetch an entity state or attribute."""
    if not entity_id or not isinstance(entity_id, str):
        return default
    try:
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
    seed_lux: float,
    user_prefs: List[Dict[str, Any]],
    current_elevation: float,
    current_azimuth: Optional[float] = None,
) -> float:
    """Blend seed lux with historical user preferences weighted by sun elevation and azimuth proximity."""
    if not user_prefs:
        return float(seed_lux)

    total_weight = 0.0
    weighted_lux = 0.0

    for pref in user_prefs:
        pref_elev = float(pref.get("sun_elev", 0.0))
        pref_lux = float(pref.get("preferred_lux", seed_lux))
        diff_elev = abs(current_elevation - pref_elev)

        pref_azim = pref.get("sun_azimuth")
        if current_azimuth is not None and pref_azim is not None:
            diff_azim = abs(current_azimuth - float(pref_azim))
            diff_azim = min(diff_azim, 360.0 - diff_azim)
            weight = math.exp(-0.5 * ((diff_elev / 15.0) ** 2 + (diff_azim / 45.0) ** 2))
        else:
            weight = math.exp(-0.5 * (diff_elev / 15.0) ** 2)

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
        self._pending_learning_handles: Dict[str, CALLBACK_TYPE] = {}
        self._last_ambient_adjust: Dict[str, float] = {}
        self._last_engine_target: Dict[str, int] = {}
        self._last_engine_command: Dict[str, float] = {}
        self._engine_contexts: Dict[str, float] = {}
        self._stabilizing_tasks: Dict[str, asyncio.Task] = {}
        self._controllers: Dict[str, "RoomController"] = {}

    def _cleanup_contexts(self) -> None:
        """Prune expired engine context IDs."""
        now = time.time()
        self._engine_contexts = {cid: exp for cid, exp in self._engine_contexts.items() if exp > now}

    def register_engine_context(self, context_id: str, ttl_sec: float) -> None:
        """Register an integration service call context ID with TTL."""
        self._engine_contexts[context_id] = time.time() + ttl_sec
        self._cleanup_contexts()

    def is_engine_context(self, context: Optional[Context]) -> bool:
        """Check if an event was triggered by an automated engine command."""
        if not context:
            return False
        self._cleanup_contexts()
        if context.id in self._engine_contexts:
            return True
        if context.parent_id and context.parent_id in self._engine_contexts:
            return True
        return False

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
        self, room_id: str, target_pct: int, start_pct: int, transition_sec: float = 1.0
    ) -> None:
        """Record an intended lighting adjustment for trajectory-bounded convergence guarding."""
        now = time.time()
        duration_sec = transition_sec + DEFAULT_MESH_SETTLE_SEC
        direction = 1 if target_pct > start_pct else (-1 if target_pct < start_pct else 0)
        self._echo_guards[room_id] = {
            "expires_at": now + duration_sec,
            "target_pct": target_pct,
            "start_pct": start_pct,
            "last_reported_pct": start_pct,
            "direction": direction,
            "settled_since": None,
            "timestamp": now,
        }

    def check_echo_guard(self, room_id: str, current_pct: int) -> bool:
        """Check if an incoming light state update is an echo of an automated change."""
        guard = self._echo_guards.get(room_id)
        now = time.time()

        if guard:
            if now > guard["expires_at"]:
                self._echo_guards.pop(room_id, None)
            else:
                target_pct = guard["target_pct"]
                start_pct = guard["start_pct"]
                tolerance = ECHO_GUARD_TOLERANCE_PCT

                min_p = min(start_pct, target_pct) - tolerance
                max_p = max(start_pct, target_pct) + tolerance

                # Check if current_pct falls within trajectory bounds
                if min_p <= current_pct <= max_p:
                    guard["last_reported_pct"] = current_pct
                    if abs(current_pct - target_pct) <= 3:
                        if guard["settled_since"] is None:
                            guard["settled_since"] = now
                        elif (now - guard["settled_since"]) >= ECHO_CONVERGENCE_SETTLE_SEC:
                            _LOGGER.debug(
                                "PassableSmartLighting [%s]: Hardware reached target %s%% and settled. Closing echo guard early.",
                                room_id,
                                target_pct,
                            )
                            self._echo_guards.pop(room_id, None)
                    else:
                        guard["settled_since"] = None
                    return True

        # Secondary check: If within mesh settle window of last command and close to target
        last_target = self._last_engine_target.get(room_id)
        last_cmd_time = self._last_engine_command.get(room_id, 0.0)
        if last_target is not None and (now - last_cmd_time) <= DEFAULT_MESH_SETTLE_SEC:
            if abs(current_pct - last_target) <= ECHO_GUARD_TOLERANCE_PCT:
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
        prev = self._override_timers.get(room_id)
        if prev and prev.get("cancel_cb"):
            try:
                prev["cancel_cb"]()
            except Exception:
                pass

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
        if prev:
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
        """Send turn_on command to Home Assistant light with echo guard and context tracking."""
        current_state = self.hass.states.get(light_entity)
        start_pct = 0
        if current_state and current_state.state == "on":
            start_pct = int(round((current_state.attributes.get("brightness", 0) / 255.0) * 100))

        clamped_pct = max(1, min(100, brightness_pct))
        service_data: Dict[str, Any] = {
            "entity_id": light_entity,
            "brightness_pct": clamped_pct,
            "transition": transition,
        }

        if circadian_enabled:
            kelvin = get_circadian_temp(self.hass, min_temp, max_temp)
            service_data["color_temp_kelvin"] = kelvin

        # Track HA Context and engine targets
        engine_context = Context()
        ttl = transition + DEFAULT_MESH_SETTLE_SEC + 5.0
        self.register_engine_context(engine_context.id, ttl)
        self._last_engine_target[room_id] = clamped_pct
        self._last_engine_command[room_id] = time.time()

        self.set_echo_guard(room_id, clamped_pct, start_pct, transition)
        await self.hass.services.async_call("light", "turn_on", service_data, context=engine_context)

    async def async_turn_off_light(self, room_id: str, light_entity: str, transition: float = 2.0) -> None:
        """Send turn_off command to Home Assistant light with echo guard and context tracking."""
        current_state = self.hass.states.get(light_entity)
        start_pct = 0
        if current_state and current_state.state == "on":
            start_pct = int(round((current_state.attributes.get("brightness", 0) / 255.0) * 100))

        # Track HA Context and engine targets
        engine_context = Context()
        ttl = transition + DEFAULT_MESH_SETTLE_SEC + 5.0
        self.register_engine_context(engine_context.id, ttl)
        self._last_engine_target[room_id] = 0
        self._last_engine_command[room_id] = time.time()

        self.set_echo_guard(room_id, 0, start_pct, transition)
        await self.hass.services.async_call(
            "light", "turn_off", {"entity_id": light_entity, "transition": transition}, context=engine_context
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
            evt_context = p.get("context")

            # A. Explicit Engine Context match
            if self.is_engine_context(evt_context):
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Echo guard absorbed light change via Context ID", room_id
                )
                return

            # B. Echo Guard Trajectory & Mesh Settle match
            if self.check_echo_guard(room_id, current_pct):
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Echo guard absorbed light change via Trajectory/Settling (%s%%)",
                    room_id,
                    current_pct,
                )
                return

            # C. Commanded Target match (within tolerance)
            last_target = self._last_engine_target.get(room_id)
            if last_target is not None and abs(current_pct - last_target) <= ECHO_GUARD_TOLERANCE_PCT:
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Absorbed report matching commanded target (%s%% ≈ %s%%)",
                    room_id,
                    current_pct,
                    last_target,
                )
                return

            # D. Startup Grace Period Filter (prevent false overrides during bridge/device reconnection)
            ctrl = self._controllers.get(room_id)
            if ctrl and (time.time() - ctrl.started_at) < STARTUP_SETTLE_SEC:
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Ignoring light change during startup grace period (%s%%)",
                    room_id,
                    current_pct,
                )
                return

            # E. Entity availability / restoration filter
            from_st = str(p.get("trigger_from_state", "")).lower()
            if from_st in ("unavailable", "unknown", "none"):
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Ignoring light change from uninitialized/restored state (%s)",
                    room_id,
                    from_st,
                )
                return

            # F. Determine if this is a genuine user manual action
            is_user_ui = evt_context and getattr(evt_context, "user_id", None) is not None
            is_physical_turn_on = (from_st == "off" and is_light_on)
            from_b = p.get("trigger_from_brightness", 0)
            from_pct = int(round((from_b / 255.0) * 100)) if from_b else 0
            is_physical_dim = (
                from_st == "on"
                and is_light_on
                and abs(current_pct - from_pct) >= BRIGHTNESS_HYSTERESIS_PCT
            )

            # If not UI, not physical toggle from off, not physical dimmer adjustment, and not turned off: ignore
            if not (is_user_ui or is_physical_turn_on or is_physical_dim or not is_light_on):
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Ignoring minor fluctuation or attribute report (pct=%s%%, from=%s%%)",
                    room_id,
                    current_pct,
                    from_pct,
                )
                return

            # Genuine manual action confirmed
            is_manual_action = True

            # Task full-brightness lock: when light is turned on to 100% from OFF by a physical switch or UI
            if ignore_max_override and current_pct >= 95 and from_st == "off":
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Light turned on to 100%% from off (Task full-brightness lock).", room_id
                )
                is_manual_action = True

            if is_manual_action and is_light_on:
                @callback
                def _on_override_expired() -> None:
                    self.clear_manual_override(room_id)
                    self.hass.async_create_task(self.async_sync_helper(manual_override_entity, False))
                    # Trigger a room re-evaluation with graceful cross-fade
                    c = self._controllers.get(room_id)
                    if c:
                        self.hass.async_create_task(
                            c.async_evaluate("override_expired", {"transition": OVERRIDE_FADE_TRANSITION_SEC})
                        )

                cancel_listener = async_call_later(
                    self.hass, override_timeout_min * 60, lambda _: _on_override_expired()
                )
                self.set_manual_override(room_id, override_timeout_min, cancel_listener)
                await self.async_sync_helper(manual_override_entity, True)

                # Trigger background learning from manual override with 180s dwell validation
                self._schedule_preference_learning(room_id, lux_sensor, current_pct, p)
                return

            if not is_light_on:
                # Turned off manually
                self.clear_manual_override(room_id)
                self.cancel_pending_learning(room_id)
                await self.async_sync_helper(manual_override_entity, False)
                return

        # 4. Check if manual override is currently locked
        if manual_override_entity:
            helper_val = str(safe_get_state(self.hass, manual_override_entity, "off")).lower()
            if helper_val in ("on", "true") and not self.is_manual_override_active(room_id):
                self.set_manual_override(room_id, override_timeout_min)
            elif helper_val in ("off", "false") and self.is_manual_override_active(room_id):
                self.clear_manual_override(room_id)

        if self.is_manual_override_active(room_id):
            _LOGGER.debug("PassableSmartLighting [%s]: Manual override active. Skipping auto-adjustment.", room_id)
            return

        # 5. Presence & Vacancy Evaluation
        is_occupied = self.check_presence(presence_entities) if presence_entities else True

        if not is_occupied:
            # Vacancy timeout handling
            if trigger_id == "presence_off_timeout" or (
                trigger_id == "heartbeat" and not is_occupied and is_light_on
            ):
                if is_light_on:
                    _LOGGER.info("PassableSmartLighting [%s]: Vacancy timeout elapsed. Turning lights OFF.", room_id)
                    await self.async_turn_off_light(room_id, light_entity)
                self.clear_manual_override(room_id)
                self.cancel_pending_learning(room_id)
                await self.async_sync_helper(manual_override_entity, False)
                return

            # Startup / Fail-Safe Vacancy Recovery:
            # If lights are on in an unoccupied room and no timer is currently running
            # (e.g. after Home Assistant reboot, reload, or missed event), recover countdown or turn off immediately.
            if is_light_on:
                ctrl = self._controllers.get(room_id)
                if ctrl and ctrl.vacancy_cancel is None:
                    timeout_sec = float(presence_timeout_min * 60)
                    remaining_sec = ctrl.get_vacancy_remaining_sec(presence_entities, timeout_sec)
                    if remaining_sec <= 0.0:
                        _LOGGER.info(
                            "PassableSmartLighting [%s]: Vacancy timeout elapsed while offline/reboot. Turning lights OFF immediately.",
                            room_id,
                        )
                        await self.async_turn_off_light(room_id, light_entity)
                        self.clear_manual_override(room_id)
                        self.cancel_pending_learning(room_id)
                        await self.async_sync_helper(manual_override_entity, False)
                    else:
                        _LOGGER.info(
                            "PassableSmartLighting [%s]: Unoccupied room with lights on detected on %s. Resuming vacancy timer (%.1fs remaining).",
                            room_id,
                            trigger_id,
                            remaining_sec,
                        )
                        ctrl.schedule_vacancy_timer(delay_sec=remaining_sec)
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
        azim = float(sun_state.attributes.get("azimuth", 0)) if sun_state and "azimuth" in sun_state.attributes else None
        target_lux = calculate_learned_target_lux(target_lux_seed, user_prefs, elev, azim)
        current_lux = self.get_smoothed_lux(room_id, lux_sensor)

        needed_pct = calculate_required_pct(
            target_lux, current_lux, room_curves, default_lux_ratio, min_occupied_pct
        )

        # Check hysteresis and deadbands
        pct_diff = abs(current_pct - needed_pct)
        lux_diff = abs(current_lux - target_lux)
        lux_deadband = max(MIN_LUX_DEADBAND, target_lux * LUX_DEADBAND_PCT)

        now_ts = time.time()
        last_adj = self._last_ambient_adjust.get(room_id, 0.0)
        time_since_last_adj = now_ts - last_adj

        if not is_light_on and needed_pct > 0:
            _LOGGER.info(
                "PassableSmartLighting [%s]: Occupancy detected. Turning lights ON to %s%% (Target Lux: %.1f, Current: %.1f)",
                room_id,
                needed_pct,
                target_lux,
                current_lux,
            )
            self._last_ambient_adjust[room_id] = now_ts
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
                self._last_ambient_adjust[room_id] = now_ts
                await self.async_turn_off_light(room_id, light_entity)
            elif pct_diff >= BRIGHTNESS_HYSTERESIS_PCT and lux_diff > lux_deadband:
                # Rate limit to prevent control hunting during passing clouds
                if time_since_last_adj < LUX_ADJUST_RATE_LIMIT_SEC and trigger_id == "lux_change":
                    _LOGGER.debug(
                        "PassableSmartLighting [%s]: Ambient adjustment rate-limited (%.1fs < %.1fs).",
                        room_id,
                        time_since_last_adj,
                        LUX_ADJUST_RATE_LIMIT_SEC,
                    )
                    return

                transition = float(p.get("transition", 1.0))
                _LOGGER.info(
                    "PassableSmartLighting [%s]: Adjusting brightness from %s%% to %s%% (Target: %.1f, Lux: %.1f, Trans: %.1fs)",
                    room_id,
                    current_pct,
                    needed_pct,
                    target_lux,
                    current_lux,
                    transition,
                )
                self._last_ambient_adjust[room_id] = now_ts
                await self.async_turn_on_light(
                    room_id,
                    light_entity,
                    needed_pct,
                    circadian_enabled,
                    min_color_temp,
                    max_color_temp,
                    transition=transition,
                )

    def cancel_pending_learning(self, room_id: str) -> None:
        """Cancel any scheduled preference learning for a room."""
        handle = self._pending_learning_handles.pop(room_id, None)
        if handle:
            try:
                handle()
            except Exception:
                pass
        task = self._stabilizing_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_preference_learning(
        self, room_id: str, lux_sensor: str, current_pct: int, p: Dict[str, Any]
    ) -> None:
        """Schedule preference learning with 180s dwell validation to filter transient adjustments."""
        self.cancel_pending_learning(room_id)

        @callback
        def _on_dwell_completed(_now: Any) -> None:
            self._pending_learning_handles.pop(room_id, None)
            task = self.hass.async_create_task(
                self._async_commit_learned_preference(room_id, lux_sensor, current_pct, p)
            )
            self._stabilizing_tasks[room_id] = task

        _LOGGER.debug(
            "PassableSmartLighting [%s]: Scheduled preference learning with %.0fs dwell validation",
            room_id,
            DWELL_TIME_SEC,
        )
        self._pending_learning_handles[room_id] = async_call_later(
            self.hass, DWELL_TIME_SEC, _on_dwell_completed
        )

    async def _async_commit_learned_preference(
        self, room_id: str, lux_sensor: str, current_pct: int, p: Dict[str, Any]
    ) -> None:
        """Commit learned user preference and update yield curves with daylight protection."""
        try:
            # 1. Verify light is still on and close to commanded percentage
            light_entity = p.get("light_entity")
            light_st = self.hass.states.get(light_entity) if light_entity else None
            if not light_st or light_st.state != "on":
                _LOGGER.debug("PassableSmartLighting [%s]: Light turned off during dwell; discarding preference.", room_id)
                return

            live_pct = int(round((light_st.attributes.get("brightness", 0) / 255.0) * 100))
            if abs(live_pct - current_pct) > 5:
                _LOGGER.debug("PassableSmartLighting [%s]: Light brightness altered during dwell; discarding preference.", room_id)
                return

            # 2. Get settled ambient lux (dwell time guarantees sensor lag has fully resolved)
            lux_now = self.get_smoothed_lux(room_id, lux_sensor)
            if lux_now <= 0:
                _LOGGER.warning("PassableSmartLighting [%s]: Rejecting pref — lux reading is %.1f", room_id, lux_now)
                return

            sun_state = self.hass.states.get("sun.sun")
            elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
            azim = float(sun_state.attributes.get("azimuth", 0)) if sun_state and "azimuth" in sun_state.attributes else None

            # 3. Store user preference
            prefs = self.store.data.setdefault("user_prefs", {}).setdefault(room_id, [])
            pref_entry: Dict[str, Any] = {
                "sun_elev": round(elev, 1),
                "preferred_lux": round(lux_now, 1),
            }
            if azim is not None:
                pref_entry["sun_azimuth"] = round(azim, 1)

            prefs.append(pref_entry)
            if len(prefs) > 50:
                prefs.pop(0)

            # 4. Yield Curve Update with Daylight Protection:
            # ONLY record yield curves during dark hours (sun elevation < -4°) where ambient daylight ~ 0.
            # During daylight, total lux includes sunlight which would severely contaminate the bulb yield curve.
            if elev < -4.0:
                curves = self.store.data.setdefault("room_curves", {}).setdefault(room_id, {})
                curves[str(current_pct)] = round(lux_now, 1)
                _LOGGER.info(
                    "PassableSmartLighting [%s]: 🌙 Dark hours yield curve updated: %s%% = %.1f lx",
                    room_id,
                    current_pct,
                    lux_now,
                )
            else:
                _LOGGER.debug(
                    "PassableSmartLighting [%s]: Daylight present (elev=%.1f°). Preserved yield curve from daylight contamination.",
                    room_id,
                    elev,
                )

            # Schedule delayed atomic save to eliminate flash wear
            self.store.schedule_save(delay=30.0)
            _LOGGER.info(
                "PassableSmartLighting [%s]: 💾 Saved learned preference: Elev=%.1f°, Lux=%.1f at %s%%",
                room_id,
                elev,
                lux_now,
                current_pct,
            )

        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.error("PassableSmartLighting [%s]: Error committing learned preference: %s", room_id, err)
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
        self._vacancy_cancel: Optional[CALLBACK_TYPE] = None
        self._debounce_cancel: Optional[CALLBACK_TYPE] = None
        self.selected_reset_target: str = "all"
        self.started_at: float = time.time()

    @property
    def is_enabled(self) -> bool:
        """Return whether automation is enabled for this room."""
        return self._is_enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable automation for this room."""
        self._is_enabled = enabled
        if not enabled:
            self.cancel_vacancy_timer()
            self.engine.clear_manual_override(self.room_id)
        else:
            self.schedule_evaluation("enabled_toggle", delay_sec=0.0)

    @property
    def vacancy_cancel(self) -> Optional[CALLBACK_TYPE]:
        """Return active vacancy timer cancel handle."""
        return self._vacancy_cancel

    def schedule_vacancy_timer(self, delay_sec: Optional[float] = None) -> None:
        """Arm or update the vacancy timeout countdown for this room."""
        presence_entities = self.entry_data.get(CONF_PRESENCE_ENTITIES, [])
        if isinstance(presence_entities, str):
            presence_entities = [presence_entities] if presence_entities else []
        elif presence_entities is None:
            presence_entities = []

        timeout_m = int(self.entry_data.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN))
        default_delay = max(1.0, float(timeout_m * 60))

        if delay_sec is None:
            delay_sec = default_delay

        if self._vacancy_cancel:
            self._vacancy_cancel()
            self._vacancy_cancel = None

        @callback
        def _on_vacancy_timeout(_now: Any) -> None:
            self._vacancy_cancel = None
            if not self.engine.check_presence(presence_entities):
                self.schedule_evaluation("presence_off_timeout", delay_sec=0.0)

        self._vacancy_cancel = async_call_later(self.hass, max(0.5, delay_sec), _on_vacancy_timeout)

    def cancel_vacancy_timer(self) -> None:
        """Cancel active vacancy timer."""
        if self._vacancy_cancel:
            self._vacancy_cancel()
            self._vacancy_cancel = None

    def get_vacancy_remaining_sec(self, presence_entities: List[str], timeout_sec: float) -> float:
        """Calculate remaining vacancy countdown based on presence entity last_changed timestamps."""
        if not presence_entities:
            return 0.0

        now = dt_util.utcnow()
        most_recent_off_ts: Optional[datetime] = None

        for ent in presence_entities:
            st = self.hass.states.get(ent)
            if not st:
                continue
            if st.state in ("on", "home", "true", "active"):
                # Room is occupied
                return timeout_sec
            if st.last_changed:
                lc = st.last_changed
                if lc.tzinfo is None:
                    lc = dt_util.as_utc(lc)
                if most_recent_off_ts is None or lc > most_recent_off_ts:
                    most_recent_off_ts = lc

        if most_recent_off_ts is not None:
            elapsed = (now - most_recent_off_ts).total_seconds()
            remaining = timeout_sec - elapsed
            return max(0.0, remaining)

        return timeout_sec

    @property
    def freeze_bypass_active(self) -> bool:
        """Return dedicated freeze switch state."""
        return self._freeze_bypass_active

    def set_freeze_bypass(self, active: bool) -> None:
        """Set dedicated freeze switch state."""
        self._freeze_bypass_active = active

    def schedule_evaluation(
        self, trigger_id: str, extra_params: Optional[Dict[str, Any]] = None, delay_sec: float = SENSOR_DEBOUNCE_SEC
    ) -> None:
        """Debounce room evaluations to coalesce bursts of sensor events and prevent mesh flooding."""
        if self._debounce_cancel:
            self._debounce_cancel()
            self._debounce_cancel = None

        @callback
        def _execute(_now: Any) -> None:
            self._debounce_cancel = None
            self.hass.async_create_task(self.async_evaluate(trigger_id, extra_params))

        if delay_sec <= 0:
            _execute(None)
        else:
            self._debounce_cancel = async_call_later(self.hass, delay_sec, _execute)

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
                if not new_st:
                    return
                if new_st.state in ("on", "home", "true", "active"):
                    self.cancel_vacancy_timer()
                    self.schedule_evaluation("presence_on", delay_sec=0.1)
                elif new_st.state in ("off", "not_home", "false"):
                    if not self.engine.check_presence(presence_entities):
                        self.schedule_vacancy_timer()

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, presence_entities, _on_presence_change)
            )

        # Track light changes (with context forwarding)
        if light_entity:
            @callback
            def _on_light_change(evt: Event) -> None:
                new_st = evt.data.get("new_state")
                old_st = evt.data.get("old_state")
                if not new_st or not old_st:
                    return

                # Ignore transitions when entity was or became unavailable/unknown (e.g. startup / reconnection)
                if old_st.state in ("unavailable", "unknown") or new_st.state in ("unavailable", "unknown"):
                    return

                # Ignore duplicate / no-op events
                old_b = old_st.attributes.get("brightness", 0) if old_st else 0
                new_b = new_st.attributes.get("brightness", 0) if new_st else 0
                if old_st.state == new_st.state and old_b == new_b:
                    return

                params = {
                    "trigger_id": "light_change",
                    "trigger_from_state": old_st.state,
                    "trigger_from_brightness": old_b,
                    "context": evt.context,
                }
                # Minimal debounce to capture rapid multi-bulb Zigbee reports
                self.schedule_evaluation("light_change", params, delay_sec=0.05)

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, [light_entity], _on_light_change)
            )

        # Track lux changes (with sensor debounce)
        if lux_sensor:
            @callback
            def _on_lux_change(evt: Event) -> None:
                self.schedule_evaluation("lux_change", delay_sec=SENSOR_DEBOUNCE_SEC)

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, [lux_sensor], _on_lux_change)
            )

        # Track media changes
        if media_entities:
            @callback
            def _on_media_change(evt: Event) -> None:
                self.schedule_evaluation("media_change", delay_sec=SENSOR_DEBOUNCE_SEC)

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, media_entities, _on_media_change)
            )

        # Track bypasses
        if bypasses:
            @callback
            def _on_bypass_change(evt: Event) -> None:
                self.schedule_evaluation("bypass_change", delay_sec=0.1)

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, bypasses, _on_bypass_change)
            )

        # Initial evaluation
        await self.async_evaluate("startup")

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
            params["internal_freeze"] = True

        await self.engine.async_handle_engine_cycle(params)

    def stop(self) -> None:
        """Unsubscribe all active listeners and cancel pending timers."""
        self.cancel_vacancy_timer()
        if self._debounce_cancel:
            self._debounce_cancel()
            self._debounce_cancel = None
        for unsub in self._unsub_listeners:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_listeners.clear()
