"""Binary sensor platform for Passable AI Smart Lighting Controller."""

from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PRESENCE_ENTITIES, CONF_ROOM_ID, DOMAIN
from .engine import PassableLightingEngine, RoomController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensors for a room config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]
    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    entities = [
        PassableLightingPresenceBinarySensor(entry, controller, engine),
        PassableLightingOverrideBinarySensor(entry, controller, engine),
    ]

    async_add_entities(entities)


class PassableLightingBaseBinarySensor(BinarySensorEntity):
    """Base class for room binary sensors."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize binary sensor."""
        self._entry = entry
        self._controller = controller
        self._engine = engine
        self._room_id = entry.data[CONF_ROOM_ID]
        self._room_title = self._room_id.replace("_", " ").title()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking this entity to the room device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {self._room_title}",
            manufacturer="Passable AI",
            model="Smart Lighting Engine v2",
            sw_version="2.0.0",
        )


class PassableLightingPresenceBinarySensor(PassableLightingBaseBinarySensor):
    """Composite presence binary sensor for the room."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize presence binary sensor."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_composite_presence"
        self._attr_name = f"{self._room_title} Room Presence"
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        """Return True if any configured presence sensor is on."""
        presence_entities = self._controller.entry_data.get(CONF_PRESENCE_ENTITIES, [])
        if isinstance(presence_entities, str):
            presence_entities = [presence_entities]
        return self._engine.check_presence(presence_entities)


class PassableLightingOverrideBinarySensor(PassableLightingBaseBinarySensor):
    """Binary sensor indicating active manual override."""

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize override binary sensor."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_override_active"
        self._attr_name = f"{self._room_title} Manual Override Active"
        self._attr_icon = "mdi:lock-outline"

    @property
    def is_on(self) -> bool:
        """Return True if manual override is currently active."""
        return self._engine.is_manual_override_active(self._room_id)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return override details."""
        return {
            "remaining_seconds": self._engine.get_override_remaining_sec(self._room_id),
            "timeout_minutes": int(self._controller.entry_data.get("override_timeout_min", 60)),
        }
