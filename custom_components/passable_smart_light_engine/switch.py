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
    DOMAIN,
)
from .engine import PassableLightingEngine, RoomController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up switch entities for a room config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]
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
