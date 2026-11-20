"""Sensor platform for Passable Smart Light Engine."""

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
    ACTIVE_HOLIDAY_SENSOR_ENTITY_ID,
    ACTIVE_HOLIDAY_SENSOR_UNIQUE_ID,
    CONF_DEFAULT_LUX_RATIO,
    CONF_LATE_NIGHT_LEARN_PREFS,
    CONF_MEDIA_LEARN_PREFS,
    CONF_MEDIA_RESPECT_AMBIENT_LUX,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_ROOM_ID,
    CONF_SECONDARY_LIGHTS,
    CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    CONF_TARGET_LUX,
    CONF_TIMEOUT_SCALE_ENTITIES,
    CONF_TIMEOUT_SCALE_FACTOR,
    DEFAULT_LATE_NIGHT_LEARN_PREFS,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LUX_RATIO,
    DEFAULT_MEDIA_LEARN_PREFS,
    DEFAULT_MEDIA_RESPECT_AMBIENT_LUX,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_SECONDARY_LIGHTS,
    DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    DEFAULT_TARGET_LUX,
    DEFAULT_TIMEOUT_SCALE_ENTITIES,
    DEFAULT_TIMEOUT_SCALE_FACTOR,
    DOMAIN,
    MODE_HOLIDAY,
    MODE_NOTIFICATION,
    MODE_PRESENCE_SIMULATION,
    RESET_TYPES,
    SUMMARY_SENSOR_ENTITY_ID,
    SUMMARY_SENSOR_UNIQUE_ID,
)
from .engine import (
    PassableLightingEngine,
    RoomController,
    calculate_learned_target_lux,
    compute_engine_summary,
    compute_room_active_mode,
    get_expected_lux,
    safe_get_state,
)
from .storage import LearningDataStore


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities for a room, presence simulation, or holiday lighting config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]

    if entry.data.get("entry_type") == "presence_simulation":
        if not data.get("system_simulation_sensor_registered"):
            async_add_entities([PassablePresenceSimulationStatusSensor(hass, engine)])
            data["system_simulation_sensor_registered"] = True
        return

    if entry.data.get("entry_type") == "holiday_lighting":
        holiday_coord = data.get("holiday_coordinator")
        if holiday_coord:
            sensor = PassableActiveHolidaySensor(entry, holiday_coord)
            holiday_coord.register_entities(sensor=sensor)
            async_add_entities([sensor])
        return

    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    entities = [
        PassableLightingLuxYieldSensor(entry, controller, engine),
        PassableLightingTargetLuxSensor(entry, controller, engine),
        PassableLightingActiveModeSensor(entry, controller, engine),
    ]

    # Add the system-wide ready and summary sensors once if not already added
    if not data.get("system_sensor_registered"):
        entities.extend(
            [
                PassableLightingEngineReadySensor(hass, engine.store),
                PassableLightingSummarySensor(hass, engine),
            ]
        )
        data["system_sensor_registered"] = True
        data["system_sensor_entry_id"] = entry.entry_id

    async_add_entities(entities)


