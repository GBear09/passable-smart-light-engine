"""Button platform for Passable Adaptive Smart Lighting Controller."""

import logging
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ROOM_ID, DOMAIN
from .engine import PassableLightingEngine, RoomController

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities for a room config entry."""
    data = hass.data[DOMAIN]
    engine: PassableLightingEngine = data["engine"]
    controllers = data["controllers"]
    controller: RoomController = controllers[entry.entry_id]

    entities = [
        PassableLightingCalibrateCurveButton(entry, controller, engine),
        PassableLightingResetSelectedButton(entry, controller, engine),
        PassableLightingResetAllButton(entry, controller, engine),
    ]

    async_add_entities(entities)


class PassableLightingBaseButton(ButtonEntity):
    """Base class for room button entities."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize base button."""
        self._entry = entry
        self._controller = controller
        self._engine = engine
        self._room_id = entry.data[CONF_ROOM_ID]

    @property
    def device_info(self) -> DeviceInfo:
        """Link button to the room device."""
        room_title = self._room_id.replace("_", " ").title()
        return DeviceInfo(
            identifiers={(DOMAIN, self._room_id)},
            name=f"Smart Lighting - {room_title}",
            manufacturer="Passable",
            model="Adaptive Lighting Room Controller",
        )


class PassableLightingResetSelectedButton(PassableLightingBaseButton):
    """Button entity to reset the currently selected learning dataset."""

    _attr_translation_key = "reset_selected_data"
    _attr_icon = "mdi:restore"

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize reset selected button."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{self._room_id}_reset_selected_data"

    async def async_press(self) -> None:
        """Execute reset for the selected target dataset."""
        target = self._controller.selected_reset_target or "all"
        await self._engine.store.async_reset(self._room_id, target)
        _LOGGER.info(
            "PassableAdaptiveLighting [%s]: Reset learning dataset '%s' via UI button press.",
            self._room_id,
            target,
        )


class PassableLightingResetAllButton(PassableLightingBaseButton):
    """Button entity to reset all learning datasets for this room with one click."""

    _attr_translation_key = "reset_all_data"
    _attr_icon = "mdi:delete-restore"

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize reset all button."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{self._room_id}_reset_all_data"

    async def async_press(self) -> None:
        """Execute reset for all datasets in this room."""
        await self._engine.store.async_reset(self._room_id, "all")
        _LOGGER.info(
            "PassableAdaptiveLighting [%s]: Reset ALL learning datasets via UI button press.",
            self._room_id,
        )


class PassableLightingCalibrateCurveButton(PassableLightingBaseButton):
    """Button entity to trigger automated yield calibration routine for this room."""

    _attr_translation_key = "calibrate_room_curve"
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, entry: ConfigEntry, controller: RoomController, engine: PassableLightingEngine) -> None:
        """Initialize calibrate room curve button."""
        super().__init__(entry, controller, engine)
        self._attr_unique_id = f"{self._room_id}_calibrate_room_curve"

    async def async_press(self) -> None:
        """Execute automated yield calibration for this room."""
        _LOGGER.info(
            "PassableAdaptiveLighting [%s]: Calibrate room curve triggered via UI button press.",
            self._room_id,
        )
        self.hass.async_create_task(self._engine.async_calibrate_room_curve(self._room_id))
