"""Holiday Lighting Coordinator for Passable Adaptive Smart Lighting Controller."""

import asyncio
import copy
from datetime import datetime, time as dtime, timedelta
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .const import (
    ACTIVE_HOLIDAY_SENSOR_ENTITY_ID,
    CONF_HOLIDAY_DECORATIONS_ENABLED,
    CONF_HOLIDAY_GLOBAL_DECORATIONS,
    CONF_HOLIDAY_GLOBAL_LABEL,
    CONF_HOLIDAY_GLOBAL_LIGHTS,
    CONF_HOLIDAY_HOME_STATE_ENTITY,
    CONF_HOLIDAY_LIGHTING_ENABLED,
    CONF_HOLIDAY_OFF_TIME,
    CONF_HOLIDAY_OFF_TRIGGER,
    CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
    CONF_HOLIDAY_SUNRISE_OFFSET_MIN,
    CONF_HOLIDAY_SUNSET_OFFSET_MIN,
    DEFAULT_HOLIDAY_DECORATIONS_ENABLED,
    DEFAULT_HOLIDAY_GLOBAL_DECORATIONS,
    DEFAULT_HOLIDAY_GLOBAL_LABEL,
    DEFAULT_HOLIDAY_GLOBAL_LIGHTS,
    DEFAULT_HOLIDAY_HOME_STATE_ENTITY,
    DEFAULT_HOLIDAY_LIGHTING_ENABLED,
    DEFAULT_HOLIDAY_OFF_TIME,
    DEFAULT_HOLIDAY_OFF_TRIGGER,
    DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
    DEFAULT_HOLIDAY_SUNRISE_OFFSET_MIN,
    DEFAULT_HOLIDAY_SUNSET_OFFSET_MIN,
    DEFAULT_HOLIDAYS,
    DOMAIN,
    HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
    HOLIDAY_STORAGE_KEY,
    HOLIDAY_STORAGE_VERSION,
    LIGHT_MODE_COLOR_TEMP,
    LIGHT_MODE_EFFECT,
    LIGHT_MODE_HUE_SCENE,
    LIGHT_MODE_RGB,
    MODE_HOLIDAY,
)

if TYPE_CHECKING:
    from .engine import PassableLightingEngine, RoomController

_LOGGER = logging.getLogger(__name__)


def parse_date_str(date_str: str) -> Tuple[int, int]:
    """Parse 'MM-DD' string into (month, day) integers."""
    try:
        parts = date_str.strip().split("-")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 1, 1


def is_date_in_range(now_m: int, now_d: int, sm: int, sd: int, em: int, ed: int) -> bool:
    """Check if current month and day falls between start and end dates."""
    start = (sm, sd)
    end = (em, ed)
    curr = (now_m, now_d)
    if start <= end:
        return start <= curr <= end
    # Range wraps around the new year (e.g., Dec 31 to Jan 1)
    return curr >= start or curr <= end


