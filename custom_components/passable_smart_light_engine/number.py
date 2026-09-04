"""Number platform for Passable Adaptive Smart Lighting Controller."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ROOM_ID, CONF_TARGET_LUX, DEFAULT_TARGET_LUX, DOMAIN
from .engine import RoomController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up number entities for a room config entry."""
    data = hass.data[DOMAIN]
    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    async_add_entities([PassableLightingTargetLuxNumber(entry, controller)])


class PassableLightingTargetLuxNumber(NumberEntity):
    """Interactive number entity to adjust baseline target lux directly from dashboard."""

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize number entity."""
        self._entry = entry
        self._controller = controller
        self._room_id = entry.data[CONF_ROOM_ID]
        self._room_title = self._room_id.replace("_", " ").title()

        self._attr_unique_id = f"{DOMAIN}_{self._room_id}_target_lux_number"
        self._attr_name = f"{self._room_title} Target Lux Setting"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 1000
        self._attr_native_step = 5
        self._attr_native_unit_of_measurement = "lx"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:tune"

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

    @property
    def native_value(self) -> float:
        """Return current configured target lux."""
        return float(self._controller.entry_data.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX))

    async def async_set_native_value(self, value: float) -> None:
        """Update target lux setting in config entry and trigger re-evaluation."""
        new_data = {**self._controller.entry_data, CONF_TARGET_LUX: int(value)}
        self._controller.entry_data = new_data
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self.async_write_ha_state()
        await self._controller.async_evaluate("target_lux_adjusted")
