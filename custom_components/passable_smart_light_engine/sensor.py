"""Sensor platform for Passable Adaptive Smart Lighting Controller."""

import time
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEFAULT_LUX_RATIO,
    CONF_ROOM_ID,
    CONF_SECONDARY_LIGHTS,
    CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    CONF_TARGET_LUX,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LUX_RATIO,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_SECONDARY_LIGHTS,
    DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    DEFAULT_TARGET_LUX,
    DOMAIN,
    RESET_TYPES,
)
from .engine import (
    PassableLightingEngine,
    RoomController,
    calculate_learned_target_lux,
    get_expected_lux,
    safe_get_state,
)
from .storage import LearningDataStore


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities for a room config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]
    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    entities = [
        PassableLightingLuxYieldSensor(entry, controller, engine),
        PassableLightingTargetLuxSensor(entry, controller, engine),
        PassableLightingActiveModeSensor(entry, controller, engine),
    ]

    # Add the system-wide ready sensor once if not already added
    if not data.get("system_sensor_registered"):
        entities.append(PassableLightingEngineReadySensor(hass, engine.store))
        data["system_sensor_registered"] = True

    async_add_entities(entities)


class PassableLightingBaseSensor(SensorEntity):
    """Base class providing device info and live storage listeners for room sensors."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize base sensor."""
        self._entry = entry
        self._controller = controller
        self._engine = engine
        self._room_id = entry.data[CONF_ROOM_ID]
        self._room_title = self._room_id.replace("_", " ").title()

    async def async_added_to_hass(self) -> None:
        """Register storage update listener so attributes refresh live when learning data updates."""
        self._engine.store.register_update_listener(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the room device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {self._room_title}",
            manufacturer="Passable",
            model="Smart Lighting Engine v2",
            sw_version="2.1.9",
        )


class PassableLightingLuxYieldSensor(PassableLightingBaseSensor):
    """Diagnostic sensor reporting calculated ambient lux per 1% brightness."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize lux yield sensor."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_lux_yield"
        self._attr_name = f"{self._room_title} Lux Yield"
        self._attr_native_unit_of_measurement = "lx/%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-line"

    @property
    def native_value(self) -> float:
        """Calculate and return average lux per 1% brightness."""
        curves = self._engine.store.data.get("room_curves", {}).get(self._room_id, {})
        default_ratio = float(self._controller.entry_data.get(CONF_DEFAULT_LUX_RATIO, DEFAULT_LUX_RATIO))
        if not curves:
            return default_ratio

        yield_50 = get_expected_lux(curves, 50, default_ratio)
        return round(yield_50 / 50.0, 2)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose learned room curve yield points."""
        curves = self._engine.store.data.get("room_curves", {}).get(self._room_id, {})
        return {
            "room_curves": curves,
            "curve_points_count": len(curves),
        }


class PassableLightingTargetLuxSensor(PassableLightingBaseSensor):
    """Diagnostic sensor reporting current blended target lux."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize target lux sensor."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_target_lux_sensor"
        self._attr_name = f"{self._room_title} Target Lux"
        self._attr_device_class = SensorDeviceClass.ILLUMINANCE
        self._attr_native_unit_of_measurement = "lx"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:brightness-auto"

    @property
    def native_value(self) -> float:
        """Calculate current target lux."""
        seed_lux = float(self._controller.entry_data.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX))
        user_prefs = self._engine.store.data.get("user_prefs", {}).get(self._room_id, [])
        sun_state = self.hass.states.get("sun.sun")
        elev = float(sun_state.attributes.get("elevation", 0)) if sun_state else 0.0
        azim = float(sun_state.attributes.get("azimuth", 0)) if sun_state and "azimuth" in sun_state.attributes else None
        return round(calculate_learned_target_lux(seed_lux, user_prefs, elev, azim), 1)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose learned user preferences and sample count."""
        prefs = self._engine.store.data.get("user_prefs", {}).get(self._room_id, [])
        return {
            "user_preferences": prefs,
            "sample_count": len(prefs),
            "seed_lux": float(self._controller.entry_data.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX)),
        }


