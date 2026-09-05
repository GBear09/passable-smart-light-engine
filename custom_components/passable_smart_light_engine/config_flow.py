"""Config flow and options flow for Passable Adaptive Smart Lighting Controller."""

from typing import Any, Dict, Optional
import voluptuous as vol

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BYPASS_FREEZE_ENTITIES,
    CONF_BYPASS_OFF_ENTITIES,
    CONF_CIRCADIAN_ENABLED,
    CONF_CREATE_FREEZE_SWITCH,
    CONF_CREATE_OVERRIDE_SWITCH,
    CONF_DEFAULT_LUX_RATIO,
    CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
    CONF_LATE_NIGHT_CONDITION_TYPE,
    CONF_LATE_NIGHT_ENABLED,
    CONF_LATE_NIGHT_ENTITY,
    CONF_LATE_NIGHT_PCT,
    CONF_LATE_NIGHT_START_ENTITY,
    CONF_LATE_NIGHT_START_TIME,
    CONF_LATE_NIGHT_STOP_ENTITY,
    CONF_LATE_NIGHT_STOP_TIME,
    CONF_LIGHT_ENTITY,
    CONF_LUX_SENSOR,
    CONF_MANUAL_OVERRIDE_ENTITY,
    CONF_MAX_COLOR_TEMP,
    CONF_MEDIA_ENTITIES,
    CONF_MEDIA_SEED_PCT,
    CONF_MIN_COLOR_TEMP,
    CONF_MIN_OCCUPIED_PCT,
    CONF_OVERRIDE_TIMEOUT_MIN,
    CONF_POWER_GRID_ENTITY,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_ROOM_ID,
    CONF_SETTLING_COOLDOWN_SEC,
    CONF_TARGET_LUX,
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
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_MIN_OCCUPIED_PCT,
    DEFAULT_OVERRIDE_TIMEOUT_MIN,
    DEFAULT_POWER_GRID_ENTITY,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_SETTLING_COOLDOWN_SEC,
    DEFAULT_TARGET_LUX,
    DOMAIN,
    SECTION_BYPASSES,
    SECTION_CIRCADIAN,
    SECTION_HARDWARE,
    SECTION_LATE_NIGHT,
    SECTION_MEDIA,
)


class OptionalEntitySelector(selector.EntitySelector):
    """EntitySelector that safely accepts None or empty string when optional."""

    def __call__(self, data: Any) -> Any:
        """Validate input or allow None when empty."""
        if data is None or data == "":
            return [] if self.config.get("multiple") else None
        if self.config.get("multiple") and isinstance(data, list):
            cleaned = [x for x in data if x]
            return cleaned
        return super().__call__(data)


class OptionalTimeSelector(selector.TimeSelector):
    """TimeSelector that safely accepts None or empty string when optional."""

    def __call__(self, data: Any) -> Any:
        """Validate input or allow None when empty."""
        if data is None or data == "":
            return None
        return super().__call__(data)


class PassableSmartLightingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Passable Adaptive Smart Lighting Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._step1_data: Dict[str, Any] = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Handle Step 1: Core room requirements and hardware."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            room_id = user_input[CONF_ROOM_ID].strip().lower().replace(" ", "_")
            await self.async_set_unique_id(room_id)
            self._abort_if_unique_id_configured()

            self._step1_data = dict(user_input)
            self._step1_data[CONF_ROOM_ID] = room_id
            return await self.async_step_advanced()

        step1_schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_ID): selector.TextSelector(),
                vol.Required(CONF_LIGHT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Required(CONF_PRESENCE_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Required(CONF_LUX_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
                ),
                vol.Required(CONF_TARGET_LUX, default=DEFAULT_TARGET_LUX): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1000, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_DEFAULT_LUX_RATIO, default=DEFAULT_LUX_RATIO): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.01, max=20.0, step=0.05, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_PRESENCE_TIMEOUT_MIN, default=DEFAULT_PRESENCE_TIMEOUT_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=120, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_MIN_OCCUPIED_PCT, default=DEFAULT_MIN_OCCUPIED_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=step1_schema, errors=errors)

    async def async_step_advanced(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Handle Step 2: Advanced settings, overrides, and bypasses."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            flat_input: Dict[str, Any] = {}
            for k, v in user_input.items():
                if isinstance(v, dict):
                    flat_input.update(v)
                else:
                    flat_input[k] = v
            full_data = {**self._step1_data, **flat_input}
            room_title = self._step1_data[CONF_ROOM_ID].replace("_", " ").title()
            return self.async_create_entry(title=f"Smart Lighting - {room_title}", data=full_data)

        step2_schema = vol.Schema(
            {
                vol.Required(SECTION_CIRCADIAN): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_CIRCADIAN_ENABLED, default=DEFAULT_CIRCADIAN_ENABLED): selector.BooleanSelector(),
                            vol.Optional(CONF_MIN_COLOR_TEMP, default=DEFAULT_MIN_COLOR_TEMP): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=2000, max=4000, step=100, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(CONF_MAX_COLOR_TEMP, default=DEFAULT_MAX_COLOR_TEMP): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=4000, max=6500, step=100, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_LATE_NIGHT): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_LATE_NIGHT_ENABLED, default=DEFAULT_LATE_NIGHT_ENABLED): selector.BooleanSelector(),
                            vol.Optional(CONF_LATE_NIGHT_PCT, default=DEFAULT_LATE_NIGHT_PCT): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                            vol.Optional(CONF_LATE_NIGHT_CONDITION_TYPE, default=DEFAULT_LATE_NIGHT_CONDITION_TYPE): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=[
                                        selector.SelectOptionDict(value="time", label="Time Schedule"),
                                        selector.SelectOptionDict(value="entity_state", label="Entity State (Helper/Group)"),
                                    ]
                                )
                            ),
                            vol.Optional(CONF_LATE_NIGHT_ENTITY): OptionalEntitySelector(),
                            vol.Optional(CONF_LATE_NIGHT_START_TIME, default=DEFAULT_LATE_NIGHT_START_TIME): OptionalTimeSelector(),
                            vol.Optional(CONF_LATE_NIGHT_START_ENTITY): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="input_datetime")
                            ),
                            vol.Optional(CONF_LATE_NIGHT_STOP_TIME, default=DEFAULT_LATE_NIGHT_STOP_TIME): OptionalTimeSelector(),
                            vol.Optional(CONF_LATE_NIGHT_STOP_ENTITY): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="input_datetime")
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_MEDIA): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_MEDIA_ENTITIES, default=[]): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="media_player", multiple=True)
                            ),
                            vol.Optional(CONF_MEDIA_SEED_PCT, default=DEFAULT_MEDIA_SEED_PCT): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_BYPASSES): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_MANUAL_OVERRIDE_ENTITY): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain=["input_boolean", "switch"])
                            ),
                            vol.Optional(CONF_CREATE_OVERRIDE_SWITCH, default=False): selector.BooleanSelector(),
                            vol.Optional(CONF_BYPASS_FREEZE_ENTITIES, default=[]): OptionalEntitySelector(
                                selector.EntitySelectorConfig(multiple=True)
                            ),
                            vol.Optional(CONF_CREATE_FREEZE_SWITCH, default=False): selector.BooleanSelector(),
                            vol.Optional(CONF_BYPASS_OFF_ENTITIES, default=[]): OptionalEntitySelector(
                                selector.EntitySelectorConfig(multiple=True)
                            ),
                            vol.Optional(CONF_OVERRIDE_TIMEOUT_MIN, default=DEFAULT_OVERRIDE_TIMEOUT_MIN): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=5, max=240, step=5, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE, default=DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE): selector.BooleanSelector(),
                            vol.Optional(CONF_POWER_GRID_ENTITY): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                            ),
                            vol.Optional(CONF_SETTLING_COOLDOWN_SEC, default=DEFAULT_SETTLING_COOLDOWN_SEC): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=5, max=180, step=5, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(step_id="advanced", data_schema=step2_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create options flow handler for modifying an existing room."""
        return PassableSmartLightingOptionsFlow(config_entry)


class PassableSmartLightingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for editing an existing room configuration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Manage room options."""
        if user_input is not None:
            # Unpack section dictionaries and update entry data
            flat_input: Dict[str, Any] = {}
            for k, v in user_input.items():
                if isinstance(v, dict):
                    flat_input.update(v)
                else:
                    flat_input[k] = v
            new_data = {**self._entry.data, **flat_input}
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            return self.async_create_entry(title="", data={})

        d = self._entry.data

        options_schema = vol.Schema(
            {
                vol.Required(SECTION_HARDWARE): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Required(CONF_LIGHT_ENTITY, default=d.get(CONF_LIGHT_ENTITY)): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="light")
                            ),
                            vol.Required(CONF_PRESENCE_ENTITIES, default=d.get(CONF_PRESENCE_ENTITIES, [])): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                            ),
                            vol.Required(CONF_LUX_SENSOR, default=d.get(CONF_LUX_SENSOR)): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
                            ),
                            vol.Required(CONF_TARGET_LUX, default=d.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=1000, step=5, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Required(CONF_DEFAULT_LUX_RATIO, default=d.get(CONF_DEFAULT_LUX_RATIO, DEFAULT_LUX_RATIO)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0.01, max=20.0, step=0.05, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Required(CONF_PRESENCE_TIMEOUT_MIN, default=d.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=1, max=120, step=1, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(CONF_MIN_OCCUPIED_PCT, default=d.get(CONF_MIN_OCCUPIED_PCT, DEFAULT_MIN_OCCUPIED_PCT)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_CIRCADIAN): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_CIRCADIAN_ENABLED, default=d.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED)): selector.BooleanSelector(),
                            vol.Optional(CONF_MIN_COLOR_TEMP, default=d.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=2000, max=4000, step=100, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(CONF_MAX_COLOR_TEMP, default=d.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=4000, max=6500, step=100, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_LATE_NIGHT): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_LATE_NIGHT_ENABLED, default=d.get(CONF_LATE_NIGHT_ENABLED, DEFAULT_LATE_NIGHT_ENABLED)): selector.BooleanSelector(),
                            vol.Optional(CONF_LATE_NIGHT_PCT, default=d.get(CONF_LATE_NIGHT_PCT, DEFAULT_LATE_NIGHT_PCT)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                            vol.Optional(CONF_LATE_NIGHT_CONDITION_TYPE, default=d.get(CONF_LATE_NIGHT_CONDITION_TYPE, DEFAULT_LATE_NIGHT_CONDITION_TYPE)): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=[
                                        selector.SelectOptionDict(value="time", label="Time Schedule"),
                                        selector.SelectOptionDict(value="entity_state", label="Entity State (Helper/Group)"),
                                    ]
                                )
                            ),
                            vol.Optional(CONF_LATE_NIGHT_ENTITY, description={"suggested_value": d.get(CONF_LATE_NIGHT_ENTITY)}): OptionalEntitySelector(),
                            vol.Optional(CONF_LATE_NIGHT_START_TIME, description={"suggested_value": d.get(CONF_LATE_NIGHT_START_TIME, DEFAULT_LATE_NIGHT_START_TIME)}): OptionalTimeSelector(),
                            vol.Optional(CONF_LATE_NIGHT_START_ENTITY, description={"suggested_value": d.get(CONF_LATE_NIGHT_START_ENTITY)}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="input_datetime")
                            ),
                            vol.Optional(CONF_LATE_NIGHT_STOP_TIME, description={"suggested_value": d.get(CONF_LATE_NIGHT_STOP_TIME, DEFAULT_LATE_NIGHT_STOP_TIME)}): OptionalTimeSelector(),
                            vol.Optional(CONF_LATE_NIGHT_STOP_ENTITY, description={"suggested_value": d.get(CONF_LATE_NIGHT_STOP_ENTITY)}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="input_datetime")
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_MEDIA): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_MEDIA_ENTITIES, description={"suggested_value": d.get(CONF_MEDIA_ENTITIES, [])}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="media_player", multiple=True)
                            ),
                            vol.Optional(CONF_MEDIA_SEED_PCT, default=d.get(CONF_MEDIA_SEED_PCT, DEFAULT_MEDIA_SEED_PCT)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required(SECTION_BYPASSES): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_MANUAL_OVERRIDE_ENTITY, description={"suggested_value": d.get(CONF_MANUAL_OVERRIDE_ENTITY)}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain=["input_boolean", "switch"])
                            ),
                            vol.Optional(CONF_CREATE_OVERRIDE_SWITCH, default=d.get(CONF_CREATE_OVERRIDE_SWITCH, False)): selector.BooleanSelector(),
                            vol.Optional(CONF_BYPASS_FREEZE_ENTITIES, description={"suggested_value": d.get(CONF_BYPASS_FREEZE_ENTITIES, [])}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(multiple=True)
                            ),
                            vol.Optional(CONF_CREATE_FREEZE_SWITCH, default=d.get(CONF_CREATE_FREEZE_SWITCH, False)): selector.BooleanSelector(),
                            vol.Optional(CONF_BYPASS_OFF_ENTITIES, description={"suggested_value": d.get(CONF_BYPASS_OFF_ENTITIES, [])}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(multiple=True)
                            ),
                            vol.Optional(CONF_OVERRIDE_TIMEOUT_MIN, default=d.get(CONF_OVERRIDE_TIMEOUT_MIN, DEFAULT_OVERRIDE_TIMEOUT_MIN)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=5, max=240, step=5, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE, default=d.get(CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE, DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE)): selector.BooleanSelector(),
                            vol.Optional(CONF_POWER_GRID_ENTITY, description={"suggested_value": d.get(CONF_POWER_GRID_ENTITY)}): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                            ),
                            vol.Optional(CONF_SETTLING_COOLDOWN_SEC, default=d.get(CONF_SETTLING_COOLDOWN_SEC, DEFAULT_SETTLING_COOLDOWN_SEC)): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=5, max=180, step=5, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
