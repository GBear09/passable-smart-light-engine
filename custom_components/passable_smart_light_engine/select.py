"""Select platform for Passable Adaptive Smart Lighting Controller."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ROOM_ID, DOMAIN
from .engine import RoomController

RESET_OPTIONS = [
    "all",
    "user_prefs",
    "room_curves",
    "media_prefs",
    "late_night_prefs",
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up select entities for a room config entry."""
    data = hass.data[DOMAIN]
    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    async_add_entities([PassableLightingResetDatasetSelect(entry, controller)])


class PassableLightingResetDatasetSelect(SelectEntity):
    """Select entity allowing user to pick which learning dataset to reset."""

    _attr_has_entity_name = True
    _attr_translation_key = "reset_dataset_target"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:database-cog"

    def __init__(self, entry: ConfigEntry, controller: RoomController) -> None:
        """Initialize dataset select entity."""
        self._entry = entry
        self._controller = controller
        self._room_id = entry.data[CONF_ROOM_ID]
        self._attr_unique_id = f"{self._room_id}_reset_dataset_target"
        self._attr_options = list(RESET_OPTIONS)
        self._attr_current_option = controller.selected_reset_target or "all"

    @property
    def current_option(self) -> str:
        """Return the currently selected dataset target."""
        return self._controller.selected_reset_target

    async def async_select_option(self, option: str) -> None:
        """Change the selected reset dataset target."""
        if option in RESET_OPTIONS:
            self._controller.selected_reset_target = option
            self._attr_current_option = option
            self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Link select entity to the room device."""
        room_title = self._room_id.replace("_", " ").title()
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {room_title}",
            manufacturer="Passable",
            model="Adaptive Lighting Room Controller",
        )