class PassableLightingActiveModeSensor(PassableLightingBaseSensor):
    """Sensor reporting active operating mode of the room."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize active mode sensor."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_active_mode"
        self._attr_name = f"{self._room_title} Active Mode"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str:
        """Determine and return current mode."""
        if not self._controller.is_enabled:
            return "disabled"

        if self._engine.is_manual_override_active(self._room_id):
            return "manual_override"

        freezes = self._controller.entry_data.get("bypass_freeze_entities", [])
        offs = self._controller.entry_data.get("bypass_off_entities", [])
        manual_override_entity = self._controller.entry_data.get("manual_override_entity")
        is_frozen, is_off = self._engine.check_bypasses(freezes, offs, manual_override_entity)
        if self._controller.freeze_bypass_active:
            is_frozen = True

        if is_off:
            return "forced_off"
        if is_frozen:
            return "frozen"

        media = self._controller.entry_data.get("media_entities", [])
        if self._engine.check_media(media):
            return "media"

        is_night = self._engine.is_late_night_active(
            bool(self._controller.entry_data.get("late_night_enabled", False)),
            str(self._controller.entry_data.get("late_night_condition_type", "time")),
            self._controller.entry_data.get("late_night_entity"),
            str(self._controller.entry_data.get("late_night_start_time", "22:00:00")),
            str(self._controller.entry_data.get("late_night_stop_time", "06:00:00")),
            self._controller.entry_data.get("late_night_start_entity"),
            self._controller.entry_data.get("late_night_stop_entity"),
        )
        if is_night:
            return "late_night"

        presence = self._controller.entry_data.get("presence_entity", [])
        is_occupied = self._engine.check_presence(presence)

        sec_lights = self._controller.entry_data.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS)
        if isinstance(sec_lights, str):
            sec_lights = [sec_lights] if sec_lights else []
        any_sec_on = any(safe_get_state(self.hass, s, "off") == "on" for s in (sec_lights or []))
        suppress_main = bool(
            self._controller.entry_data.get(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON)
        )

        if suppress_main and any_sec_on and is_occupied:
            return "secondary_active"

        if is_occupied:
            return "occupied"

        return "vacant"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose media and late night preferences and target percentages."""
        learning_data = self._engine.store.data
        media_prefs = learning_data.get("media_prefs", {}).get(self._room_id, [])
        late_night_prefs = learning_data.get("late_night_prefs", {}).get(self._room_id, [])
        media_seed = int(self._controller.entry_data.get("media_seed_pct", DEFAULT_MEDIA_SEED_PCT))
        late_night_seed = int(self._controller.entry_data.get("late_night_pct", DEFAULT_LATE_NIGHT_PCT))

        media_target = int(sum(media_prefs) / len(media_prefs)) if media_prefs else media_seed
        late_night_target = int(sum(late_night_prefs) / len(late_night_prefs)) if late_night_prefs else late_night_seed

        sec_lights = self._controller.entry_data.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS)
        if isinstance(sec_lights, str):
            sec_lights = [sec_lights] if sec_lights else []
        active_sec = [s for s in (sec_lights or []) if safe_get_state(self.hass, s, "off") == "on"]
        suppress_main = bool(
            self._controller.entry_data.get(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON)
        )

        return {
            "media_preferences": media_prefs,
            "media_target_pct": media_target,
            "late_night_preferences": late_night_prefs,
            "late_night_target_pct": late_night_target,
            "secondary_lights": sec_lights or [],
            "active_secondary_lights": active_sec,
            "secondary_lights_active": len(active_sec) > 0,
            "suppress_main_when_secondary_on": suppress_main,
        }


class PassableLightingEngineReadySensor(SensorEntity):
    """System-wide readiness and dataset synchronization sensor."""

    def __init__(self, hass: HomeAssistant, store: LearningDataStore) -> None:
        """Initialize ready sensor."""
        self.hass = hass
        self._store = store
        self._attr_unique_id = f"{DOMAIN}_ready"
        self._attr_name = "Passable Smart Light Engine Ready"
        self._attr_icon = "mdi:brain"
        self._startup_time = time.time()

    async def async_added_to_hass(self) -> None:
        """Register storage update listener."""
        self._store.register_update_listener(self._on_store_updated)

    def _on_store_updated(self) -> None:
        """Update HA state when storage data changes."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return engine state."""
        return "on"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose active rooms, room datasets, and reset types for dynamic popups."""
        return {
            "startup_time": self._startup_time,
            "active_rooms": self._store.get_active_rooms(),
            "room_datasets": self._store.get_room_datasets(),
            "available_reset_types": RESET_TYPES,
        }
