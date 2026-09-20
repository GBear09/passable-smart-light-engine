"""Config flow and options flow for Passable Adaptive Smart Lighting Controller."""

import logging
from typing import Any, Dict, List, Optional
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_BYPASS_FREEZE_ENTITIES,
    CONF_BYPASS_OFF_ENTITIES,
    CONF_CIRCADIAN_ENABLED,
    CONF_CREATE_FREEZE_SWITCH,
    CONF_CREATE_OVERRIDE_SWITCH,
    CONF_DEFAULT_LUX_RATIO,
    CONF_DECORATIONS_OFF_TIME,
    CONF_DECORATIONS_OFF_TRIGGER,
    CONF_DECORATIONS_ON_TRIGGER,
    CONF_DECORATIONS_SUNSET_OFFSET_MIN,
    CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT,
    CONF_EXTERIOR_BASELINE_KELVIN,
    CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED,
    CONF_EXTERIOR_LIGHTS,
    CONF_EXTERIOR_OFF_TIME,
    CONF_EXTERIOR_OFF_TRIGGER,
    CONF_EXTERIOR_ON_TIME,
    CONF_EXTERIOR_ON_TRIGGER,
    CONF_EXTERIOR_SUNRISE_OFFSET_MIN,
    CONF_EXTERIOR_SUNSET_OFFSET_MIN,
    CONF_HOLIDAY_DECORATIONS_ENABLED,
    CONF_HOLIDAY_GLOBAL_DECORATIONS,
    CONF_HOLIDAY_GLOBAL_LABEL,
    CONF_HOLIDAY_GLOBAL_LIGHTS,
    CONF_HOLIDAY_HOME_STATE_ENTITY,
    CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR,
    CONF_HOLIDAY_LIGHTING_ENABLED,
    CONF_HOLIDAY_OFF_TIME,
    CONF_HOLIDAY_OFF_TRIGGER,
    CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
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
    CONF_MEDIA_RESPECT_AMBIENT_LUX,
    CONF_MEDIA_SEED_PCT,
    CONF_MIN_COLOR_TEMP,
    CONF_MIN_OCCUPIED_PCT,
    CONF_OVERRIDE_TIMEOUT_MIN,
    CONF_POWER_GRID_ENTITY,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_ROOM_ID,
    CONF_SECONDARY_LIGHTS,
    CONF_SETTLING_COOLDOWN_SEC,
    CONF_SIMULATION_ARRIVAL_GRACE_MIN,
    CONF_SIMULATION_ENABLED,
    CONF_SIMULATION_JITTER_MIN,
    CONF_SIMULATION_LABEL,
    CONF_SIMULATION_LOOKBACK_DAYS,
    CONF_SIMULATION_MAX_BRIGHTNESS_PCT,
    CONF_SIMULATION_MODE,
    CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    CONF_TARGET_LUX,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_DECORATIONS_OFF_TIME,
    DEFAULT_DECORATIONS_OFF_TRIGGER,
    DEFAULT_DECORATIONS_ON_TRIGGER,
    DEFAULT_DECORATIONS_SUNSET_OFFSET_MIN,
    DEFAULT_EXTERIOR_BASELINE_BRIGHTNESS_PCT,
    DEFAULT_EXTERIOR_BASELINE_KELVIN,
    DEFAULT_EXTERIOR_DUSK_TO_DAWN_ENABLED,
    DEFAULT_EXTERIOR_LIGHTS,
    DEFAULT_EXTERIOR_OFF_TIME,
    DEFAULT_EXTERIOR_OFF_TRIGGER,
    DEFAULT_EXTERIOR_ON_TIME,
    DEFAULT_EXTERIOR_ON_TRIGGER,
    DEFAULT_EXTERIOR_SUNRISE_OFFSET_MIN,
    DEFAULT_EXTERIOR_SUNSET_OFFSET_MIN,
    DEFAULT_HOLIDAY_DECORATIONS_ENABLED,
    DEFAULT_HOLIDAY_GLOBAL_DECORATIONS,
    DEFAULT_HOLIDAY_GLOBAL_LABEL,
    DEFAULT_HOLIDAY_GLOBAL_LIGHTS,
    DEFAULT_HOLIDAY_HOME_STATE_ENTITY,
    DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR,
    DEFAULT_HOLIDAY_LIGHTING_ENABLED,
    DEFAULT_HOLIDAY_OFF_TIME,
    DEFAULT_HOLIDAY_OFF_TRIGGER,
    DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
    DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
    DEFAULT_LATE_NIGHT_CONDITION_TYPE,
    DEFAULT_LATE_NIGHT_ENABLED,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LATE_NIGHT_START_TIME,
    DEFAULT_LATE_NIGHT_STOP_TIME,
    DEFAULT_LUX_RATIO,
    DEFAULT_MAX_COLOR_TEMP,
    DEFAULT_MEDIA_RESPECT_AMBIENT_LUX,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_MIN_OCCUPIED_PCT,
    DEFAULT_OVERRIDE_TIMEOUT_MIN,
    DEFAULT_POWER_GRID_ENTITY,
    DEFAULT_PRESENCE_TIMEOUT_MIN,
    DEFAULT_SECONDARY_LIGHTS,
    DEFAULT_SETTLING_COOLDOWN_SEC,
    DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
    DEFAULT_SIMULATION_ENABLED,
    DEFAULT_SIMULATION_JITTER_MIN,
    DEFAULT_SIMULATION_LABEL,
    DEFAULT_SIMULATION_LOOKBACK_DAYS,
    DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
    DEFAULT_SIMULATION_MODE,
    DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
    DEFAULT_TARGET_LUX,
    DOMAIN,
    LIGHT_MODE_COLOR_TEMP,
    LIGHT_MODE_EFFECT,
    LIGHT_MODE_HUE_SCENE,
    LIGHT_MODE_RGB,
    LIGHT_MODES,
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