class PassableLightingBaseSensor(SensorEntity):
    """Base class providing device info and live storage listeners for room sensors."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize base sensor."""
        self._entry = entry
        self._controller = controller
        self._engine = engine
        self._room_id = entry.data[CONF_ROOM_ID]
        self._room_title = self._room_id.replace("_", " ").title()

    async def async_added_to_hass(self) -> None:
        """Register storage and controller update listeners so attributes refresh live."""
        self.async_on_remove(
            self._engine.store.register_update_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            self._controller.register_entity_listener(self.async_write_ha_state)
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the room device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {self._room_title}",
            manufacturer="Passable",
            model="Smart Lighting Engine v2",
            sw_version="2.8.0",
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
        return compute_room_active_mode(self.hass, self._engine, self._controller)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose media and late night preferences and target percentages."""
        learning_data = self._engine.store.data
        media_prefs = learning_data.get("media_prefs", {}).get(self._room_id, [])
        late_night_prefs = learning_data.get("late_night_prefs", {}).get(self._room_id, [])
        media_seed = int(self._controller.entry_data.get("media_seed_pct", DEFAULT_MEDIA_SEED_PCT))
        late_night_seed = int(self._controller.entry_data.get("late_night_pct", DEFAULT_LATE_NIGHT_PCT))

        media_learn = bool(self._controller.entry_data.get(CONF_MEDIA_LEARN_PREFS, DEFAULT_MEDIA_LEARN_PREFS))
        late_night_learn = bool(
            self._controller.entry_data.get(CONF_LATE_NIGHT_LEARN_PREFS, DEFAULT_LATE_NIGHT_LEARN_PREFS)
        )

        if media_learn and media_prefs:
            media_target = int(sum(media_prefs) / len(media_prefs))
        else:
            media_target = media_seed

        if late_night_learn and late_night_prefs:
            late_night_target = int(sum(late_night_prefs) / len(late_night_prefs))
        else:
            late_night_target = late_night_seed

        sec_lights = self._controller.entry_data.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS)
        if isinstance(sec_lights, str):
            sec_lights = [sec_lights] if sec_lights else []
        active_sec = [s for s in (sec_lights or []) if safe_get_state(self.hass, s, "off") == "on"]
        suppress_main = bool(
            self._controller.entry_data.get(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON)
        )

        scale_entities = self._controller.entry_data.get(
            CONF_TIMEOUT_SCALE_ENTITIES, DEFAULT_TIMEOUT_SCALE_ENTITIES
        )
        if isinstance(scale_entities, str):
            scale_entities = [scale_entities] if scale_entities else []
        elif scale_entities is None:
            scale_entities = []
        base_timeout = int(
            self._controller.entry_data.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN)
        )
        try:
            scale_factor = float(
                self._controller.entry_data.get(CONF_TIMEOUT_SCALE_FACTOR, DEFAULT_TIMEOUT_SCALE_FACTOR)
            )
        except (TypeError, ValueError):
            scale_factor = DEFAULT_TIMEOUT_SCALE_FACTOR

        return {
            "notification_light_enabled": self._controller.is_notification_enabled,
            "notification_pending": self._controller.is_notification_pending,
            "notification_showing": self._controller.is_notification_showing,
            "notification_light_entity": self._controller.notification_light_entity,
            "media_learning_enabled": media_learn,
            "media_preferences": media_prefs,
            "media_target_pct": media_target,
            "media_respect_ambient_lux": bool(
                self._controller.entry_data.get(
                    CONF_MEDIA_RESPECT_AMBIENT_LUX, DEFAULT_MEDIA_RESPECT_AMBIENT_LUX
                )
            ),
            "media_daylight_suppressed": self._engine.is_media_daylight_suppressed(self._room_id),
            "late_night_learning_enabled": late_night_learn,
            "late_night_preferences": late_night_prefs,
            "late_night_target_pct": late_night_target,
            "secondary_lights": sec_lights or [],
            "active_secondary_lights": active_sec,
            "secondary_lights_active": len(active_sec) > 0,
            "suppress_main_when_secondary_on": suppress_main,
            "base_presence_timeout_min": base_timeout,
            "effective_presence_timeout_min": self._engine.get_effective_presence_timeout_min(
                self._controller.entry_data
            ),
            "timeout_scaling_active": self._engine.is_timeout_scaling_active(scale_entities),
            "timeout_scale_factor": scale_factor,
            "timeout_scale_entities": list(scale_entities),
        }


class PassableLightingEngineReadySensor(SensorEntity):
    """System-wide readiness and dataset synchronization sensor."""

    _attr_should_poll = False

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
        self.async_on_remove(
            self._store.register_update_listener(self._on_store_updated)
        )

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


class PassableLightingSummarySensor(SensorEntity):
    """System-wide summary sensor aggregating engine, room, holiday, and simulation status."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, engine: PassableLightingEngine) -> None:
        """Initialize summary sensor."""
        self.hass = hass
        self._engine = engine
        self.entity_id = SUMMARY_SENSOR_ENTITY_ID
        self._attr_unique_id = SUMMARY_SENSOR_UNIQUE_ID
        self._attr_name = "Passable Smart Light Engine Summary"
        self._attr_icon = "mdi:lightbulb-auto"

    @property
    def device_info(self) -> DeviceInfo:
        """Return system hub device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, "system_hub")},
            name="Passable Smart Light Engine",
            manufacturer="Passable",
            model="Smart Lighting Engine Hub",
            sw_version="2.9.0",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to engine, learning store, and holiday store updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._engine.register_summary_listener(self._on_summary_updated)
        )
        self.async_on_remove(
            self._engine.store.register_update_listener(self._on_summary_updated)
        )
        holiday_coord = self._engine.holiday_lighting
        if holiday_coord and getattr(holiday_coord, "store", None):
            self.async_on_remove(
                holiday_coord.store.register_update_listener(self._on_summary_updated)
            )

    def _on_summary_updated(self) -> None:
        """Write updated summary state safely when attached to hass."""
        if self.hass:
            self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return high-level engine operational state."""
        summary = compute_engine_summary(self.hass, self._engine)
        if summary["presence_simulation_active"]:
            return "simulating"
        if summary["manual_overrides_count"] > 0:
            return "override_active"
        if summary["holiday_active"]:
            return "holiday"
        if summary["total_rooms"] > 0 and summary["rooms_auto_enabled"] == 0:
            return "paused"
        return "auto"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose cross-room and subsystem telemetry."""
        summary = compute_engine_summary(self.hass, self._engine)
        summary.pop("sun_elevation", None)
        return summary


class PassablePresenceSimulationStatusSensor(SensorEntity):
    """Sensor reporting presence simulation status and active lights."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, engine: PassableLightingEngine) -> None:
        """Initialize simulation status sensor."""
        self.hass = hass
        self._engine = engine
        self._attr_unique_id = f"{DOMAIN}_presence_simulation_status"
        self._attr_name = "Presence Simulation Status"
        self._attr_icon = "mdi:shield-home"

    async def async_added_to_hass(self) -> None:
        """Subscribe to presence simulation coordinator updates."""
        coord = self._engine.presence_simulation
        if coord and hasattr(coord, "register_listener"):
            self.async_on_remove(coord.register_listener(self.async_write_ha_state))

    @property
    def device_info(self) -> DeviceInfo:
        """Return system device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, "presence_simulation")},
            name="Passable Smart Light Engine - Presence Simulation",
            manufacturer="Passable",
            model="Presence Simulation v1",
            sw_version="2.7.0",
        )

    @property
    def native_value(self) -> str:
        """Return current simulation status."""
        coord = self._engine.presence_simulation
        if not coord:
            return "idle"
        return coord.status

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return simulation diagnostics."""
        coord = self._engine.presence_simulation
        if not coord:
            return {}
        return {
            "is_active": coord.is_on,
            "simulation_enabled": coord.enabled,
            "configured_lights": coord.configured_target_entities,
            "configured_count": len(coord.configured_target_entities),
            "active_simulated_lights": coord.active_simulated_lights,
            "active_count": len(coord.active_simulated_lights),
            "next_event": coord.next_event,
            "label": coord.label,
            "mode": coord.mode,
            "lookback_days": coord.lookback_days,
            "jitter_minutes": coord.jitter_min,
            "arrival_grace_minutes": coord.arrival_grace_min,
        }


class PassableActiveHolidaySensor(SensorEntity):
    """Sensor reporting active holiday status and legacy dashboard attributes."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        """Initialize active holiday sensor."""
        self._entry = entry
        self._coordinator = coordinator
        self.entity_id = ACTIVE_HOLIDAY_SENSOR_ENTITY_ID
        self._attr_unique_id = ACTIVE_HOLIDAY_SENSOR_UNIQUE_ID
        self._attr_name = "Active Holiday"
        self._attr_icon = "mdi:calendar-star"

    async def async_added_to_hass(self) -> None:
        """Register storage listener to refresh state when holiday settings change."""
        self.async_on_remove(
            self._coordinator.store.register_update_listener(self.async_write_ha_state)
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the Holiday Lighting device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "holiday_lighting")},
            name="Holiday & Exterior Lighting",
            manufacturer="Passable",
            model="Holiday & Exterior Lighting Subsystem",
            sw_version="2.7.0",
        )

    @property
    def native_value(self) -> str:
        """Return current holiday name, or 'unknown' to preserve conditional dashboard cards."""
        curr = self._coordinator.active_holiday
        if curr:
            return curr.get("name", "unknown")
        return "unknown"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return legacy attributes and new rich holiday lighting metadata."""
        return self._coordinator.get_legacy_sensor_attributes()