class HolidayStore:
    """Manages asynchronous persistence for Holiday Lighting configurations and catalog."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize holiday store."""
        self.hass = hass
        self._store = Store(hass, HOLIDAY_STORAGE_VERSION, HOLIDAY_STORAGE_KEY)
        self._data: Dict[str, Any] = {
            "options": {
                CONF_HOLIDAY_LIGHTING_ENABLED: DEFAULT_HOLIDAY_LIGHTING_ENABLED,
                CONF_HOLIDAY_DECORATIONS_ENABLED: DEFAULT_HOLIDAY_DECORATIONS_ENABLED,
                CONF_HOLIDAY_GLOBAL_LIGHTS: copy.deepcopy(DEFAULT_HOLIDAY_GLOBAL_LIGHTS),
                CONF_HOLIDAY_GLOBAL_DECORATIONS: copy.deepcopy(DEFAULT_HOLIDAY_GLOBAL_DECORATIONS),
                CONF_HOLIDAY_GLOBAL_LABEL: DEFAULT_HOLIDAY_GLOBAL_LABEL,
                CONF_HOLIDAY_SUNSET_OFFSET_MIN: DEFAULT_HOLIDAY_SUNSET_OFFSET_MIN,
                CONF_HOLIDAY_SUNRISE_OFFSET_MIN: DEFAULT_HOLIDAY_SUNRISE_OFFSET_MIN,
                CONF_HOLIDAY_HOME_STATE_ENTITY: DEFAULT_HOLIDAY_HOME_STATE_ENTITY,
                CONF_HOLIDAY_OFF_TRIGGER: DEFAULT_HOLIDAY_OFF_TRIGGER,
                CONF_HOLIDAY_OFF_TIME: DEFAULT_HOLIDAY_OFF_TIME,
                CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION: DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
            },
            "holidays": copy.deepcopy(DEFAULT_HOLIDAYS),
        }
        self._update_listeners: List[Callable[[], None]] = []

    @property
    def options(self) -> Dict[str, Any]:
        """Return global options dictionary."""
        return self._data.get("options", {})

    @property
    def holidays(self) -> Dict[str, Any]:
        """Return all holiday definitions."""
        return self._data.get("holidays", {})

    def register_update_listener(self, listener: Callable[[], None]) -> None:
        """Register a callback for storage changes."""
        if listener not in self._update_listeners:
            self._update_listeners.append(listener)

    def _notify_listeners(self) -> None:
        """Notify registered listeners."""
        for listener in self._update_listeners:
            try:
                listener()
            except Exception as err:
                _LOGGER.error("PassableSmartLighting: Error notifying holiday store listener: %s", err)

    async def async_load(self) -> None:
        """Load stored holiday catalog and settings."""
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            # Merge with defaults to ensure any new keys exist
            saved_options = stored.get("options", {})
            for k, v in self._data["options"].items():
                if k not in saved_options:
                    saved_options[k] = v
            self._data["options"] = saved_options

            saved_holidays = stored.get("holidays", {})
            if not saved_holidays:
                self._data["holidays"] = copy.deepcopy(DEFAULT_HOLIDAYS)
            else:
                self._data["holidays"] = saved_holidays

            _LOGGER.info(
                "PassableSmartLighting: Loaded %d holiday definitions from storage.",
                len(self._data["holidays"]),
            )
        else:
            _LOGGER.info("PassableSmartLighting: Initialized default holiday catalog.")
            await self.async_save()

        self._notify_listeners()

    async def async_save(self) -> None:
        """Persist current holiday settings to storage."""
        await self._store.async_save(self._data)
        self._notify_listeners()

    def update_options(self, new_options: Dict[str, Any]) -> None:
        """Update global options."""
        self._data["options"].update(new_options)

    def set_holiday(self, holiday_id: str, holiday_data: Dict[str, Any]) -> None:
        """Add or update a holiday definition."""
        self._data["holidays"][holiday_id] = holiday_data

    def delete_holiday(self, holiday_id: str) -> None:
        """Remove a holiday definition."""
        self._data["holidays"].pop(holiday_id, None)

    def reset_defaults(self) -> None:
        """Reset holiday catalog to factory defaults."""
        self._data["holidays"] = copy.deepcopy(DEFAULT_HOLIDAYS)


