"""Switch platform for Passable Adaptive Smart Lighting Controller."""

from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CIRCADIAN_ENABLED,
    CONF_CREATE_FREEZE_SWITCH,
    CONF_CREATE_OVERRIDE_SWITCH,
    CONF_ROOM_ID,
    CONF_SIMULATION_ENABLED,
    DOMAIN,
    EXTERIOR_LIGHTING_SWITCH_ENTITY_ID,
    EXTERIOR_LIGHTING_SWITCH_UNIQUE_ID,
    HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID,
    HOLIDAY_DECORATIONS_SWITCH_UNIQUE_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID,
    HOLIDAY_LIGHTING_MASTER_SWITCH_UNIQUE_ID,
    PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID,
    PRESENCE_SIMULATION_MASTER_SWITCH_UNIQUE_ID,
    PRESENCE_SIMULATION_SWITCH_ENTITY_ID,
    PRESENCE_SIMULATION_SWITCH_UNIQUE_ID,
)
from .engine import PassableLightingEngine, RoomController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up switch entities for a room, presence simulation, or holiday lighting config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]

    if entry.data.get("entry_type") == "presence_simulation":
        async_add_entities(
            [
                PassablePresenceSimulationMasterSwitch(hass, entry, engine),
                PassablePresenceSimulationSwitch(hass, engine),
            ]
        )
        return

    if entry.data.get("entry_type") == "holiday_lighting":
        holiday_coord = data.get("holiday_coordinator")
        if holiday_coord:
            master_sw = PassableHolidayLightingMasterSwitch(entry, holiday_coord)
            decor_sw = PassableHolidayDecorationsSwitch(entry, holiday_coord)
            exterior_sw = PassableExteriorLightingSwitch(entry, holiday_coord)
            holiday_coord.register_entities(
                master_switch=master_sw,
                decor_switch=decor_sw,
                exterior_switch=exterior_sw,
            )
            async_add_entities([master_sw, decor_sw, exterior_sw])
        return

    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]
    room_id = entry.data[CONF_ROOM_ID]

    entities = [
        PassableLightingRoomSwitch(entry, controller),
        PassableLightingCircadianSwitch(entry, controller),
    ]

    if entry.data.get(CONF_CREATE_OVERRIDE_SWITCH):
        entities.append(PassableLightingOverrideSwitch(entry, controller, engine))

    if entry.data.get(CONF_CREATE_FREEZE_SWITCH):
        entities.append(PassableLightingFreezeSwitch(entry, controller))

    async_add_entities(entities)


class PassableLightingBaseEntity:
    """Base class providing device info for room entities."""

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize base entity."""
        self._entry = entry
        self._controller = controller
        self._room_id = entry.data[CONF_ROOM_ID]
        self._room_title = self._room_id.replace("_", " ").title()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the room device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {self._room_title}",
            manufacturer="Passable",
            model="Smart Lighting Engine v2",
            sw_version="2.0.0",
        )


class PassableLightingRoomSwitch(PassableLightingBaseEntity, SwitchEntity):
    """Switch to toggle the automation engine on/off for this room."""

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize the room switch."""
        super().__init__(entry, controller)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_automation_switch"
        self._attr_name = f"Smart Lighting {self._room_title}"
        self._attr_icon = "mdi:auto-fix"

    @property
    def is_on(self) -> bool:
        """Return True if automation is enabled for this room."""
        return self._controller.is_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automation for this room."""
        self._controller.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automation for this room."""
        self._controller.set_enabled(False)
        self.async_write_ha_state()