def get_available_bulb_effects(
    hass: Optional[HomeAssistant] = None, current_values: Optional[List[str]] = None
) -> List[selector.SelectOptionDict]:
    """Collect known and dynamically discovered bulb firmware effects across all lights in Home Assistant."""
    known_effects: Dict[str, str] = {
        "candle": "🕯️ Candle",
        "fire": "🔥 Fire",
        "prism": "🌈 Prism",
        "sparkle": "✨ Sparkle",
        "opal": "💎 Opal",
        "glisten": "🌟 Glisten",
        "sunrise": "🌅 Sunrise",
        "sunset": "🌇 Sunset",
        "underwater": "🌊 Underwater",
        "cosmos": "🌌 Cosmos",
        "enchant": "✨ Enchant",
        "sunbeam": "☀️ Sunbeam",
        "Slow Pulse": "💓 Slow Pulse",
        "Fast Pulse": "⚡ Fast Pulse",
    }

    discovered: Dict[str, str] = {}
    if hass and hasattr(hass, "states"):
        for state in hass.states.async_all("light"):
            eff_list = state.attributes.get("effect_list")
            if eff_list and isinstance(eff_list, (list, tuple)):
                for eff in eff_list:
                    if eff and isinstance(eff, str):
                        s_eff = eff.strip()
                        if s_eff.lower() in ("none", "off", ""):
                            continue
                        if s_eff not in discovered:
                            discovered[s_eff] = known_effects.get(s_eff, s_eff.title())

    for k, v in known_effects.items():
        if k not in discovered:
            discovered[k] = v

    if current_values:
        for cv in current_values:
            if cv and isinstance(cv, str) and cv.strip() and cv.strip().lower() not in ("none", "off", ""):
                c_clean = cv.strip()
                if c_clean not in discovered:
                    discovered[c_clean] = known_effects.get(c_clean, c_clean.title())

    options = [selector.SelectOptionDict(value="", label="None / No Effect")]
    for val, lbl in sorted(discovered.items(), key=lambda x: x[1].lower()):
        options.append(selector.SelectOptionDict(value=val, label=lbl))

    return options


class PassableSmartLightingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Passable Adaptive Smart Lighting Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._step1_data: Dict[str, Any] = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Choose between setting up a room, presence simulation, or holiday lighting."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["room", "presence_simulation", "holiday_lighting"],
        )

    async def async_step_room(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
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
                vol.Optional(CONF_SECONDARY_LIGHTS, default=DEFAULT_SECONDARY_LIGHTS): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True)
                ),
                vol.Optional(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, default=DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON): selector.BooleanSelector(),
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

        return self.async_show_form(step_id="room", data_schema=step1_schema, errors=errors)

    async def async_step_import(self, import_data: Dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Auto-create dedicated presence simulation config entry from system."""
        if import_data.get("entry_type") == "presence_simulation":
            await self.async_set_unique_id(f"{DOMAIN}_presence_simulation")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Presence Simulation",
                data={
                    "entry_type": "presence_simulation",
                    CONF_SIMULATION_ENABLED: DEFAULT_SIMULATION_ENABLED,
                    CONF_SIMULATION_LABEL: DEFAULT_SIMULATION_LABEL,
                    CONF_SIMULATION_MODE: DEFAULT_SIMULATION_MODE,
                    CONF_SIMULATION_LOOKBACK_DAYS: DEFAULT_SIMULATION_LOOKBACK_DAYS,
                    CONF_SIMULATION_JITTER_MIN: DEFAULT_SIMULATION_JITTER_MIN,
                    CONF_SIMULATION_ARRIVAL_GRACE_MIN: DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
                    CONF_SIMULATION_MAX_BRIGHTNESS_PCT: DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
                },
            )
        if import_data.get("entry_type") == "holiday_lighting":
            await self.async_set_unique_id(f"{DOMAIN}_holiday_lighting")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Holiday & Exterior Lighting",
                data={"entry_type": "holiday_lighting"},
            )
        return self.async_abort(reason="unknown_import")

    async def async_step_holiday_lighting(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Configure or initialize holiday lighting subsystem."""
        await self.async_set_unique_id(f"{DOMAIN}_holiday_lighting")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Holiday & Exterior Lighting",
            data={"entry_type": "holiday_lighting"},
        )


    async def async_step_presence_simulation(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Configure presence simulation settings."""
        await self.async_set_unique_id(f"{DOMAIN}_presence_simulation")
        self._abort_if_unique_id_configured()

        if user_input is not None:
            data = {"entry_type": "presence_simulation", **user_input}
            return self.async_create_entry(title="Presence Simulation", data=data)

        target_label = DEFAULT_SIMULATION_LABEL
        reg = er.async_get(self.hass)
        matching_lights = [
            entry.entity_id
            for entry in reg.entities.values()
            if entry.domain == "light" and not entry.disabled and target_label in entry.labels
        ]
        matching_lights.sort()

        if matching_lights:
            lights_list = "\n".join(f"- `{entity_id}`" for entity_id in matching_lights)
            summary_text = (
                f"**Currently Included Lights ({len(matching_lights)}) with label `{target_label}`:**\n"
                f"{lights_list}"
            )
        else:
            summary_text = (
                f"ℹ️ **No lights currently tagged with label `{target_label}`.**\n\n"
                f"You can tag lights in Home Assistant at any time (Settings → Devices & Services → Entities → select light → Labels)."
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_SIMULATION_ENABLED, default=DEFAULT_SIMULATION_ENABLED): selector.BooleanSelector(),
                vol.Required(CONF_SIMULATION_LABEL, default=target_label): selector.TextSelector(),
                vol.Required(CONF_SIMULATION_MODE, default=DEFAULT_SIMULATION_MODE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="hybrid", label="Hybrid (Smart History Replay with Synthetic Fallback)"),
                            selector.SelectOptionDict(value="history_replay", label="Smart History Replay Only"),
                            selector.SelectOptionDict(value="synthetic_routine", label="Synthetic Realistic Evening Routine Only"),
                        ]
                    )
                ),
                vol.Required(CONF_SIMULATION_LOOKBACK_DAYS, default=DEFAULT_SIMULATION_LOOKBACK_DAYS): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_JITTER_MIN, default=DEFAULT_SIMULATION_JITTER_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=60, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_ARRIVAL_GRACE_MIN, default=DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, default=DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
            }
        )
        return self.async_show_form(
            step_id="presence_simulation",
            data_schema=schema,
            description_placeholders={"lights_summary": summary_text},
        )

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
                            vol.Optional(CONF_MIN_COLOR_TEMP, default=DEFAULT_MIN_COLOR_TEMP): selector.ColorTempSelector(
                                selector.ColorTempSelectorConfig(
                                    min=2000,
                                    max=4000,
                                    unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                                )
                            ),
                            vol.Optional(CONF_MAX_COLOR_TEMP, default=DEFAULT_MAX_COLOR_TEMP): selector.ColorTempSelector(
                                selector.ColorTempSelectorConfig(
                                    min=4000,
                                    max=6500,
                                    unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                                )
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
                            vol.Optional(CONF_MEDIA_RESPECT_AMBIENT_LUX, default=DEFAULT_MEDIA_RESPECT_AMBIENT_LUX): selector.BooleanSelector(),
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
        """Manage room, presence simulation, or holiday lighting options."""
        if self._entry.data.get("entry_type") == "presence_simulation":
            return await self.async_step_presence_simulation_options(user_input)

        if self._entry.data.get("entry_type") == "holiday_lighting":
            return await self.async_step_holiday_menu()

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
                            vol.Optional(CONF_SECONDARY_LIGHTS, default=d.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS)): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="light", multiple=True)
                            ),
                            vol.Optional(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, default=d.get(CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON, DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON)): selector.BooleanSelector(),
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
                            vol.Optional(CONF_MIN_COLOR_TEMP, default=d.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP)): selector.ColorTempSelector(
                                selector.ColorTempSelectorConfig(
                                    min=2000,
                                    max=4000,
                                    unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                                )
                            ),
                            vol.Optional(CONF_MAX_COLOR_TEMP, default=d.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP)): selector.ColorTempSelector(
                                selector.ColorTempSelectorConfig(
                                    min=4000,
                                    max=6500,
                                    unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                                )
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
                            vol.Optional(
                                CONF_MEDIA_RESPECT_AMBIENT_LUX,
                                default=d.get(CONF_MEDIA_RESPECT_AMBIENT_LUX, DEFAULT_MEDIA_RESPECT_AMBIENT_LUX),
                            ): selector.BooleanSelector(),
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

    async def async_step_presence_simulation_options(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Manage presence simulation options and show current included lights."""
        d = self._entry.data
        target_label = d.get(CONF_SIMULATION_LABEL, DEFAULT_SIMULATION_LABEL)

        if user_input is not None:
            new_data = {**self._entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
            if coordinator:
                coordinator.update_options(new_data)
            return self.async_create_entry(title="", data={})

        reg = er.async_get(self.hass)
        matching_lights = [
            entry.entity_id
            for entry in reg.entities.values()
            if entry.domain == "light" and not entry.disabled and target_label in entry.labels
        ]
        matching_lights.sort()

        if matching_lights:
            lights_list = "\n".join(f"- `{entity_id}`" for entity_id in matching_lights)
            summary_text = (
                f"**Currently Included Lights ({len(matching_lights)}) with label `{target_label}`:**\n"
                f"{lights_list}"
            )
        else:
            summary_text = (
                f"⚠️ **No lights currently found with label `{target_label}`.**\n\n"
                f"To include lights, assign the label `{target_label}` to any light entity in Home Assistant "
                f"(Settings → Devices & Services → Entities → select light → Labels)."
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SIMULATION_ENABLED,
                    default=d.get(CONF_SIMULATION_ENABLED, DEFAULT_SIMULATION_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(CONF_SIMULATION_LABEL, default=target_label): selector.TextSelector(),
                vol.Required(CONF_SIMULATION_MODE, default=d.get(CONF_SIMULATION_MODE, DEFAULT_SIMULATION_MODE)): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="hybrid", label="Hybrid (Smart History Replay with Synthetic Fallback)"),
                            selector.SelectOptionDict(value="history_replay", label="Smart History Replay Only"),
                            selector.SelectOptionDict(value="synthetic_routine", label="Synthetic Realistic Evening Routine Only"),
                        ]
                    )
                ),
                vol.Required(CONF_SIMULATION_LOOKBACK_DAYS, default=d.get(CONF_SIMULATION_LOOKBACK_DAYS, DEFAULT_SIMULATION_LOOKBACK_DAYS)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_JITTER_MIN, default=d.get(CONF_SIMULATION_JITTER_MIN, DEFAULT_SIMULATION_JITTER_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=60, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_ARRIVAL_GRACE_MIN, default=d.get(CONF_SIMULATION_ARRIVAL_GRACE_MIN, DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, default=d.get(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
            }
        )
        return self.async_show_form(
            step_id="presence_simulation_options",
            data_schema=schema,
            description_placeholders={"lights_summary": summary_text},
        )

    async def async_step_holiday_menu(self, user_input: Optional[Dict[str, Any]] = None) -> config_entries.ConfigFlowResult:
        """Main menu for Holiday & Exterior Lighting options."""
        return self.async_show_menu(
            step_id="holiday_menu",
            menu_options=[
                "holiday_exterior_settings",
                "holiday_decoration_settings",
                "holiday_select",
                "holiday_reset",
            ],
        )

    async def async_step_holiday_global_settings(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Redirect legacy global settings to exterior settings."""
        return await self.async_step_holiday_exterior_settings(user_input)

    async def async_step_holiday_exterior_settings(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure year-round dusk-to-dawn exterior lighting settings."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options

        if user_input is not None:
            holiday_store.update_options(user_input)
            await holiday_store.async_save()
            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED,
                    default=opts.get(CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED, DEFAULT_EXTERIOR_DUSK_TO_DAWN_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_EXTERIOR_LIGHTS,
                    default=opts.get(CONF_EXTERIOR_LIGHTS, DEFAULT_EXTERIOR_LIGHTS),
                ): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True)
                ),
                vol.Required(
                    CONF_EXTERIOR_ON_TRIGGER,
                    default=opts.get(CONF_EXTERIOR_ON_TRIGGER, DEFAULT_EXTERIOR_ON_TRIGGER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="sunset", label="At Sunset (with Offset)"),
                            selector.SelectOptionDict(value="fixed_time", label="At Specific Time"),
                        ]
                    )
                ),
                vol.Optional(
                    CONF_EXTERIOR_SUNSET_OFFSET_MIN,
                    default=opts.get(CONF_EXTERIOR_SUNSET_OFFSET_MIN, DEFAULT_EXTERIOR_SUNSET_OFFSET_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_EXTERIOR_ON_TIME,
                    default=opts.get(CONF_EXTERIOR_ON_TIME, DEFAULT_EXTERIOR_ON_TIME),
                ): OptionalTimeSelector(),
                vol.Required(
                    CONF_EXTERIOR_OFF_TRIGGER,
                    default=opts.get(CONF_EXTERIOR_OFF_TRIGGER, DEFAULT_EXTERIOR_OFF_TRIGGER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="sunrise", label="At Sunrise (with Offset)"),
                            selector.SelectOptionDict(value="fixed_time", label="At Specific Time"),
                        ]
                    )
                ),
                vol.Optional(
                    CONF_EXTERIOR_SUNRISE_OFFSET_MIN,
                    default=opts.get(CONF_EXTERIOR_SUNRISE_OFFSET_MIN, DEFAULT_EXTERIOR_SUNRISE_OFFSET_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_EXTERIOR_OFF_TIME,
                    default=opts.get(CONF_EXTERIOR_OFF_TIME, DEFAULT_EXTERIOR_OFF_TIME),
                ): OptionalTimeSelector(),
                vol.Required(
                    CONF_EXTERIOR_BASELINE_KELVIN,
                    default=opts.get(CONF_EXTERIOR_BASELINE_KELVIN, DEFAULT_EXTERIOR_BASELINE_KELVIN),
                ): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(
                        min=2000,
                        max=6500,
                        unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                    )
                ),
                vol.Required(
                    CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT,
                    default=opts.get(CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT, DEFAULT_EXTERIOR_BASELINE_BRIGHTNESS_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Required(
                    CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR,
                    default=opts.get(CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR, DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="all_night", label="All Night (Keep Holiday Scene Until Sunrise)"),
                            selector.SelectOptionDict(value="revert_to_baseline_at_sleep", label="Revert to Warm White Baseline at Sleep"),
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(step_id="holiday_exterior_settings", data_schema=schema)

    async def async_step_holiday_decoration_settings(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure holiday outdoor decoration plug schedule and triggers."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options

        if user_input is not None:
            holiday_store.update_options(user_input)
            await holiday_store.async_save()
            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOLIDAY_DECORATIONS_ENABLED,
                    default=opts.get(CONF_HOLIDAY_DECORATIONS_ENABLED, DEFAULT_HOLIDAY_DECORATIONS_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_HOLIDAY_GLOBAL_DECORATIONS,
                    default=opts.get(CONF_HOLIDAY_GLOBAL_DECORATIONS, DEFAULT_HOLIDAY_GLOBAL_DECORATIONS),
                ): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="switch", multiple=True)
                ),
                vol.Required(
                    CONF_HOLIDAY_GLOBAL_LABEL,
                    default=opts.get(CONF_HOLIDAY_GLOBAL_LABEL, DEFAULT_HOLIDAY_GLOBAL_LABEL),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_DECORATIONS_ON_TRIGGER,
                    default=opts.get(CONF_DECORATIONS_ON_TRIGGER, DEFAULT_DECORATIONS_ON_TRIGGER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="sunset", label="At Sunset (with Offset)"),
                            selector.SelectOptionDict(value="fixed_time", label="At Specific Time"),
                        ]
                    )
                ),
                vol.Optional(
                    CONF_DECORATIONS_SUNSET_OFFSET_MIN,
                    default=opts.get(CONF_DECORATIONS_SUNSET_OFFSET_MIN, DEFAULT_DECORATIONS_SUNSET_OFFSET_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_DECORATIONS_OFF_TRIGGER,
                    default=opts.get(CONF_DECORATIONS_OFF_TRIGGER, DEFAULT_DECORATIONS_OFF_TRIGGER),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="sleep", label="When Home State is Sleep (Bedtime)"),
                            selector.SelectOptionDict(value="sunrise", label="At Sunrise"),
                            selector.SelectOptionDict(value="fixed_time", label="At Specific Cutoff Time"),
                        ]
                    )
                ),
                vol.Optional(
                    CONF_DECORATIONS_OFF_TIME,
                    default=opts.get(CONF_DECORATIONS_OFF_TIME, DEFAULT_DECORATIONS_OFF_TIME),
                ): OptionalTimeSelector(),
                vol.Optional(
                    CONF_HOLIDAY_HOME_STATE_ENTITY,
                    default=opts.get(CONF_HOLIDAY_HOME_STATE_ENTITY, DEFAULT_HOLIDAY_HOME_STATE_ENTITY),
                ): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="input_select")
                ),
                vol.Required(
                    CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
                    default=opts.get(CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION, DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="holiday_decoration_settings", data_schema=schema)

    async def async_step_holiday_select(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Select a holiday to customize or choose to add a new holiday."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        if user_input is not None:
            self._selected_holiday_id = user_input["selected_holiday"]
            return await self.async_step_holiday_edit()

        holidays = holiday_store.holidays
        options = [
            selector.SelectOptionDict(value="__add_new__", label="➕ Add New Holiday...")
        ]
        for h_id, h in sorted(holidays.items(), key=lambda x: x[1].get("start_date", "")):
            s_date = h.get("start_date", "")
            e_date = h.get("end_date", "")
            name = h.get("name", h_id)
            mode = h.get("light_mode", "rgb")
            options.append(
                selector.SelectOptionDict(
                    value=h_id,
                    label=f"{name} ({s_date} to {e_date}) [{mode}]",
                )
            )

        schema = vol.Schema(
            {
                vol.Required("selected_holiday", default="__add_new__"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }
        )
        return self.async_show_form(step_id="holiday_select", data_schema=schema)

    async def async_step_holiday_edit(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Edit details of a holiday or create a new one."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = {} if is_new else holiday_store.holidays.get(self._selected_holiday_id, {})

        if user_input is not None:
            if user_input.get("delete_holiday") and not is_new:
                holiday_store.delete_holiday(self._selected_holiday_id)
                await holiday_store.async_save()
                return self.async_create_entry(title="", data={})

            h_name = str(user_input.get("name", curr_holiday.get("name", "Custom Holiday"))).strip()
            h_id = self._selected_holiday_id if not is_new else h_name.lower().replace(" ", "_").replace("'", "")

            raw_rgb = user_input.get("rgb_color")
            if isinstance(raw_rgb, (list, tuple)) and len(raw_rgb) >= 3:
                rgb = [int(raw_rgb[0]), int(raw_rgb[1]), int(raw_rgb[2])]
            elif "rgb_red" in user_input:
                rgb = [
                    int(user_input.get("rgb_red", 255)),
                    int(user_input.get("rgb_green", 140)),
                    int(user_input.get("rgb_blue", 0)),
                ]
            else:
                rgb = curr_holiday.get("rgb_color", [255, 140, 0])

            holiday_data = {
                "id": h_id,
                "name": h_name,
                "enabled": bool(user_input.get("enabled", True)),
                "start_date": str(user_input.get("start_date", "10-01")).strip(),
                "end_date": str(user_input.get("end_date", "10-31")).strip(),
                "icon": str(user_input.get("icon", "mdi:calendar-star")).strip(),
                "phrase": str(user_input.get("phrase", "")).strip(),
                "theme_color": str(user_input.get("theme_color", "#9c4600")).strip(),
                "light_mode": user_input.get("light_mode", LIGHT_MODE_RGB),
                "hue_scene": str(user_input.get("hue_scene") or "").strip(),
                "dynamic_scene": bool(user_input.get("dynamic_scene", False)),
                "effect": str(user_input.get("effect") or "").strip(),
                "fallback_effect": str(user_input.get("fallback_effect") or "").strip(),
                "rgb_color": rgb,
                "color_temp_kelvin": int(user_input.get("color_temp_kelvin", 2500)),
                "brightness_pct": int(user_input.get("brightness_pct", 100)),
                "decorations_on": bool(user_input.get("decorations_on", True)),
                "participating_lights": user_input.get("participating_lights") or [],
                "participating_decorations": user_input.get("participating_decorations") or [],
            }

            holiday_store.set_holiday(h_id, holiday_data)
            await holiday_store.async_save()

            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                coordinator._active_holiday = coordinator.evaluate_active_holiday()
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())

            return self.async_create_entry(title="", data={})

        d_rgb = curr_holiday.get("rgb_color", [255, 140, 0])
        curr_effect = curr_holiday.get("effect") or ""
        curr_fallback_effect = curr_holiday.get("fallback_effect") or "fire"
        effect_options = get_available_bulb_effects(
            self.hass, [curr_effect, curr_fallback_effect]
        )

        fields = {
            vol.Required("name", default=curr_holiday.get("name", "Custom Holiday")): selector.TextSelector(),
            vol.Required("enabled", default=curr_holiday.get("enabled", True)): selector.BooleanSelector(),
            vol.Required("start_date", default=curr_holiday.get("start_date", "10-01")): selector.TextSelector(),
            vol.Required("end_date", default=curr_holiday.get("end_date", "10-31")): selector.TextSelector(),
            vol.Required("icon", default=curr_holiday.get("icon", "mdi:ghost")): selector.TextSelector(),
            vol.Optional("phrase", default=curr_holiday.get("phrase", "Happy Holidays!")): selector.TextSelector(),
            vol.Optional("theme_color", default=curr_holiday.get("theme_color", "#9c4600")): selector.TextSelector(),
            vol.Required("light_mode", default=curr_holiday.get("light_mode", LIGHT_MODE_RGB)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="hue_scene", label="Philips Hue Dynamic Scene"),
                        selector.SelectOptionDict(value="effect", label="Bulb Firmware Effect (fire, candle, prism)"),
                        selector.SelectOptionDict(value="rgb", label="RGB Color Palette"),
                        selector.SelectOptionDict(value="color_temp", label="Color Temperature (Kelvin)"),
                    ]
                )
            ),
            vol.Optional("hue_scene", default=curr_holiday.get("hue_scene", "")): OptionalEntitySelector(
                selector.EntitySelectorConfig(domain="scene")
            ),
            vol.Optional("dynamic_scene", default=curr_holiday.get("dynamic_scene", True)): selector.BooleanSelector(),
            vol.Optional("effect", default=curr_effect): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=effect_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("fallback_effect", default=curr_fallback_effect): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=effect_options,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional("rgb_color", default=curr_holiday.get("rgb_color", [255, 140, 0])): selector.ColorRGBSelector(),
            vol.Optional("color_temp_kelvin", default=curr_holiday.get("color_temp_kelvin", 2200)): selector.ColorTempSelector(
                selector.ColorTempSelectorConfig(
                    min=2000,
                    max=6500,
                    unit=getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin"),
                )
            ),
            vol.Required("brightness_pct", default=curr_holiday.get("brightness_pct", 100)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
            ),
            vol.Required("decorations_on", default=curr_holiday.get("decorations_on", True)): selector.BooleanSelector(),
            vol.Optional("participating_lights", default=curr_holiday.get("participating_lights", [])): OptionalEntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional("participating_decorations", default=curr_holiday.get("participating_decorations", [])): OptionalEntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            ),
        }

        if not is_new:
            fields[vol.Optional("delete_holiday", default=False)] = selector.BooleanSelector()

        schema = vol.Schema(fields)
        return self.async_show_form(step_id="holiday_edit", data_schema=schema)

    async def async_step_holiday_reset(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Reset holiday catalog to factory defaults."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        if user_input is not None:
            if user_input.get("confirm_reset"):
                holiday_store.reset_defaults()
                await holiday_store.async_save()
                _LOGGER.info("PassableSmartLighting: Reset holiday catalog to factory defaults.")
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required("confirm_reset", default=False): selector.BooleanSelector()
            }
        )
        return self.async_show_form(step_id="holiday_reset", data_schema=schema)