class HolidayLightingCoordinator:
    """Central coordinator for dynamic, multi-light holiday lighting and effects."""

    def __init__(self, hass: HomeAssistant, engine: "PassableLightingEngine", store: HolidayStore) -> None:
        """Initialize the holiday coordinator."""
        self.hass = hass
        self.engine = engine
        self.store = store

        self._is_active: bool = False
        self._active_holiday: Optional[Dict[str, Any]] = None
        self._preview_holiday: Optional[Dict[str, Any]] = None
        self._active_lights: Set[str] = set()
        self._active_decorations: Set[str] = set()
        self._unsub_listeners: List[CALLBACK_TYPE] = []
        self._midnight_unsub: Optional[CALLBACK_TYPE] = None

        self._master_switch_entity: Any = None
        self._decorations_switch_entity: Any = None
        self._sensor_entity: Any = None

    @property
    def enabled(self) -> bool:
        """Return True if holiday lighting master feature is enabled."""
        return bool(self.store.options.get(CONF_HOLIDAY_LIGHTING_ENABLED, DEFAULT_HOLIDAY_LIGHTING_ENABLED))

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable master holiday lighting feature."""
        if self.enabled == enabled:
            return
        self.store.update_options({CONF_HOLIDAY_LIGHTING_ENABLED: enabled})
        await self.store.async_save()
        _LOGGER.info("PassableSmartLighting: Holiday lighting enabled changed to %s", enabled)
        if not enabled and self._is_active:
            await self.async_turn_off_holiday_lighting()
        self._update_entities()

    @property
    def decorations_enabled(self) -> bool:
        """Return True if holiday decoration plugs feature is enabled."""
        return bool(self.store.options.get(CONF_HOLIDAY_DECORATIONS_ENABLED, DEFAULT_HOLIDAY_DECORATIONS_ENABLED))

    async def async_set_decorations_enabled(self, enabled: bool) -> None:
        """Enable or disable holiday decorations plugs."""
        if self.decorations_enabled == enabled:
            return
        self.store.update_options({CONF_HOLIDAY_DECORATIONS_ENABLED: enabled})
        await self.store.async_save()
        _LOGGER.info("PassableSmartLighting: Holiday decorations enabled changed to %s", enabled)
        if not enabled and self._active_decorations:
            await self._async_turn_off_decorations()
        elif enabled and self._is_active:
            await self._async_turn_on_decorations()
        self._update_entities()

    @property
    def is_active(self) -> bool:
        """Return True if holiday lighting is currently active."""
        return self._is_active

    @property
    def active_holiday(self) -> Optional[Dict[str, Any]]:
        """Return current active or preview holiday definition."""
        return self._preview_holiday or self._active_holiday

    @property
    def active_lights(self) -> List[str]:
        """Return list of light entities currently controlled by holiday lighting."""
        return sorted(list(self._active_lights))

    @property
    def active_decorations(self) -> List[str]:
        """Return list of decoration entities currently controlled by holiday lighting."""
        return sorted(list(self._active_decorations))

    def is_light_active(self, entity_id: Optional[str]) -> bool:
        """Check if an entity is currently actively controlled by holiday lighting."""
        if not entity_id or not self._is_active:
            return False
        return entity_id in self._active_lights

    def register_entities(self, master_switch: Any = None, decor_switch: Any = None, sensor: Any = None) -> None:
        """Link entity objects for live state updates."""
        if master_switch:
            self._master_switch_entity = master_switch
        if decor_switch:
            self._decorations_switch_entity = decor_switch
        if sensor:
            self._sensor_entity = sensor

    def _update_entities(self) -> None:
        """Notify registered entities to refresh HA state."""
        if self._master_switch_entity:
            self._master_switch_entity.async_write_ha_state()
        if self._decorations_switch_entity:
            self._decorations_switch_entity.async_write_ha_state()
        if self._sensor_entity:
            self._sensor_entity.async_write_ha_state()

    def evaluate_active_holiday(self, target_dt: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Determine which holiday is active based on calendar date."""
        now = target_dt or dt_util.now()
        now_m = now.month
        now_d = now.day

        holidays = self.store.holidays
        matching_holidays: List[Dict[str, Any]] = []

        for h in holidays.values():
            if not h.get("enabled", True):
                continue
            start_str = h.get("start_date", "")
            end_str = h.get("end_date", "")
            if not start_str or not end_str:
                continue
            sm, sd = parse_date_str(start_str)
            em, ed = parse_date_str(end_str)
            if is_date_in_range(now_m, now_d, sm, sd, em, ed):
                matching_holidays.append(h)

        if not matching_holidays:
            return None

        # If multiple match, pick the one with the narrower active window (most specific)
        def _duration_days(h: Dict[str, Any]) -> int:
            sm, sd = parse_date_str(h["start_date"])
            em, ed = parse_date_str(h["end_date"])
            if (sm, sd) <= (em, ed):
                return (em - sm) * 31 + (ed - sd)
            return (12 - sm + em) * 31 + (ed - sd)

        matching_holidays.sort(key=_duration_days)
        return matching_holidays[0]

    async def async_start(self) -> None:
        """Start holiday coordinator listeners and evaluate initial state."""
        self._active_holiday = self.evaluate_active_holiday()
        _LOGGER.info(
            "PassableSmartLighting: Holiday coordinator started. Active Holiday: %s",
            self._active_holiday["name"] if self._active_holiday else "None",
        )

        # 1. Listen to sun elevation changes
        @callback
        def _handle_sun_change(event: Event) -> None:
            self.hass.async_create_task(self._async_evaluate_schedule_trigger())

        self._unsub_listeners.append(
            async_track_state_change_event(self.hass, ["sun.sun"], _handle_sun_change)
        )

        # 2. Listen to home state changes (Sleep, Morning, Night, Pre-Sleep)
        home_state_entity = self.store.options.get(CONF_HOLIDAY_HOME_STATE_ENTITY, DEFAULT_HOLIDAY_HOME_STATE_ENTITY)
        if home_state_entity:
            @callback
            def _handle_home_state_change(event: Event) -> None:
                self.hass.async_create_task(self._async_evaluate_schedule_trigger())

            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, [home_state_entity], _handle_home_state_change)
            )

        # 3. Schedule midnight date check
        self._schedule_midnight_check()

        # Initial schedule check
        await self._async_evaluate_schedule_trigger()

    def _schedule_midnight_check(self) -> None:
        """Schedule check shortly past midnight to advance holidays."""
        now = dt_util.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        delay = (next_midnight - now).total_seconds()

        @callback
        def _midnight_fired(_now: Any) -> None:
            self._active_holiday = self.evaluate_active_holiday()
            self._update_entities()
            self.hass.async_create_task(self._async_evaluate_schedule_trigger())
            self._schedule_midnight_check()

        self._midnight_unsub = async_call_later(self.hass, max(5.0, delay), _midnight_fired)

    async def _async_evaluate_schedule_trigger(self) -> None:
        """Evaluate if holiday lights should turn on, turn off, or update."""
        if not self.enabled:
            if self._is_active:
                await self.async_turn_off_holiday_lighting()
            return

        current_holiday = self.active_holiday
        if not current_holiday:
            if self._is_active:
                await self.async_turn_off_holiday_lighting()
            return

        # Check conditions for turning on
        sun_state = self.hass.states.get("sun.sun")
        elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
        is_sun_down = elev < -1.0  # At or below sunset

        home_state_entity = self.store.options.get(CONF_HOLIDAY_HOME_STATE_ENTITY, DEFAULT_HOLIDAY_HOME_STATE_ENTITY)
        home_state = None
        if home_state_entity:
            st = self.hass.states.get(home_state_entity)
            if st and st.state:
                home_state = str(st.state).lower()

        # Home state sleep check
        is_sleeping = home_state == "sleep"

        # Check off trigger
        off_trigger = self.store.options.get(CONF_HOLIDAY_OFF_TRIGGER, DEFAULT_HOLIDAY_OFF_TRIGGER)
        should_be_on = False

        if is_sun_down:
            if off_trigger == "sleep":
                should_be_on = not is_sleeping
            elif off_trigger == "sunrise":
                should_be_on = True
            elif off_trigger == "fixed_time":
                off_time_str = self.store.options.get(CONF_HOLIDAY_OFF_TIME, DEFAULT_HOLIDAY_OFF_TIME)
                try:
                    parts = off_time_str.split(":")
                    off_time = dtime(int(parts[0]), int(parts[1]))
                    now_time = dt_util.now().time()
                    if now_time < off_time or elev < -15.0:
                        should_be_on = True
                except Exception:
                    should_be_on = not is_sleeping
            else:
                should_be_on = not is_sleeping

        if should_be_on and not self._is_active:
            _LOGGER.info(
                "PassableSmartLighting: Holiday schedule triggered ON for '%s'.",
                current_holiday["name"],
            )
            await self.async_turn_on_holiday_lighting()
        elif not should_be_on and self._is_active:
            _LOGGER.info(
                "PassableSmartLighting: Holiday schedule triggered OFF for '%s'.",
                current_holiday["name"],
            )
            await self.async_turn_off_holiday_lighting()

    def resolve_participating_lights(self, holiday: Dict[str, Any]) -> List[str]:
        """Resolve all participating lights for a given holiday."""
        lights = holiday.get("participating_lights") or self.store.options.get(
            CONF_HOLIDAY_GLOBAL_LIGHTS, DEFAULT_HOLIDAY_GLOBAL_LIGHTS
        )
        if isinstance(lights, str):
            lights = [lights]

        resolved: Set[str] = set()
        for item in lights:
            if item and isinstance(item, str):
                resolved.add(item.strip())

        # Also resolve any light tagged with global label
        target_label = self.store.options.get(CONF_HOLIDAY_GLOBAL_LABEL, DEFAULT_HOLIDAY_GLOBAL_LABEL)
        if target_label:
            reg = er.async_get(self.hass)
            for entry in reg.entities.values():
                if entry.domain == "light" and not entry.disabled and target_label in entry.labels:
                    resolved.add(entry.entity_id)

        return sorted(list(resolved))

    def resolve_participating_decorations(self, holiday: Dict[str, Any]) -> List[str]:
        """Resolve all participating decoration switches/plugs."""
        decorations = holiday.get("participating_decorations") or self.store.options.get(
            CONF_HOLIDAY_GLOBAL_DECORATIONS, DEFAULT_HOLIDAY_GLOBAL_DECORATIONS
        )
        if isinstance(decorations, str):
            decorations = [decorations]

        resolved: Set[str] = set()
        for item in decorations:
            if item and isinstance(item, str):
                resolved.add(item.strip())

        target_label = self.store.options.get(CONF_HOLIDAY_GLOBAL_LABEL, DEFAULT_HOLIDAY_GLOBAL_LABEL)
        if target_label:
            reg = er.async_get(self.hass)
            for entry in reg.entities.values():
                if entry.domain == "switch" and not entry.disabled and target_label in entry.labels:
                    resolved.add(entry.entity_id)

        return sorted(list(resolved))

    async def async_turn_on_holiday_lighting(self, preview_holiday: Optional[Dict[str, Any]] = None) -> None:
        """Actuate lights and decorations for the active or preview holiday."""
        holiday = preview_holiday or self.active_holiday
        if not holiday:
            _LOGGER.debug("PassableSmartLighting: No active holiday to turn on.")
            return

        ctx = Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)

        target_lights = self.resolve_participating_lights(holiday)
        mode = holiday.get("light_mode", LIGHT_MODE_RGB)
        brightness_pct = int(holiday.get("brightness_pct", 100))

        _LOGGER.info(
            "PassableSmartLighting: Actuating holiday '%s' across %d light(s) using mode '%s'.",
            holiday["name"],
            len(target_lights),
            mode,
        )

        for light_id in target_lights:
            # Check presence simulation arbitration
            if self.store.options.get(CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION, True):
                if self.engine.is_simulating_presence(light_id):
                    _LOGGER.debug(
                        "PassableSmartLighting: Light '%s' is simulating presence; skipping holiday actuation.",
                        light_id,
                    )
                    continue

            self._active_lights.add(light_id)
            success = False

            # Mode 1: Hue Dynamic Scene
            if mode == LIGHT_MODE_HUE_SCENE and holiday.get("hue_scene"):
                scene_id = holiday["hue_scene"].strip()
                scene_state = self.hass.states.get(scene_id)
                if scene_state:
                    try:
                        # Attempt native Hue activate_scene with dynamic=True
                        if self.hass.services.has_service("hue", "activate_scene"):
                            await self.hass.services.async_call(
                                "hue",
                                "activate_scene",
                                {"dynamic": bool(holiday.get("dynamic_scene", True))},
                                target={"entity_id": scene_id},
                                context=ctx,
                            )
                        else:
                            await self.hass.services.async_call(
                                "scene", "turn_on", target={"entity_id": scene_id}, context=ctx
                            )
                        success = True
                        _LOGGER.debug("PassableSmartLighting: Activated Hue scene '%s' for '%s'.", scene_id, light_id)
                    except Exception as err:
                        _LOGGER.warning(
                            "PassableSmartLighting: Failed to activate Hue scene '%s': %s. Falling back.",
                            scene_id,
                            err,
                        )

            # Mode 2: Hardware Bulb Effect (e.g. fire, candle, prism)
            if not success and (mode == LIGHT_MODE_EFFECT or holiday.get("fallback_effect")):
                effect_name = holiday.get("effect") or holiday.get("fallback_effect")
                if effect_name:
                    try:
                        await self.hass.services.async_call(
                            "light",
                            "turn_on",
                            {
                                ATTR_ENTITY_ID: light_id,
                                "effect": effect_name,
                                "brightness_pct": brightness_pct,
                            },
                            context=ctx,
                        )
                        success = True
                        _LOGGER.debug("PassableSmartLighting: Applied effect '%s' to '%s'.", effect_name, light_id)
                    except Exception as err:
                        _LOGGER.warning("PassableSmartLighting: Failed to apply effect '%s' to '%s': %s", effect_name, light_id, err)

            # Mode 3: Color Temp (Kelvin)
            if not success and mode == LIGHT_MODE_COLOR_TEMP:
                kelvin = int(holiday.get("color_temp_kelvin", 2000))
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {
                            ATTR_ENTITY_ID: light_id,
                            "color_temp_kelvin": kelvin,
                            "brightness_pct": brightness_pct,
                        },
                        context=ctx,
                    )
                    success = True
                except Exception as err:
                    _LOGGER.warning("PassableSmartLighting: Failed to set kelvin on '%s': %s", light_id, err)

            # Mode 4: Standard RGB Color (Default fallback)
            if not success:
                rgb = holiday.get("rgb_color", [255, 209, 163])
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {
                            ATTR_ENTITY_ID: light_id,
                            "rgb_color": rgb,
                            "brightness_pct": brightness_pct,
                        },
                        context=ctx,
                    )
                except Exception as err:
                    _LOGGER.error("PassableSmartLighting: Failed to turn on light '%s': %s", light_id, err)

        # Actuate decoration plugs if enabled
        if self.decorations_enabled and holiday.get("decorations_on", True):
            await self._async_turn_on_decorations(ctx)

        self._is_active = True
        self._update_entities()

    async def _async_turn_on_decorations(self, context: Optional[Context] = None) -> None:
        """Turn on all participating decoration plugs."""
        holiday = self.active_holiday
        if not holiday:
            return
        ctx = context or Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)

        decorations = self.resolve_participating_decorations(holiday)
        for dec_id in decorations:
            self._active_decorations.add(dec_id)
            try:
                await self.hass.services.async_call(
                    "homeassistant", "turn_on", {ATTR_ENTITY_ID: dec_id}, context=ctx
                )
            except Exception as err:
                _LOGGER.error("PassableSmartLighting: Failed to turn on decoration '%s': %s", dec_id, err)

    async def _async_turn_off_decorations(self, context: Optional[Context] = None) -> None:
        """Turn off all active decoration plugs."""
        ctx = context or Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)

        for dec_id in list(self._active_decorations):
            try:
                await self.hass.services.async_call(
                    "homeassistant", "turn_off", {ATTR_ENTITY_ID: dec_id}, context=ctx
                )
            except Exception as err:
                _LOGGER.debug("PassableSmartLighting: Failed to turn off decoration '%s': %s", dec_id, err)
        self._active_decorations.clear()

    async def async_turn_off_holiday_lighting(self) -> None:
        """Turn off all active holiday lights and decorations."""
        ctx = Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)

        _LOGGER.info(
            "PassableSmartLighting: Turning off holiday lighting for %d light(s) and %d decoration(s).",
            len(self._active_lights),
            len(self._active_decorations),
        )

        for light_id in list(self._active_lights):
            try:
                await self.hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: light_id}, context=ctx)
            except Exception as err:
                _LOGGER.debug("PassableSmartLighting: Error turning off holiday light '%s': %s", light_id, err)

        self._active_lights.clear()
        await self._async_turn_off_decorations(ctx)

        self._is_active = False
        self._preview_holiday = None
        self._update_entities()

    async def async_preview_holiday(self, holiday_id: str, duration_sec: int = 60) -> None:
        """Preview a holiday configuration for a temporary period."""
        holiday = self.store.holidays.get(holiday_id)
        if not holiday:
            _LOGGER.warning("PassableSmartLighting: Holiday '%s' not found for preview.", holiday_id)
            return

        _LOGGER.info("PassableSmartLighting: Previewing holiday '%s' for %ds.", holiday["name"], duration_sec)
        self._preview_holiday = holiday
        await self.async_turn_on_holiday_lighting(preview_holiday=holiday)

        @callback
        def _revert(_now: Any) -> None:
            self._preview_holiday = None
            self.hass.async_create_task(self._async_evaluate_schedule_trigger())

        async_call_later(self.hass, max(5, duration_sec), _revert)

    def get_legacy_sensor_attributes(self) -> Dict[str, Any]:
        """Generate attributes matching the legacy template sensor for 100% backward compatibility."""
        holidays = self.store.holidays
        legacy_data: Dict[str, Any] = {}

        for h in holidays.values():
            legacy_data[h["name"]] = {
                "rgb": h.get("rgb_color", [255, 209, 163]),
                "icon": h.get("icon", "mdi:calendar-star"),
                "phrase": h.get("phrase", ""),
                "theme_color": h.get("theme_color", "#555555"),
                "decorations_on": bool(h.get("decorations_on", True)),
            }

        curr = self.active_holiday
        if curr:
            rgb = curr.get("rgb_color", [255, 209, 163])
            icon = curr.get("icon", "mdi:calendar-star")
            phrase = curr.get("phrase", "")
            theme = curr.get("theme_color", "#555555")
            decorations_active = "true" if (self._active_decorations or curr.get("decorations_on")) else "false"
            scene = curr.get("hue_scene", "")
            effect = curr.get("effect", "") or curr.get("fallback_effect", "")
            dynamic_active = bool(curr.get("dynamic_scene", False))
        else:
            rgb = [255, 209, 163]
            icon = "mdi:home"
            phrase = "Normal Mode"
            theme = "#555555"
            decorations_active = "false"
            scene = ""
            effect = ""
            dynamic_active = False

        return {
            "holiday_data": json.dumps(legacy_data, indent=2),
            "current_rgb": rgb,
            "current_icon": icon,
            "current_phrase": phrase,
            "current_theme": theme,
            "decorations_active": decorations_active,
            "current_scene": scene,
            "current_effect": effect,
            "dynamic_active": dynamic_active,
            "participating_lights": self.resolve_participating_lights(curr) if curr else [],
            "active_decorations": list(self._active_decorations),
            "friendly_name": "Active Holiday",
            "icon": icon,
        }

    def stop(self) -> None:
        """Clean up listeners on unload."""
        for unsub in self._unsub_listeners:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_listeners.clear()
        if self._midnight_unsub:
            try:
                self._midnight_unsub()
            except Exception:
                pass
            self._midnight_unsub = None