class PassableLightingCircadianSwitch(PassableLightingBaseEntity, SwitchEntity):
    """Switch to toggle circadian rhythm color temperature shifting."""

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize the circadian switch."""
        super().__init__(entry, controller)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_circadian_switch"
        self._attr_name = f"{self._room_title} Circadian Rhythm"
        self._attr_icon = "mdi:weather-sunset"

    @property
    def is_on(self) -> bool:
        """Return True if circadian rhythm is enabled."""
        return bool(self._controller.entry_data.get(CONF_CIRCADIAN_ENABLED, True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable circadian rhythm."""
        new_data = {**self._controller.entry_data, CONF_CIRCADIAN_ENABLED: True}
        self._controller.entry_data = new_data
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self.async_write_ha_state()
        self.hass.async_create_task(
            self._controller.engine.async_evaluate_dynamic_circadian(self._room_id)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable circadian rhythm."""
        new_data = {**self._controller.entry_data, CONF_CIRCADIAN_ENABLED: False}
        self._controller.entry_data = new_data
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self.async_write_ha_state()


class PassableLightingOverrideSwitch(PassableLightingBaseEntity, SwitchEntity):
    """Auto-created manual override switch."""

    def __init__(
        self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine
    ) -> None:
        """Initialize the override switch."""
        super().__init__(entry, controller)
        self._engine = engine
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_manual_override_switch"
        self._attr_name = f"{self._room_title} Manual Override"
        self._attr_icon = "mdi:lock-clock"

    @property
    def is_on(self) -> bool:
        """Return True if manual override is active."""
        return self._engine.is_manual_override_active(self._room_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock manual override for the configured timeout."""
        timeout_m = int(self._controller.entry_data.get("override_timeout_min", 60))
        manual_override_entity = self._controller.entry_data.get("manual_override_entity")
        self._engine.schedule_manual_override(self._room_id, timeout_m, manual_override_entity)
        if manual_override_entity:
            await self._engine.async_sync_helper(manual_override_entity, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear manual override."""
        manual_override_entity = self._controller.entry_data.get("manual_override_entity")
        self._engine.clear_manual_override(self._room_id)
        if manual_override_entity:
            await self._engine.async_sync_helper(manual_override_entity, False)
        self.async_write_ha_state()


class PassableLightingFreezeSwitch(PassableLightingBaseEntity, SwitchEntity):
    """Auto-created dedicated freeze switch."""

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize the freeze switch."""
        super().__init__(entry, controller)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_freeze_switch"
        self._attr_name = f"{self._room_title} Freeze Bypass"
        self._attr_icon = "mdi:pause-circle"

    @property
    def is_on(self) -> bool:
        """Return True if freeze bypass is active."""
        return self._controller.freeze_bypass_active

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate freeze bypass."""
        self._controller.set_freeze_bypass(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate freeze bypass."""
        self._controller.set_freeze_bypass(False)
        self.async_write_ha_state()


class PassablePresenceSimulationMasterSwitch(SwitchEntity):
    """Master toggle switch to enable/disable the presence simulation function."""

    _attr_has_entity_name = True
    _attr_name = "Presence Simulation Function"
    _attr_icon = "mdi:shield-home"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, engine: PassableLightingEngine) -> None:
        """Initialize master presence simulation switch."""
        self.hass = hass
        self._entry = entry
        self._engine = engine
        self._coordinator = engine.presence_simulation
        if self._coordinator:
            self._coordinator.register_master_switch(self)
        self._attr_unique_id = PRESENCE_SIMULATION_MASTER_SWITCH_UNIQUE_ID
        self.entity_id = PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID

    @property
    def device_info(self) -> DeviceInfo:
        """Return system device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, "presence_simulation")},
            name="Passable Smart Light Engine - Presence Simulation",
            manufacturer="Passable",
            model="Presence Simulation v1",
            sw_version="2.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True if simulation feature is enabled."""
        if not self._coordinator:
            return True
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable presence simulation function."""
        if self._coordinator:
            await self._coordinator.async_set_enabled(True)
        new_data = {**self._entry.data, CONF_SIMULATION_ENABLED: True}
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable presence simulation function."""
        if self._coordinator:
            await self._coordinator.async_set_enabled(False)
        new_data = {**self._entry.data, CONF_SIMULATION_ENABLED: False}
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self.async_write_ha_state()


class PassablePresenceSimulationSwitch(SwitchEntity):
    """Presence simulation away mode trigger switch with drop-in compatibility."""

    def __init__(self, hass: HomeAssistant, engine: PassableLightingEngine) -> None:
        """Initialize presence simulation switch."""
        self.hass = hass
        self._engine = engine
        self._coordinator = engine.presence_simulation
        if self._coordinator:
            self._coordinator.register_switch(self)
        self._attr_unique_id = PRESENCE_SIMULATION_SWITCH_UNIQUE_ID
        self._attr_name = "Simulate Presence (Away Mode)"
        self.entity_id = PRESENCE_SIMULATION_SWITCH_ENTITY_ID
        self._attr_icon = "mdi:home-clock"

    @property
    def device_info(self) -> DeviceInfo:
        """Return system device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, "presence_simulation")},
            name="Passable Smart Light Engine - Presence Simulation",
            manufacturer="Passable",
            model="Presence Simulation v1",
            sw_version="2.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True if simulation is active."""
        if not self._coordinator:
            return False
        return self._coordinator.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on presence simulation."""
        if self._coordinator:
            await self._coordinator.async_start()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off presence simulation."""
        if self._coordinator:
            await self._coordinator.async_stop()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose simulation attributes."""
        if not self._coordinator:
            return {}
        return {
            "status": self._coordinator.status,
            "simulation_enabled": self._coordinator.enabled,
            "simulation_mode": self._coordinator.mode,
            "target_label": self._coordinator.label,
            "configured_lights": self._coordinator.configured_target_entities,
            "configured_count": len(self._coordinator.configured_target_entities),
            "active_simulated_lights": self._coordinator.active_simulated_lights,
            "active_lights_count": len(self._coordinator.active_simulated_lights),
            "next_event": self._coordinator.next_event,
            "lookback_days": self._coordinator.lookback_days,
            "jitter_minutes": self._coordinator.jitter_min,
            "arrival_grace_minutes": self._coordinator.arrival_grace_min,
        }


class PassableHolidayLightingMasterSwitch(SwitchEntity):
    """Master toggle switch for Holiday Lighting subsystem."""

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        """Initialize holiday lighting master switch."""
        self._entry = entry
        self._coordinator = coordinator
        self.entity_id = HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID
        self._attr_unique_id = HOLIDAY_LIGHTING_MASTER_SWITCH_UNIQUE_ID
        self._attr_name = "Holiday Lighting"
        self._attr_icon = "mdi:party-popper"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the Holiday & Exterior Lighting device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "holiday_lighting")},
            name="Holiday & Exterior Lighting",
            manufacturer="Passable",
            model="Holiday & Exterior Lighting Subsystem",
            sw_version="2.4.4",
        )

    @property
    def is_on(self) -> bool:
        """Return True if holiday lighting is enabled."""
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on holiday lighting."""
        await self._coordinator.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off holiday lighting."""
        await self._coordinator.async_set_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose operational attributes."""
        curr = self._coordinator.active_holiday
        return {
            "is_active": self._coordinator.is_active,
            "active_holiday": curr["name"] if curr else None,
            "active_lights": self._coordinator.active_lights,
            "active_lights_count": len(self._coordinator.active_lights),
            "active_decorations": self._coordinator.active_decorations,
            "active_decorations_count": len(self._coordinator.active_decorations),
        }


class PassableHolidayDecorationsSwitch(SwitchEntity):
    """Toggle switch specifically for holiday decoration plugs and switches."""

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        """Initialize holiday decorations switch."""
        self._entry = entry
        self._coordinator = coordinator
        self.entity_id = HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID
        self._attr_unique_id = HOLIDAY_DECORATIONS_SWITCH_UNIQUE_ID
        self._attr_name = "Holiday Decorations"
        self._attr_icon = "mdi:power-plug"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the Holiday & Exterior Lighting device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "holiday_lighting")},
            name="Holiday & Exterior Lighting",
            manufacturer="Passable",
            model="Holiday & Exterior Lighting Subsystem",
            sw_version="2.4.4",
        )

    @property
    def is_on(self) -> bool:
        """Return True if holiday decorations are enabled."""
        return self._coordinator.decorations_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on holiday decorations."""
        await self._coordinator.async_set_decorations_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off holiday decorations."""
        await self._coordinator.async_set_decorations_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose decorations attributes."""
        return {
            "active_decorations": self._coordinator.active_decorations,
            "active_decorations_count": len(self._coordinator.active_decorations),
        }


class PassableExteriorLightingSwitch(SwitchEntity):
    """Toggle switch specifically for dusk-to-dawn exterior lighting."""

    def __init__(self, entry: ConfigEntry, coordinator: Any) -> None:
        """Initialize exterior dusk-to-dawn lighting switch."""
        self._entry = entry
        self._coordinator = coordinator
        self.entity_id = EXTERIOR_LIGHTING_SWITCH_ENTITY_ID
        self._attr_unique_id = EXTERIOR_LIGHTING_SWITCH_UNIQUE_ID
        self._attr_name = "Exterior Dusk-to-Dawn Lighting"
        self._attr_icon = "mdi:weather-sunset-down"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the Holiday & Exterior Lighting device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "holiday_lighting")},
            name="Holiday & Exterior Lighting",
            manufacturer="Passable",
            model="Holiday & Exterior Lighting Subsystem",
            sw_version="2.4.4",
        )

    @property
    def is_on(self) -> bool:
        """Return True if exterior dusk-to-dawn lighting is enabled."""
        return self._coordinator.exterior_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on exterior dusk-to-dawn lighting."""
        await self._coordinator.async_set_exterior_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off exterior dusk-to-dawn lighting."""
        await self._coordinator.async_set_exterior_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Expose exterior lighting attributes."""
        return {
            "exterior_active": self._coordinator.is_exterior_active,
            "baseline_active": self._coordinator.is_baseline_active,
            "holiday_active": self._coordinator.is_holiday_active_now,
            "participating_exterior_lights": self._coordinator.resolve_exterior_lights(),
        }


