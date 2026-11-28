"""Config flow and Options flow for Passable Smart Light Engine."""

from collections.abc import Mapping
import copy
import logging
import re
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
    CONF_DECORATIONS_OFF_TIME,
    CONF_DECORATIONS_OFF_TRIGGER,
    CONF_DECORATIONS_ON_TIME,
    CONF_DECORATIONS_ON_TRIGGER,
    CONF_DECORATIONS_SUNSET_OFFSET_MIN,
    CONF_DEFAULT_LUX_RATIO,
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
    CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
    CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
    CONF_LATE_NIGHT_CONDITION_TYPE,
    CONF_LATE_NIGHT_ENABLED,
    CONF_LATE_NIGHT_ENTITY,
    CONF_LATE_NIGHT_ENTITY_STATES,
    CONF_LATE_NIGHT_LEARN_PREFS,
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
    CONF_MEDIA_LEARN_PREFS,
    CONF_MEDIA_RESPECT_AMBIENT_LUX,
    CONF_MEDIA_SEED_PCT,
    CONF_MIN_COLOR_TEMP,
    CONF_MIN_OCCUPIED_PCT,
    CONF_NOTIFICATION_BRIGHTNESS_PCT,
    CONF_NOTIFICATION_COLOR,
    CONF_NOTIFICATION_LIGHT_ENABLED,
    CONF_NOTIFICATION_LIGHT_ENTITY,
    CONF_NOTIFICATION_PRESENCE_GATED,
    CONF_NOTIFICATION_SUPPRESSION_ENTITIES,
    CONF_NOTIFICATION_TRIGGER_ENTITY,
    CONF_OVERRIDE_TIMEOUT_MIN,
    CONF_POWER_GRID_ENTITY,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_TIMEOUT_MIN,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
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
    CONF_TIMEOUT_SCALE_ENTITIES,
    CONF_TIMEOUT_SCALE_FACTOR,
    DEFAULT_CIRCADIAN_ENABLED,
    DEFAULT_DECORATIONS_OFF_TIME,
    DEFAULT_DECORATIONS_OFF_TRIGGER,
    DEFAULT_DECORATIONS_ON_TIME,
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
    DEFAULT_HOLIDAY_HOME_STATE_ENTITY,
    DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR,
    DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
    DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
    DEFAULT_LATE_NIGHT_CONDITION_TYPE,
    DEFAULT_LATE_NIGHT_ENABLED,
    DEFAULT_LATE_NIGHT_ENTITY_STATES,
    DEFAULT_LATE_NIGHT_LEARN_PREFS,
    DEFAULT_LATE_NIGHT_PCT,
    DEFAULT_LATE_NIGHT_START_TIME,
    DEFAULT_LATE_NIGHT_STOP_TIME,
    DEFAULT_LUX_RATIO,
    DEFAULT_MAX_COLOR_TEMP,
    DEFAULT_MEDIA_LEARN_PREFS,
    DEFAULT_MEDIA_RESPECT_AMBIENT_LUX,
    DEFAULT_MEDIA_SEED_PCT,
    DEFAULT_MIN_COLOR_TEMP,
    DEFAULT_MIN_OCCUPIED_PCT,
    DEFAULT_NOTIFICATION_BRIGHTNESS_PCT,
    DEFAULT_NOTIFICATION_COLOR,
    DEFAULT_NOTIFICATION_LIGHT_ENABLED,
    DEFAULT_NOTIFICATION_PRESENCE_GATED,
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
    DEFAULT_TIMEOUT_SCALE_ENTITIES,
    DEFAULT_TIMEOUT_SCALE_FACTOR,
    DOMAIN,
    LATE_NIGHT_MODE_DATETIME_HELPER,
    LATE_NIGHT_MODE_ENTITY_STATE,
    LATE_NIGHT_MODE_FIXED_TIME,
    LIGHT_MODE_COLOR_TEMP,
    LIGHT_MODE_DEFAULT,
    LIGHT_MODE_EFFECT,
    LIGHT_MODE_HA_SCENE,
    LIGHT_MODE_HUE_SCENE,
    LIGHT_MODE_OFF,
    LIGHT_MODE_RGB,
    LIGHT_MODE_WLED_PRESET,
    SECTION_AUXILIARY_TUNING,
    SECTION_BYPASS_ENTITIES,
    SECTION_HARDWARE_SAFEGUARDS,
    SECTION_OVERRIDE_BEHAVIOR,
)
from .engine import get_light_members, normalize_late_night_mode
from .holiday_lighting import discover_light_companions


class OptionalEntitySelector(selector.EntitySelector):
    """EntitySelector that safely accepts None or empty string when optional."""

    def __call__(self, data: Any) -> Any:
        """Validate input or allow None when empty."""
        if data is None or data == "":
            return [] if self.config.get("multiple") else None
        if self.config.get("multiple") and isinstance(data, list):
            return [x for x in data if x]
        return super().__call__(data)


class OptionalTimeSelector(selector.TimeSelector):
    """TimeSelector that safely accepts None or empty string when optional."""

    def __call__(self, data: Any) -> Any:
        """Validate input or allow None when empty."""
        if data is None or data == "":
            return None
        return super().__call__(data)


def _slugify_room_id(value: str) -> str:
    """Convert a friendly room name or ID into a clean snake_case room_id."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _existing_entities_or_empty(hass: Optional[HomeAssistant], val: Any) -> Any:
    """Filter default entities to those present in Home Assistant states."""
    if not hass or not hasattr(hass, "states"):
        return [] if isinstance(val, list) else None
    if isinstance(val, list):
        return [e for e in val if isinstance(e, str) and hass.states.get(e) is not None]
    if isinstance(val, str) and val.strip():
        return val if hass.states.get(val.strip()) is not None else None
    return None


def _unpack_sections(user_input: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten Home Assistant section dictionaries into a single dict."""
    flat: Dict[str, Any] = {}
    for key, val in user_input.items():
        if isinstance(val, dict):
            flat.update(val)
        else:
            flat[key] = val
    return flat


def _validate_mm_dd(val: Any) -> bool:
    """Validate MM-DD date strings."""
    if not isinstance(val, str):
        return False
    parts = val.strip().split("-")
    if len(parts) != 2:
        return False
    try:
        month = int(parts[0])
        day = int(parts[1])
    except ValueError:
        return False
    return 1 <= month <= 12 and 1 <= day <= 31


def _late_night_mode_options() -> List[selector.SelectOptionDict]:
    """Return SelectSelector options for the 3 explicit Late Night trigger modes."""
    return [
        selector.SelectOptionDict(
            value=LATE_NIGHT_MODE_FIXED_TIME,
            label="Fixed Clock Schedule (Daily Start & Stop Times)",
        ),
        selector.SelectOptionDict(
            value=LATE_NIGHT_MODE_DATETIME_HELPER,
            label="Dynamic Time Helpers (input_datetime Start & Stop)",
        ),
        selector.SelectOptionDict(
            value=LATE_NIGHT_MODE_ENTITY_STATE,
            label="Entity / Home State (Switch, Sensor, Group, or input_select)",
        ),
    ]


def _late_night_mode_label(mode: str) -> str:
    """Return human-readable label for a normalized Late Night trigger mode."""
    if mode == LATE_NIGHT_MODE_DATETIME_HELPER:
        return "Dynamic Time Helpers (`input_datetime`)"
    if mode == LATE_NIGHT_MODE_ENTITY_STATE:
        return "Entity / Home State"
    return "Fixed Clock Schedule"


def _build_late_night_details_schema(
    cond_type: str, defaults: Mapping[str, Any], is_options: bool = False
) -> vol.Schema:
    """Build schema containing only the inputs relevant to the selected Late Night mode."""
    if cond_type == LATE_NIGHT_MODE_DATETIME_HELPER:
        if is_options:
            return vol.Schema(
                {
                    vol.Optional(
                        CONF_LATE_NIGHT_START_ENTITY,
                        description={"suggested_value": defaults.get(CONF_LATE_NIGHT_START_ENTITY)},
                    ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="input_datetime")),
                    vol.Optional(
                        CONF_LATE_NIGHT_STOP_ENTITY,
                        description={"suggested_value": defaults.get(CONF_LATE_NIGHT_STOP_ENTITY)},
                    ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="input_datetime")),
                }
            )
        return vol.Schema(
            {
                vol.Optional(CONF_LATE_NIGHT_START_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="input_datetime")
                ),
                vol.Optional(CONF_LATE_NIGHT_STOP_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="input_datetime")
                ),
            }
        )

    if cond_type == LATE_NIGHT_MODE_ENTITY_STATE:
        if is_options:
            return vol.Schema(
                {
                    vol.Optional(
                        CONF_LATE_NIGHT_ENTITY,
                        description={"suggested_value": defaults.get(CONF_LATE_NIGHT_ENTITY)},
                    ): OptionalEntitySelector(
                        selector.EntitySelectorConfig(
                            domain=[
                                "input_boolean",
                                "binary_sensor",
                                "switch",
                                "group",
                                "schedule",
                                "input_select",
                                "sensor",
                            ]
                        )
                    ),
                    vol.Optional(
                        CONF_LATE_NIGHT_ENTITY_STATES,
                        description={
                            "suggested_value": defaults.get(
                                CONF_LATE_NIGHT_ENTITY_STATES, DEFAULT_LATE_NIGHT_ENTITY_STATES
                            )
                        },
                    ): selector.TextSelector(),
                }
            )
        return vol.Schema(
            {
                vol.Optional(CONF_LATE_NIGHT_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(
                        domain=[
                            "input_boolean",
                            "binary_sensor",
                            "switch",
                            "group",
                            "schedule",
                            "input_select",
                            "sensor",
                        ]
                    )
                ),
                vol.Optional(
                    CONF_LATE_NIGHT_ENTITY_STATES,
                    default=defaults.get(
                        CONF_LATE_NIGHT_ENTITY_STATES, DEFAULT_LATE_NIGHT_ENTITY_STATES
                    ),
                ): selector.TextSelector(),
            }
        )

    return vol.Schema(
        {
            vol.Required(
                CONF_LATE_NIGHT_START_TIME,
                default=defaults.get(CONF_LATE_NIGHT_START_TIME, DEFAULT_LATE_NIGHT_START_TIME)
                or DEFAULT_LATE_NIGHT_START_TIME,
            ): OptionalTimeSelector(),
            vol.Required(
                CONF_LATE_NIGHT_STOP_TIME,
                default=defaults.get(CONF_LATE_NIGHT_STOP_TIME, DEFAULT_LATE_NIGHT_STOP_TIME)
                or DEFAULT_LATE_NIGHT_STOP_TIME,
            ): OptionalTimeSelector(),
        }
    )


def _validate_late_night_details(cond_type: str, data: Mapping[str, Any]) -> Dict[str, str]:
    """Validate mode-specific required Late Night inputs."""
    errors: Dict[str, str] = {}
    if cond_type == LATE_NIGHT_MODE_ENTITY_STATE:
        if not data.get(CONF_LATE_NIGHT_ENTITY):
            errors[CONF_LATE_NIGHT_ENTITY] = "missing_late_night_entity"
    elif cond_type == LATE_NIGHT_MODE_DATETIME_HELPER:
        if not data.get(CONF_LATE_NIGHT_START_ENTITY):
            errors[CONF_LATE_NIGHT_START_ENTITY] = "missing_datetime_helper"
        if not data.get(CONF_LATE_NIGHT_STOP_ENTITY):
            errors[CONF_LATE_NIGHT_STOP_ENTITY] = "missing_datetime_helper"
    else:
        if not data.get(CONF_LATE_NIGHT_START_TIME):
            errors[CONF_LATE_NIGHT_START_TIME] = "missing_schedule_time"
        if not data.get(CONF_LATE_NIGHT_STOP_TIME):
            errors[CONF_LATE_NIGHT_STOP_TIME] = "missing_schedule_time"
    return errors


def _build_bypasses_sections_schema(
    hass: Optional[HomeAssistant], defaults: Mapping[str, Any], is_options: bool = False
) -> vol.Schema:
    """Build categorized bypass, override, and sensor-safeguard sections."""
    default_grid = defaults.get(CONF_POWER_GRID_ENTITY)
    if CONF_POWER_GRID_ENTITY not in defaults:
        default_grid = _existing_entities_or_empty(hass, DEFAULT_POWER_GRID_ENTITY)

    if is_options:
        override_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OVERRIDE_TIMEOUT_MIN,
                    default=defaults.get(CONF_OVERRIDE_TIMEOUT_MIN, DEFAULT_OVERRIDE_TIMEOUT_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=240, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
                    default=defaults.get(
                        CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE, DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_CREATE_OVERRIDE_SWITCH,
                    default=defaults.get(CONF_CREATE_OVERRIDE_SWITCH, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_MANUAL_OVERRIDE_ENTITY,
                    description={"suggested_value": defaults.get(CONF_MANUAL_OVERRIDE_ENTITY)},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain=["input_boolean", "switch"])),
            }
        )
        bypass_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CREATE_FREEZE_SWITCH,
                    default=defaults.get(CONF_CREATE_FREEZE_SWITCH, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_BYPASS_FREEZE_ENTITIES,
                    description={"suggested_value": defaults.get(CONF_BYPASS_FREEZE_ENTITIES, [])},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_BYPASS_OFF_ENTITIES,
                    description={"suggested_value": defaults.get(CONF_BYPASS_OFF_ENTITIES, [])},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(multiple=True)),
            }
        )
        safeguard_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SETTLING_COOLDOWN_SEC,
                    default=defaults.get(CONF_SETTLING_COOLDOWN_SEC, DEFAULT_SETTLING_COOLDOWN_SEC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=180, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_POWER_GRID_ENTITY,
                    description={"suggested_value": default_grid},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])),
            }
        )
    else:
        override_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OVERRIDE_TIMEOUT_MIN,
                    default=defaults.get(CONF_OVERRIDE_TIMEOUT_MIN, DEFAULT_OVERRIDE_TIMEOUT_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=240, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE,
                    default=defaults.get(
                        CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE, DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_CREATE_OVERRIDE_SWITCH,
                    default=defaults.get(CONF_CREATE_OVERRIDE_SWITCH, False),
                ): selector.BooleanSelector(),
                vol.Optional(CONF_MANUAL_OVERRIDE_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain=["input_boolean", "switch"])
                ),
            }
        )
        bypass_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CREATE_FREEZE_SWITCH,
                    default=defaults.get(CONF_CREATE_FREEZE_SWITCH, False),
                ): selector.BooleanSelector(),
                vol.Optional(CONF_BYPASS_FREEZE_ENTITIES, default=[]): OptionalEntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_BYPASS_OFF_ENTITIES, default=[]): OptionalEntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        safeguard_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SETTLING_COOLDOWN_SEC,
                    default=defaults.get(CONF_SETTLING_COOLDOWN_SEC, DEFAULT_SETTLING_COOLDOWN_SEC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=180, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_POWER_GRID_ENTITY, description={"suggested_value": default_grid}): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
            }
        )

    return vol.Schema(
        {
            vol.Required(SECTION_OVERRIDE_BEHAVIOR): data_entry_flow.section(
                override_schema, {"collapsed": False}
            ),
            vol.Required(SECTION_BYPASS_ENTITIES): data_entry_flow.section(
                bypass_schema, {"collapsed": True}
            ),
            vol.Required(SECTION_HARDWARE_SAFEGUARDS): data_entry_flow.section(
                safeguard_schema, {"collapsed": True}
            ),
        }
    )


def _build_simulation_lights_summary(hass: Optional[HomeAssistant], target_label: str) -> str:
    """Build a markdown summary listing lights tagged with target_label."""
    matching_lights: List[str] = []
    if hass:
        reg = er.async_get(hass)
        matching_lights = [
            entry.entity_id
            for entry in reg.entities.values()
            if entry.domain == "light" and not entry.disabled and target_label in entry.labels
        ]
        matching_lights.sort()

    if matching_lights:
        lights_list = "\n".join(f"- `{entity_id}`" for entity_id in matching_lights)
        return (
            f"**Currently Included Lights ({len(matching_lights)}) with label `{target_label}`:**\n"
            f"{lights_list}"
        )
    return (
        f"ℹ️ **No lights currently tagged with label `{target_label}`.**\n\n"
        f"You can tag lights in Home Assistant at any time "
        f"(Settings → Devices & Services → Entities → select light → Labels)."
    )


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


_HOLIDAY_MODE_LABELS: Dict[str, str] = {
    LIGHT_MODE_DEFAULT: "Use Holiday Default",
    LIGHT_MODE_HUE_SCENE: "Philips Hue Dynamic Scene",
    LIGHT_MODE_EFFECT: "Bulb / WLED Firmware Effect (fire, candle, chases)",
    LIGHT_MODE_WLED_PRESET: "WLED / Soffit Preset or Playlist (Lumary 3 WLED)",
    LIGHT_MODE_HA_SCENE: "Home Assistant Scene / Tuya Tap-to-Run / Script",
    LIGHT_MODE_RGB: "Solid RGB Color",
    LIGHT_MODE_COLOR_TEMP: "Warm / Cool White (Kelvin)",
    LIGHT_MODE_OFF: "Keep Light OFF for This Holiday",
}


def _holiday_mode_options() -> List[selector.SelectOptionDict]:
    """Return SelectSelector options for holiday-level lighting modes."""
    return [
        selector.SelectOptionDict(value=m, label=_HOLIDAY_MODE_LABELS[m])
        for m in (
            LIGHT_MODE_HUE_SCENE,
            LIGHT_MODE_EFFECT,
            LIGHT_MODE_WLED_PRESET,
            LIGHT_MODE_HA_SCENE,
            LIGHT_MODE_RGB,
            LIGHT_MODE_COLOR_TEMP,
        )
    ]


def _per_light_mode_options() -> List[selector.SelectOptionDict]:
    """Return SelectSelector options for per-light holiday customization."""
    return [
        selector.SelectOptionDict(value=m, label=_HOLIDAY_MODE_LABELS[m])
        for m in (
            LIGHT_MODE_DEFAULT,
            LIGHT_MODE_RGB,
            LIGHT_MODE_COLOR_TEMP,
            LIGHT_MODE_HUE_SCENE,
            LIGHT_MODE_EFFECT,
            LIGHT_MODE_WLED_PRESET,
            LIGHT_MODE_HA_SCENE,
            LIGHT_MODE_OFF,
        )
    ]


def _discover_select_options(
    hass: Optional[HomeAssistant],
    option_kind: str,
    target_light_id: Optional[str] = None,
    current_value: str = "",
) -> List[selector.SelectOptionDict]:
    """Collect WLED/Tuya preset or palette options from companion select entities."""
    seen: Dict[str, str] = {}
    if hass:
        if target_light_id:
            comp = discover_light_companions(hass, target_light_id)
            raw_list = comp.get("presets" if option_kind == "preset" else "palettes", [])
            for item in raw_list:
                seen[item] = item
        elif hasattr(hass, "states"):
            keywords = ("preset", "playlist", "scene") if option_kind == "preset" else ("palette",)
            for st in hass.states.async_all("select"):
                eid_low = st.entity_id.lower()
                if any(kw in eid_low for kw in keywords):
                    for opt in st.attributes.get("options") or []:
                        if opt and isinstance(opt, str) and opt.strip():
                            seen[opt.strip()] = opt.strip()

    if current_value and current_value.strip() and current_value.strip() not in seen:
        seen[current_value.strip()] = current_value.strip()

    opts = [selector.SelectOptionDict(value="", label="None / Select or Type...")]
    for val in sorted(seen.keys(), key=lambda x: x.lower()):
        opts.append(selector.SelectOptionDict(value=val, label=val))
    return opts


def _build_lighting_mode_fields(
    hass: Optional[HomeAssistant],
    mode: str,
    defaults: Mapping[str, Any],
    target_light_id: Optional[str] = None,
) -> Dict[Any, Any]:
    """Build dynamic schema fields matching the selected holiday or per-light mode."""
    kelvin_unit = getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin")
    curr_effect = str(defaults.get("effect") or "")
    curr_fallback = str(defaults.get("fallback_effect") or "")
    companions = discover_light_companions(hass, target_light_id) if (hass and target_light_id) else {}

    if target_light_id and companions.get("effects"):
        effect_opts = [selector.SelectOptionDict(value="", label="None / No Effect")]
        seen_effs = set()
        for eff in companions["effects"]:
            if eff not in seen_effs:
                effect_opts.append(selector.SelectOptionDict(value=eff, label=eff))
                seen_effs.add(eff)
        for opt in get_available_bulb_effects(hass, [curr_effect, curr_fallback]):
            if opt["value"] and opt["value"] not in seen_effs:
                effect_opts.append(opt)
                seen_effs.add(opt["value"])
    else:
        effect_opts = get_available_bulb_effects(hass, [curr_effect, curr_fallback])

    fields: Dict[Any, Any] = {}
    if mode == LIGHT_MODE_HUE_SCENE:
        fields[
            vol.Optional("hue_scene", default=defaults.get("hue_scene", ""))
        ] = OptionalEntitySelector(selector.EntitySelectorConfig(domain="scene"))
        fields[
            vol.Optional("dynamic_scene", default=defaults.get("dynamic_scene", True))
        ] = selector.BooleanSelector()
        fields[
            vol.Optional("fallback_effect", default=curr_fallback)
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=effect_opts, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        fields[
            vol.Optional("rgb_color", default=defaults.get("rgb_color", [255, 140, 0]))
        ] = selector.ColorRGBSelector()
    elif mode == LIGHT_MODE_HA_SCENE:
        fields[
            vol.Optional("ha_scene", default=defaults.get("ha_scene", ""))
        ] = OptionalEntitySelector(selector.EntitySelectorConfig(domain=["scene", "script"]))
        fields[
            vol.Optional("rgb_color", default=defaults.get("rgb_color", [255, 140, 0]))
        ] = selector.ColorRGBSelector()
    elif mode == LIGHT_MODE_WLED_PRESET:
        default_preset_ent = str(
            defaults.get("wled_preset_entity")
            or companions.get("preset_select")
            or companions.get("playlist_select")
            or companions.get("scene_select")
            or ""
        )
        curr_preset = str(defaults.get("wled_preset") or "")
        preset_opts = _discover_select_options(hass, "preset", target_light_id, curr_preset)
        fields[
            vol.Optional("wled_preset_entity", description={"suggested_value": default_preset_ent})
        ] = OptionalEntitySelector(selector.EntitySelectorConfig(domain="select"))
        fields[
            vol.Optional("wled_preset", default=curr_preset)
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=preset_opts, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
    elif mode == LIGHT_MODE_EFFECT:
        curr_palette = str(defaults.get("wled_palette") or "")
        default_pal_ent = str(
            defaults.get("wled_palette_entity") or companions.get("palette_select") or ""
        )
        palette_opts = _discover_select_options(hass, "palette", target_light_id, curr_palette)
        fields[vol.Optional("effect", default=curr_effect)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=effect_opts, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        fields[vol.Optional("wled_palette_entity", description={"suggested_value": default_pal_ent})] = (
            OptionalEntitySelector(selector.EntitySelectorConfig(domain="select"))
        )
        fields[vol.Optional("wled_palette", default=curr_palette)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=palette_opts, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        fields[vol.Optional("fallback_effect", default=curr_fallback)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=effect_opts, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        fields[
            vol.Optional("rgb_color", default=defaults.get("rgb_color", [255, 140, 0]))
        ] = selector.ColorRGBSelector()
    elif mode == LIGHT_MODE_COLOR_TEMP:
        fields[
            vol.Required("color_temp_kelvin", default=defaults.get("color_temp_kelvin", 2200))
        ] = selector.ColorTempSelector(
            selector.ColorTempSelectorConfig(min=2000, max=6500, unit=kelvin_unit)
        )
    else:
        fields[
            vol.Required("rgb_color", default=defaults.get("rgb_color", [255, 140, 0]))
        ] = selector.ColorRGBSelector()

    fields[
        vol.Required("brightness_pct", default=defaults.get("brightness_pct", 100))
    ] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
    )
    return fields


def _validate_lighting_mode_fields(mode: str, user_input: Mapping[str, Any]) -> Dict[str, str]:
    """Validate required fields for a holiday or per-light lighting mode."""
    errors: Dict[str, str] = {}
    if mode == LIGHT_MODE_HUE_SCENE and not str(user_input.get("hue_scene") or "").strip():
        errors["hue_scene"] = "missing_hue_scene"
    elif mode == LIGHT_MODE_HA_SCENE and not str(user_input.get("ha_scene") or "").strip():
        errors["ha_scene"] = "missing_ha_scene"
    elif mode == LIGHT_MODE_WLED_PRESET and not str(user_input.get("wled_preset") or "").strip():
        errors["wled_preset"] = "missing_wled_preset"
    elif mode == LIGHT_MODE_EFFECT and not str(user_input.get("effect") or "").strip():
        errors["effect"] = "missing_bulb_effect"
    return errors


def _format_override_summary(cfg: Optional[Mapping[str, Any]]) -> str:
    """Format a compact human-readable label describing a per-light holiday override."""
    if not cfg or cfg.get("light_mode", LIGHT_MODE_DEFAULT) == LIGHT_MODE_DEFAULT:
        return "Holiday Default"
    m = str(cfg.get("light_mode"))
    pct = cfg.get("brightness_pct", 100)
    if m == LIGHT_MODE_OFF:
        return "Keep OFF"
    if m == LIGHT_MODE_HUE_SCENE:
        return f"Hue Scene `{cfg.get('hue_scene', '')}` ({pct}%)"
    if m == LIGHT_MODE_HA_SCENE:
        return f"Scene/Script `{cfg.get('ha_scene', '')}`"
    if m == LIGHT_MODE_WLED_PRESET:
        return f"WLED Preset `{cfg.get('wled_preset', '')}` ({pct}%)"
    if m == LIGHT_MODE_EFFECT:
        pal = f", palette `{cfg['wled_palette']}`" if cfg.get("wled_palette") else ""
        return f"Effect `{cfg.get('effect', '')}`{pal} ({pct}%)"
    if m == LIGHT_MODE_COLOR_TEMP:
        return f"{cfg.get('color_temp_kelvin', 2200)}K White ({pct}%)"
    rgb = cfg.get("rgb_color", [255, 140, 0])
    return f"RGB {rgb} ({pct}%)"


class PassableSmartLightingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Passable Adaptive Smart Lighting Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._room_draft: Dict[str, Any] = {}
        self._pending_steps: List[str] = []
        self._sim_draft: Dict[str, Any] = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Choose between setting up a room, presence simulation, or holiday lighting."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["room", "presence_simulation", "holiday_lighting"],
        )

    async def async_step_room(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Handle Step 1: Core room hardware, sensors, and lux targets."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            flat = _unpack_sections(user_input)
            room_name = str(flat.get(CONF_ROOM_NAME) or "").strip()
            custom_id = str(flat.get(CONF_ROOM_ID) or "").strip()
            room_id = _slugify_room_id(custom_id or room_name)

            if not room_id:
                errors[CONF_ROOM_NAME] = "invalid_room_id"
            else:
                await self.async_set_unique_id(room_id)
                self._abort_if_unique_id_configured()

                self._room_draft = {
                    **flat,
                    CONF_ROOM_ID: room_id,
                    CONF_ROOM_NAME: room_name or room_id.replace("_", " ").title(),
                }
                return await self.async_step_room_features()

        step1_schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
                vol.Required(CONF_LIGHT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Required(CONF_PRESENCE_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"], multiple=True)
                ),
                vol.Required(CONF_LUX_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
                ),
                vol.Required(CONF_TARGET_LUX, default=DEFAULT_TARGET_LUX): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1000, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_PRESENCE_TIMEOUT_MIN, default=DEFAULT_PRESENCE_TIMEOUT_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=120, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(SECTION_AUXILIARY_TUNING): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_ROOM_ID, default=""): selector.TextSelector(),
                            vol.Optional(
                                CONF_SECONDARY_LIGHTS, default=DEFAULT_SECONDARY_LIGHTS
                            ): OptionalEntitySelector(
                                selector.EntitySelectorConfig(domain="light", multiple=True)
                            ),
                            vol.Optional(
                                CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
                                default=DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
                            ): selector.BooleanSelector(),
                            vol.Optional(
                                CONF_TIMEOUT_SCALE_ENTITIES, default=DEFAULT_TIMEOUT_SCALE_ENTITIES
                            ): OptionalEntitySelector(selector.EntitySelectorConfig(multiple=True)),
                            vol.Optional(
                                CONF_TIMEOUT_SCALE_FACTOR, default=DEFAULT_TIMEOUT_SCALE_FACTOR
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=1.0, max=10.0, step=0.5, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(
                                CONF_MIN_OCCUPIED_PCT, default=DEFAULT_MIN_OCCUPIED_PCT
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                            vol.Optional(
                                CONF_DEFAULT_LUX_RATIO, default=DEFAULT_LUX_RATIO
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0.01, max=20.0, step=0.05, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(step_id="room", data_schema=step1_schema, errors=errors)

    async def async_step_advanced(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Backward-compatible alias to room feature selection step."""
        return await self.async_step_room_features(user_input)

    async def async_step_room_features(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Handle Step 2: Enable optional room features and choose trigger modes."""
        if user_input is not None:
            min_ct = int(user_input.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP))
            max_ct = int(user_input.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP))
            if min_ct > max_ct:
                min_ct, max_ct = max_ct, min_ct

            media_entities = user_input.get(CONF_MEDIA_ENTITIES) or []
            late_night_enabled = bool(user_input.get(CONF_LATE_NIGHT_ENABLED, False))
            configure_bypasses = bool(user_input.get("configure_bypasses", False))
            notification_enabled = bool(user_input.get(CONF_NOTIFICATION_LIGHT_ENABLED, False))

            self._room_draft.update(
                {
                    CONF_CIRCADIAN_ENABLED: bool(user_input.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED)),
                    CONF_MIN_COLOR_TEMP: min_ct,
                    CONF_MAX_COLOR_TEMP: max_ct,
                    CONF_LATE_NIGHT_ENABLED: late_night_enabled,
                    CONF_LATE_NIGHT_CONDITION_TYPE: user_input.get(
                        CONF_LATE_NIGHT_CONDITION_TYPE, DEFAULT_LATE_NIGHT_CONDITION_TYPE
                    ),
                    CONF_MEDIA_ENTITIES: media_entities,
                    CONF_NOTIFICATION_LIGHT_ENABLED: notification_enabled,
                }
            )

            self._pending_steps = []
            if late_night_enabled:
                self._pending_steps.append("room_late_night")
            if media_entities:
                self._pending_steps.append("room_media")
            if configure_bypasses:
                self._pending_steps.append("room_bypasses")
            if notification_enabled:
                self._pending_steps.append("room_notification")

            return await self._async_advance_room_wizard()

        kelvin_unit = getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin")
        schema = vol.Schema(
            {
                vol.Required(CONF_CIRCADIAN_ENABLED, default=DEFAULT_CIRCADIAN_ENABLED): selector.BooleanSelector(),
                vol.Optional(CONF_MIN_COLOR_TEMP, default=DEFAULT_MIN_COLOR_TEMP): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(min=2000, max=4000, unit=kelvin_unit)
                ),
                vol.Optional(CONF_MAX_COLOR_TEMP, default=DEFAULT_MAX_COLOR_TEMP): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(min=4000, max=6500, unit=kelvin_unit)
                ),
                vol.Required(CONF_LATE_NIGHT_ENABLED, default=DEFAULT_LATE_NIGHT_ENABLED): selector.BooleanSelector(),
                vol.Required(
                    CONF_LATE_NIGHT_CONDITION_TYPE, default=DEFAULT_LATE_NIGHT_CONDITION_TYPE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_late_night_mode_options())
                ),
                vol.Optional(CONF_MEDIA_ENTITIES, default=[]): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=True)
                ),
                vol.Optional("configure_bypasses", default=False): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFICATION_LIGHT_ENABLED, default=DEFAULT_NOTIFICATION_LIGHT_ENABLED
                ): selector.BooleanSelector(),
            }
        )
        room_name = self._room_draft.get(CONF_ROOM_NAME) or self._room_draft.get(CONF_ROOM_ID, "Room")
        return self.async_show_form(
            step_id="room_features",
            data_schema=schema,
            description_placeholders={"room_name": room_name},
        )

    async def _async_advance_room_wizard(self) -> config_entries.ConfigFlowResult:
        """Route to the next enabled setup step or finalize room creation."""
        if self._pending_steps:
            next_step = self._pending_steps.pop(0)
            if next_step == "room_late_night":
                return await self.async_step_room_late_night()
            if next_step == "room_media":
                return await self.async_step_room_media()
            if next_step == "room_bypasses":
                return await self.async_step_room_bypasses()
            if next_step == "room_notification":
                return await self.async_step_room_notification()

        room_id = self._room_draft[CONF_ROOM_ID]
        room_title = str(self._room_draft.get(CONF_ROOM_NAME) or "").strip() or room_id.replace("_", " ").title()
        return self.async_create_entry(title=f"Smart Lighting - {room_title}", data=self._room_draft)

    async def async_step_room_late_night(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure Late Night brightness and only the fields for the chosen trigger mode."""
        cond_type = normalize_late_night_mode(self._room_draft)
        errors: Dict[str, str] = {}

        if user_input is not None:
            errors = _validate_late_night_details(cond_type, user_input)
            if not errors:
                self._room_draft.update(user_input)
                return await self._async_advance_room_wizard()

        base_schema = vol.Schema(
            {
                vol.Required(
                    CONF_LATE_NIGHT_PCT,
                    default=self._room_draft.get(CONF_LATE_NIGHT_PCT, DEFAULT_LATE_NIGHT_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_LATE_NIGHT_LEARN_PREFS,
                    default=self._room_draft.get(CONF_LATE_NIGHT_LEARN_PREFS, DEFAULT_LATE_NIGHT_LEARN_PREFS),
                ): selector.BooleanSelector(),
            }
        )
        details_schema = _build_late_night_details_schema(cond_type, self._room_draft, is_options=False)
        full_schema = vol.Schema({**base_schema.schema, **details_schema.schema})

        return self.async_show_form(
            step_id="room_late_night",
            data_schema=full_schema,
            errors=errors,
            description_placeholders={"mode_label": _late_night_mode_label(cond_type)},
        )

    async def async_step_room_media(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure Media Player dimming settings."""
        if user_input is not None:
            self._room_draft.update(user_input)
            return await self._async_advance_room_wizard()

        schema = vol.Schema(
            {
                vol.Required(CONF_MEDIA_SEED_PCT, default=DEFAULT_MEDIA_SEED_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_MEDIA_RESPECT_AMBIENT_LUX, default=DEFAULT_MEDIA_RESPECT_AMBIENT_LUX
                ): selector.BooleanSelector(),
                vol.Optional(CONF_MEDIA_LEARN_PREFS, default=DEFAULT_MEDIA_LEARN_PREFS): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="room_media", data_schema=schema)

    async def async_step_room_bypasses(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure manual overrides, bypasses, and hardware safeguards."""
        if user_input is not None:
            self._room_draft.update(_unpack_sections(user_input))
            return await self._async_advance_room_wizard()

        schema = _build_bypasses_sections_schema(self.hass, self._room_draft, is_options=False)
        return self.async_show_form(step_id="room_bypasses", data_schema=schema)

    async def async_step_room_notification(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure Visual Notification Light bulb and trigger."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_NOTIFICATION_TRIGGER_ENTITY):
                errors[CONF_NOTIFICATION_TRIGGER_ENTITY] = "missing_notification_trigger"
            if not user_input.get(CONF_NOTIFICATION_LIGHT_ENTITY):
                errors[CONF_NOTIFICATION_LIGHT_ENTITY] = "missing_notification_light"
            if not errors:
                self._room_draft.update(user_input)
                return await self._async_advance_room_wizard()

        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFICATION_TRIGGER_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain=["input_boolean", "binary_sensor", "switch", "sensor"])
                ),
                vol.Optional(CONF_NOTIFICATION_LIGHT_ENTITY): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Required(CONF_NOTIFICATION_COLOR, default=DEFAULT_NOTIFICATION_COLOR): selector.ColorRGBSelector(),
                vol.Required(
                    CONF_NOTIFICATION_BRIGHTNESS_PCT, default=DEFAULT_NOTIFICATION_BRIGHTNESS_PCT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_NOTIFICATION_PRESENCE_GATED, default=DEFAULT_NOTIFICATION_PRESENCE_GATED
                ): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFICATION_SUPPRESSION_ENTITIES, default=[]): OptionalEntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="room_notification", data_schema=schema, errors=errors)

    async def async_step_import(self, import_data: Dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Auto-create unified system or legacy subsystem config entry from import."""
        entry_type = import_data.get("entry_type")
        if entry_type == "system":
            await self.async_set_unique_id(f"{DOMAIN}_system")
            self._abort_if_unique_id_configured()
            defaults = {
                CONF_SIMULATION_ENABLED: DEFAULT_SIMULATION_ENABLED,
                CONF_SIMULATION_LABEL: DEFAULT_SIMULATION_LABEL,
                CONF_SIMULATION_MODE: DEFAULT_SIMULATION_MODE,
                CONF_SIMULATION_LOOKBACK_DAYS: DEFAULT_SIMULATION_LOOKBACK_DAYS,
                CONF_SIMULATION_JITTER_MIN: DEFAULT_SIMULATION_JITTER_MIN,
                CONF_SIMULATION_ARRIVAL_GRACE_MIN: DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
                CONF_SIMULATION_MAX_BRIGHTNESS_PCT: DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
            }
            merged_sim = {**defaults, **{k: v for k, v in import_data.items() if k != "entry_type"}}
            return self.async_create_entry(
                title="Passable Smart Light Engine",
                data={"entry_type": "system", **merged_sim},
            )
        if entry_type == "presence_simulation":
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

    async def async_step_holiday_lighting(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure or initialize holiday lighting subsystem."""
        await self.async_set_unique_id(f"{DOMAIN}_holiday_lighting")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Holiday & Exterior Lighting",
            data={"entry_type": "holiday_lighting"},
        )

    async def async_step_presence_simulation(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure presence simulation Step 1: enablement, label, and strategy."""
        await self.async_set_unique_id(f"{DOMAIN}_presence_simulation")
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._sim_draft = dict(user_input)
            return await self.async_step_presence_simulation_tuning()

        target_label = DEFAULT_SIMULATION_LABEL
        summary_text = _build_simulation_lights_summary(self.hass, target_label)

        schema = vol.Schema(
            {
                vol.Required(CONF_SIMULATION_ENABLED, default=DEFAULT_SIMULATION_ENABLED): selector.BooleanSelector(),
                vol.Required(CONF_SIMULATION_LABEL, default=target_label): selector.TextSelector(),
                vol.Required(CONF_SIMULATION_MODE, default=DEFAULT_SIMULATION_MODE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="hybrid",
                                label="Hybrid (Smart History Replay with Synthetic Fallback)",
                            ),
                            selector.SelectOptionDict(
                                value="history_replay",
                                label="Smart History Replay Only",
                            ),
                            selector.SelectOptionDict(
                                value="synthetic_routine",
                                label="Synthetic Realistic Evening Routine Only",
                            ),
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="presence_simulation",
            data_schema=schema,
            description_placeholders={"lights_summary": summary_text},
        )

    async def async_step_presence_simulation_tuning(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Configure presence simulation Step 2: timing, lookback (when applicable), and brightness."""
        if user_input is not None:
            data = {"entry_type": "presence_simulation", **self._sim_draft, **user_input}
            return self.async_create_entry(title="Presence Simulation", data=data)

        target_label = str(self._sim_draft.get(CONF_SIMULATION_LABEL, DEFAULT_SIMULATION_LABEL)).strip() or DEFAULT_SIMULATION_LABEL
        sim_mode = str(self._sim_draft.get(CONF_SIMULATION_MODE, DEFAULT_SIMULATION_MODE))
        summary_text = _build_simulation_lights_summary(self.hass, target_label)

        fields: Dict[Any, Any] = {}
        if sim_mode in ("hybrid", "history_replay"):
            fields[vol.Required(CONF_SIMULATION_LOOKBACK_DAYS, default=DEFAULT_SIMULATION_LOOKBACK_DAYS)] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
                )
            )
        fields[vol.Required(CONF_SIMULATION_JITTER_MIN, default=DEFAULT_SIMULATION_JITTER_MIN)] = (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=60, step=5, mode=selector.NumberSelectorMode.BOX)
            )
        )
        fields[vol.Required(CONF_SIMULATION_ARRIVAL_GRACE_MIN, default=DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN)] = (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
            )
        )
        fields[vol.Required(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, default=DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT)] = (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
            )
        )

        return self.async_show_form(
            step_id="presence_simulation_tuning",
            data_schema=vol.Schema(fields),
            description_placeholders={"lights_summary": summary_text},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create options flow handler for modifying an existing room."""
        return PassableSmartLightingOptionsFlow(config_entry)


class PassableSmartLightingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for modifying a room, system settings, presence simulation, or holidays."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry
        self._pending_late_night: Dict[str, Any] = {}
        self._pending_sim: Dict[str, Any] = {}
        self._pending_exterior: Dict[str, Any] = {}
        self._pending_decorations: Dict[str, Any] = {}
        self._pending_holiday: Dict[str, Any] = {}
        self._pending_holiday_mode_data: Dict[str, Any] = {}
        self._pending_light_overrides: Dict[str, Dict[str, Any]] = {}
        self._editing_holiday_light_id: Optional[str] = None
        self._editing_holiday_light_mode: str = LIGHT_MODE_DEFAULT
        self._selected_holiday_id: str = "__add_new__"

    async def _async_save_room_data(self, updates: Dict[str, Any], new_title: Optional[str] = None) -> config_entries.ConfigFlowResult:
        """Persist updated room configuration to config entry."""
        new_data = {**self._entry.data, **updates}
        update_kwargs: Dict[str, Any] = {"data": new_data}
        if new_title:
            update_kwargs["title"] = new_title
        self.hass.config_entries.async_update_entry(self._entry, **update_kwargs)
        return self.async_create_entry(title="", data={})

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Manage room, system, presence simulation, or holiday lighting options."""
        entry_type = self._entry.data.get("entry_type")
        if entry_type == "system":
            return await self.async_step_system_menu()
        if entry_type == "presence_simulation":
            return await self.async_step_presence_simulation_options(user_input)
        if entry_type == "holiday_lighting":
            return await self.async_step_holiday_menu()
        return await self.async_step_room_menu()

    async def async_step_room_menu(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Categorized options menu for an existing room controller."""
        d = self._entry.data
        room_id = d.get(CONF_ROOM_ID, "room")
        room_name = str(d.get(CONF_ROOM_NAME) or "").strip() or room_id.replace("_", " ").title()
        ln_enabled = bool(d.get(CONF_LATE_NIGHT_ENABLED, DEFAULT_LATE_NIGHT_ENABLED))
        ln_mode = _late_night_mode_label(normalize_late_night_mode(d))
        media_list = d.get(CONF_MEDIA_ENTITIES) or []
        notif_enabled = bool(d.get(CONF_NOTIFICATION_LIGHT_ENABLED, DEFAULT_NOTIFICATION_LIGHT_ENABLED))

        room_summary = (
            f"**{room_name}** (`{room_id}`)\n"
            f"- **Primary Light:** `{d.get(CONF_LIGHT_ENTITY, 'unset')}` • **Target Lux:** `{d.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX)} lx`\n"
            f"- **Circadian:** {'Enabled' if d.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED) else 'Disabled'} • "
            f"**Late Night:** {f'Enabled ({ln_mode})' if ln_enabled else 'Disabled'}\n"
            f"- **Media Players:** {len(media_list)} • **Visual Notification:** {'Enabled' if notif_enabled else 'Disabled'}"
        )

        return self.async_show_menu(
            step_id="room_menu",
            menu_options=[
                "room_opt_hardware",
                "room_opt_circadian",
                "room_opt_late_night",
                "room_opt_media",
                "room_opt_bypasses",
                "room_opt_notification",
            ],
            description_placeholders={"room_summary": room_summary},
        )

    async def async_step_room_opt_hardware(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Edit room name, hardware entities, presence sensors, and lux/timeout targets."""
        d = self._entry.data
        room_id = d.get(CONF_ROOM_ID, "room")
        current_name = str(d.get(CONF_ROOM_NAME) or "").strip() or room_id.replace("_", " ").title()

        if user_input is not None:
            flat = _unpack_sections(user_input)
            new_name = str(flat.get(CONF_ROOM_NAME) or "").strip() or current_name
            flat[CONF_ROOM_NAME] = new_name
            return await self._async_save_room_data(flat, new_title=f"Smart Lighting - {new_name}")

        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME, default=current_name): selector.TextSelector(),
                vol.Required(CONF_LIGHT_ENTITY, default=d.get(CONF_LIGHT_ENTITY)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Required(
                    CONF_PRESENCE_ENTITIES, default=d.get(CONF_PRESENCE_ENTITIES, [])
                ): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"], multiple=True)
                ),
                vol.Required(CONF_LUX_SENSOR, default=d.get(CONF_LUX_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")
                ),
                vol.Required(
                    CONF_TARGET_LUX, default=d.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1000, step=5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_PRESENCE_TIMEOUT_MIN,
                    default=d.get(CONF_PRESENCE_TIMEOUT_MIN, DEFAULT_PRESENCE_TIMEOUT_MIN),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=120, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(SECTION_AUXILIARY_TUNING): data_entry_flow.section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_SECONDARY_LIGHTS,
                                description={"suggested_value": d.get(CONF_SECONDARY_LIGHTS, DEFAULT_SECONDARY_LIGHTS)},
                            ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                            vol.Optional(
                                CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
                                default=d.get(
                                    CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
                                    DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON,
                                ),
                            ): selector.BooleanSelector(),
                            vol.Optional(
                                CONF_TIMEOUT_SCALE_ENTITIES,
                                description={"suggested_value": d.get(CONF_TIMEOUT_SCALE_ENTITIES, DEFAULT_TIMEOUT_SCALE_ENTITIES)},
                            ): OptionalEntitySelector(selector.EntitySelectorConfig(multiple=True)),
                            vol.Optional(
                                CONF_TIMEOUT_SCALE_FACTOR,
                                default=d.get(CONF_TIMEOUT_SCALE_FACTOR, DEFAULT_TIMEOUT_SCALE_FACTOR),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=1.0, max=10.0, step=0.5, mode=selector.NumberSelectorMode.BOX)
                            ),
                            vol.Optional(
                                CONF_MIN_OCCUPIED_PCT,
                                default=d.get(CONF_MIN_OCCUPIED_PCT, DEFAULT_MIN_OCCUPIED_PCT),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                            ),
                            vol.Optional(
                                CONF_DEFAULT_LUX_RATIO,
                                default=d.get(CONF_DEFAULT_LUX_RATIO, DEFAULT_LUX_RATIO),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=0.01, max=20.0, step=0.05, mode=selector.NumberSelectorMode.BOX)
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )
        return self.async_show_form(step_id="room_opt_hardware", data_schema=schema)

    async def async_step_room_opt_circadian(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Edit circadian rhythm settings for this room."""
        d = self._entry.data
        if user_input is not None:
            min_ct = int(user_input.get(CONF_MIN_COLOR_TEMP, d.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP)))
            max_ct = int(user_input.get(CONF_MAX_COLOR_TEMP, d.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP)))
            if min_ct > max_ct:
                min_ct, max_ct = max_ct, min_ct
            return await self._async_save_room_data(
                {
                    CONF_CIRCADIAN_ENABLED: bool(user_input.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED)),
                    CONF_MIN_COLOR_TEMP: min_ct,
                    CONF_MAX_COLOR_TEMP: max_ct,
                }
            )

        kelvin_unit = getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin")
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CIRCADIAN_ENABLED,
                    default=d.get(CONF_CIRCADIAN_ENABLED, DEFAULT_CIRCADIAN_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_MIN_COLOR_TEMP,
                    default=d.get(CONF_MIN_COLOR_TEMP, DEFAULT_MIN_COLOR_TEMP),
                ): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(min=2000, max=4000, unit=kelvin_unit)
                ),
                vol.Optional(
                    CONF_MAX_COLOR_TEMP,
                    default=d.get(CONF_MAX_COLOR_TEMP, DEFAULT_MAX_COLOR_TEMP),
                ): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(min=4000, max=6500, unit=kelvin_unit)
                ),
            }
        )
        return self.async_show_form(step_id="room_opt_circadian", data_schema=schema)

    async def async_step_room_opt_late_night(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Late Night Step 1: toggle, target brightness, learning, and trigger mode."""
        d = self._entry.data
        if user_input is not None:
            self._pending_late_night = dict(user_input)
            if not bool(user_input.get(CONF_LATE_NIGHT_ENABLED, False)):
                return await self._async_save_room_data(self._pending_late_night)
            return await self.async_step_room_opt_late_night_details()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LATE_NIGHT_ENABLED,
                    default=d.get(CONF_LATE_NIGHT_ENABLED, DEFAULT_LATE_NIGHT_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_LATE_NIGHT_PCT,
                    default=d.get(CONF_LATE_NIGHT_PCT, DEFAULT_LATE_NIGHT_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_LATE_NIGHT_LEARN_PREFS,
                    default=d.get(CONF_LATE_NIGHT_LEARN_PREFS, DEFAULT_LATE_NIGHT_LEARN_PREFS),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_LATE_NIGHT_CONDITION_TYPE,
                    default=normalize_late_night_mode(d),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_late_night_mode_options())
                ),
            }
        )
        return self.async_show_form(step_id="room_opt_late_night", data_schema=schema)

    async def async_step_room_opt_late_night_details(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Late Night Step 2: show only the trigger fields matching the chosen mode."""
        d = self._entry.data
        cond_type = normalize_late_night_mode({**d, **self._pending_late_night})
        errors: Dict[str, str] = {}

        if user_input is not None:
            errors = _validate_late_night_details(cond_type, user_input)
            if not errors:
                return await self._async_save_room_data({**self._pending_late_night, **user_input})

        schema = _build_late_night_details_schema(cond_type, d, is_options=True)
        return self.async_show_form(
            step_id="room_opt_late_night_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"mode_label": _late_night_mode_label(cond_type)},
        )

    async def async_step_room_opt_media(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Edit media player dimming settings."""
        d = self._entry.data
        if user_input is not None:
            return await self._async_save_room_data(user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MEDIA_ENTITIES,
                    description={"suggested_value": d.get(CONF_MEDIA_ENTITIES, [])},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="media_player", multiple=True)),
                vol.Required(
                    CONF_MEDIA_SEED_PCT,
                    default=d.get(CONF_MEDIA_SEED_PCT, DEFAULT_MEDIA_SEED_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_MEDIA_RESPECT_AMBIENT_LUX,
                    default=d.get(CONF_MEDIA_RESPECT_AMBIENT_LUX, DEFAULT_MEDIA_RESPECT_AMBIENT_LUX),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_MEDIA_LEARN_PREFS,
                    default=d.get(CONF_MEDIA_LEARN_PREFS, DEFAULT_MEDIA_LEARN_PREFS),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="room_opt_media", data_schema=schema)

    async def async_step_room_opt_bypasses(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Edit manual overrides, freeze/off bypasses, and sensor safeguards."""
        d = self._entry.data
        if user_input is not None:
            return await self._async_save_room_data(_unpack_sections(user_input))

        schema = _build_bypasses_sections_schema(self.hass, d, is_options=True)
        return self.async_show_form(step_id="room_opt_bypasses", data_schema=schema)

    async def async_step_room_opt_notification(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Visual Notification Light Step 1: enable/disable toggle."""
        d = self._entry.data
        if user_input is not None:
            enabled = bool(user_input.get(CONF_NOTIFICATION_LIGHT_ENABLED, False))
            if not enabled:
                return await self._async_save_room_data({CONF_NOTIFICATION_LIGHT_ENABLED: False})
            return await self.async_step_room_opt_notification_details()

        trig = d.get(CONF_NOTIFICATION_TRIGGER_ENTITY) or "not set"
        bulb = d.get(CONF_NOTIFICATION_LIGHT_ENTITY) or "not set"
        notif_summary = f"Current Trigger: `{trig}` • Current Bulb: `{bulb}`"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFICATION_LIGHT_ENABLED,
                    default=d.get(CONF_NOTIFICATION_LIGHT_ENABLED, DEFAULT_NOTIFICATION_LIGHT_ENABLED),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="room_opt_notification",
            data_schema=schema,
            description_placeholders={"notif_summary": notif_summary},
        )

    async def async_step_room_opt_notification_details(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Visual Notification Light Step 2: trigger, bulb, color, and suppression settings."""
        d = self._entry.data
        errors: Dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_NOTIFICATION_TRIGGER_ENTITY):
                errors[CONF_NOTIFICATION_TRIGGER_ENTITY] = "missing_notification_trigger"
            if not user_input.get(CONF_NOTIFICATION_LIGHT_ENTITY):
                errors[CONF_NOTIFICATION_LIGHT_ENTITY] = "missing_notification_light"
            if not errors:
                return await self._async_save_room_data(
                    {CONF_NOTIFICATION_LIGHT_ENABLED: True, **user_input}
                )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NOTIFICATION_TRIGGER_ENTITY,
                    description={"suggested_value": d.get(CONF_NOTIFICATION_TRIGGER_ENTITY)},
                ): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain=["input_boolean", "binary_sensor", "switch", "sensor"])
                ),
                vol.Optional(
                    CONF_NOTIFICATION_LIGHT_ENTITY,
                    description={"suggested_value": d.get(CONF_NOTIFICATION_LIGHT_ENTITY)},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="light")),
                vol.Required(
                    CONF_NOTIFICATION_COLOR,
                    default=d.get(CONF_NOTIFICATION_COLOR, DEFAULT_NOTIFICATION_COLOR),
                ): selector.ColorRGBSelector(),
                vol.Required(
                    CONF_NOTIFICATION_BRIGHTNESS_PCT,
                    default=d.get(CONF_NOTIFICATION_BRIGHTNESS_PCT, DEFAULT_NOTIFICATION_BRIGHTNESS_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_NOTIFICATION_PRESENCE_GATED,
                    default=d.get(CONF_NOTIFICATION_PRESENCE_GATED, DEFAULT_NOTIFICATION_PRESENCE_GATED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFICATION_SUPPRESSION_ENTITIES,
                    description={"suggested_value": d.get(CONF_NOTIFICATION_SUPPRESSION_ENTITIES, [])},
                ): OptionalEntitySelector(selector.EntitySelectorConfig(multiple=True)),
            }
        )
        return self.async_show_form(
            step_id="room_opt_notification_details",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_system_menu(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Top-level menu for the unified Passable Smart Light Engine system entry."""
        return self.async_show_menu(
            step_id="system_menu",
            menu_options=["holiday_menu", "presence_simulation_options"],
        )

    async def async_step_presence_simulation_options(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Presence simulation Step 1: enablement, label, and strategy."""
        d = self._entry.data
        target_label = d.get(CONF_SIMULATION_LABEL, DEFAULT_SIMULATION_LABEL)

        if user_input is not None:
            self._pending_sim = dict(user_input)
            if not bool(user_input.get(CONF_SIMULATION_ENABLED, DEFAULT_SIMULATION_ENABLED)):
                new_data = {**self._entry.data, **self._pending_sim}
                self.hass.data.setdefault(DOMAIN, {}).setdefault(
                    "skip_reload_entries", set()
                ).add(self._entry.entry_id)
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.update_options(new_data)
                return self.async_create_entry(title="", data={})
            return await self.async_step_presence_simulation_options_tuning()

        summary_text = _build_simulation_lights_summary(self.hass, target_label)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SIMULATION_ENABLED,
                    default=d.get(CONF_SIMULATION_ENABLED, DEFAULT_SIMULATION_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(CONF_SIMULATION_LABEL, default=target_label): selector.TextSelector(),
                vol.Required(
                    CONF_SIMULATION_MODE,
                    default=d.get(CONF_SIMULATION_MODE, DEFAULT_SIMULATION_MODE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="hybrid",
                                label="Hybrid (Smart History Replay with Synthetic Fallback)",
                            ),
                            selector.SelectOptionDict(
                                value="history_replay",
                                label="Smart History Replay Only",
                            ),
                            selector.SelectOptionDict(
                                value="synthetic_routine",
                                label="Synthetic Realistic Evening Routine Only",
                            ),
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="presence_simulation_options",
            data_schema=schema,
            description_placeholders={"lights_summary": summary_text},
        )

    async def async_step_presence_simulation_options_tuning(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Presence simulation Step 2: tuning parameters relevant to the selected strategy."""
        d = self._entry.data
        if user_input is not None:
            new_data = {**self._entry.data, **self._pending_sim, **user_input}
            self.hass.data.setdefault(DOMAIN, {}).setdefault(
                "skip_reload_entries", set()
            ).add(self._entry.entry_id)
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
            if coordinator:
                coordinator.update_options(new_data)
            return self.async_create_entry(title="", data={})

        target_label = str(
            self._pending_sim.get(CONF_SIMULATION_LABEL, d.get(CONF_SIMULATION_LABEL, DEFAULT_SIMULATION_LABEL))
        ).strip() or DEFAULT_SIMULATION_LABEL
        sim_mode = str(self._pending_sim.get(CONF_SIMULATION_MODE, d.get(CONF_SIMULATION_MODE, DEFAULT_SIMULATION_MODE)))
        summary_text = _build_simulation_lights_summary(self.hass, target_label)

        fields: Dict[Any, Any] = {}
        if sim_mode in ("hybrid", "history_replay"):
            fields[
                vol.Required(
                    CONF_SIMULATION_LOOKBACK_DAYS,
                    default=d.get(CONF_SIMULATION_LOOKBACK_DAYS, DEFAULT_SIMULATION_LOOKBACK_DAYS),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
            )
        fields[
            vol.Required(
                CONF_SIMULATION_JITTER_MIN,
                default=d.get(CONF_SIMULATION_JITTER_MIN, DEFAULT_SIMULATION_JITTER_MIN),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=60, step=5, mode=selector.NumberSelectorMode.BOX)
        )
        fields[
            vol.Required(
                CONF_SIMULATION_ARRIVAL_GRACE_MIN,
                default=d.get(CONF_SIMULATION_ARRIVAL_GRACE_MIN, DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=30, step=1, mode=selector.NumberSelectorMode.BOX)
        )
        fields[
            vol.Required(
                CONF_SIMULATION_MAX_BRIGHTNESS_PCT,
                default=d.get(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
        )

        return self.async_show_form(
            step_id="presence_simulation_options_tuning",
            data_schema=vol.Schema(fields),
            description_placeholders={"lights_summary": summary_text},
        )

    async def async_step_holiday_menu(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
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
        """Exterior lighting Step 1: enablement, fixtures, baseline look, and triggers."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options

        if user_input is not None:
            self._pending_exterior = dict(user_input)
            if not bool(user_input.get(CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED, DEFAULT_EXTERIOR_DUSK_TO_DAWN_ENABLED)):
                holiday_store.update_options(self._pending_exterior)
                await holiday_store.async_save()
                coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
                if coordinator:
                    self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
                return self.async_create_entry(title="", data={})
            return await self.async_step_holiday_exterior_schedule()

        raw_lights = opts.get(CONF_EXTERIOR_LIGHTS, DEFAULT_EXTERIOR_LIGHTS)
        if raw_lights == DEFAULT_EXTERIOR_LIGHTS:
            default_lights = _existing_entities_or_empty(self.hass, raw_lights)
        else:
            default_lights = raw_lights or []

        kelvin_unit = getattr(getattr(selector, "ColorTempSelectorUnit", None), "KELVIN", "kelvin")
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED,
                    default=opts.get(CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED, DEFAULT_EXTERIOR_DUSK_TO_DAWN_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_EXTERIOR_LIGHTS,
                    default=default_lights,
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Required(
                    CONF_EXTERIOR_BASELINE_KELVIN,
                    default=opts.get(CONF_EXTERIOR_BASELINE_KELVIN, DEFAULT_EXTERIOR_BASELINE_KELVIN),
                ): selector.ColorTempSelector(
                    selector.ColorTempSelectorConfig(min=2000, max=6500, unit=kelvin_unit)
                ),
                vol.Required(
                    CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT,
                    default=opts.get(CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT, DEFAULT_EXTERIOR_BASELINE_BRIGHTNESS_PCT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=5, mode=selector.NumberSelectorMode.SLIDER)
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
                vol.Required(
                    CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR,
                    default=opts.get(CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR, DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="all_night",
                                label="All Night (Keep Holiday Scene Until Sunrise)",
                            ),
                            selector.SelectOptionDict(
                                value="revert_to_baseline_at_sleep",
                                label="Revert to Warm White Baseline at Sleep",
                            ),
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(step_id="holiday_exterior_settings", data_schema=schema)

    async def async_step_holiday_exterior_schedule(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Exterior lighting Step 2: show only timing & state inputs matching selected triggers."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options
        if user_input is not None:
            holiday_store.update_options({**self._pending_exterior, **user_input})
            await holiday_store.async_save()
            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
            return self.async_create_entry(title="", data={})

        on_trigger = self._pending_exterior.get(
            CONF_EXTERIOR_ON_TRIGGER, opts.get(CONF_EXTERIOR_ON_TRIGGER, DEFAULT_EXTERIOR_ON_TRIGGER)
        )
        off_trigger = self._pending_exterior.get(
            CONF_EXTERIOR_OFF_TRIGGER, opts.get(CONF_EXTERIOR_OFF_TRIGGER, DEFAULT_EXTERIOR_OFF_TRIGGER)
        )
        late_night_behavior = self._pending_exterior.get(
            CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR,
            opts.get(CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR, DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR),
        )

        fields: Dict[Any, Any] = {}
        if on_trigger == "fixed_time":
            fields[
                vol.Required(
                    CONF_EXTERIOR_ON_TIME,
                    default=opts.get(CONF_EXTERIOR_ON_TIME, DEFAULT_EXTERIOR_ON_TIME),
                )
            ] = OptionalTimeSelector()
        else:
            fields[
                vol.Required(
                    CONF_EXTERIOR_SUNSET_OFFSET_MIN,
                    default=opts.get(CONF_EXTERIOR_SUNSET_OFFSET_MIN, DEFAULT_EXTERIOR_SUNSET_OFFSET_MIN),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
            )

        if off_trigger == "fixed_time":
            fields[
                vol.Required(
                    CONF_EXTERIOR_OFF_TIME,
                    default=opts.get(CONF_EXTERIOR_OFF_TIME, DEFAULT_EXTERIOR_OFF_TIME),
                )
            ] = OptionalTimeSelector()
        else:
            fields[
                vol.Required(
                    CONF_EXTERIOR_SUNRISE_OFFSET_MIN,
                    default=opts.get(CONF_EXTERIOR_SUNRISE_OFFSET_MIN, DEFAULT_EXTERIOR_SUNRISE_OFFSET_MIN),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
            )

        if late_night_behavior == "revert_to_baseline_at_sleep":
            raw_home = opts.get(CONF_HOLIDAY_HOME_STATE_ENTITY, DEFAULT_HOLIDAY_HOME_STATE_ENTITY)
            default_home = (
                _existing_entities_or_empty(self.hass, raw_home)
                if raw_home == DEFAULT_HOLIDAY_HOME_STATE_ENTITY
                else raw_home
            )
            fields[
                vol.Optional(
                    CONF_HOLIDAY_HOME_STATE_ENTITY,
                    description={"suggested_value": default_home},
                )
            ] = OptionalEntitySelector(selector.EntitySelectorConfig(domain=["input_select", "input_boolean", "binary_sensor"]))

        return self.async_show_form(
            step_id="holiday_exterior_schedule",
            data_schema=vol.Schema(fields),
        )

    async def async_step_holiday_decoration_settings(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Outdoor decorations Step 1: enablement, smart plugs, label, and triggers."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options

        if user_input is not None:
            self._pending_decorations = dict(user_input)
            if not bool(user_input.get(CONF_HOLIDAY_DECORATIONS_ENABLED, DEFAULT_HOLIDAY_DECORATIONS_ENABLED)):
                holiday_store.update_options(self._pending_decorations)
                await holiday_store.async_save()
                coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
                if coordinator:
                    self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
                return self.async_create_entry(title="", data={})
            return await self.async_step_holiday_decoration_schedule()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOLIDAY_DECORATIONS_ENABLED,
                    default=opts.get(CONF_HOLIDAY_DECORATIONS_ENABLED, DEFAULT_HOLIDAY_DECORATIONS_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_HOLIDAY_GLOBAL_DECORATIONS,
                    default=opts.get(CONF_HOLIDAY_GLOBAL_DECORATIONS, DEFAULT_HOLIDAY_GLOBAL_DECORATIONS),
                ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="switch", multiple=True)),
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
                vol.Required(
                    CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
                    default=opts.get(
                        CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
                        DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION,
                    ),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="holiday_decoration_settings", data_schema=schema)

    async def async_step_holiday_decoration_schedule(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Outdoor decorations Step 2: show only timing & state inputs matching selected triggers."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        opts = holiday_store.options
        on_trigger = self._pending_decorations.get(
            CONF_DECORATIONS_ON_TRIGGER, opts.get(CONF_DECORATIONS_ON_TRIGGER, DEFAULT_DECORATIONS_ON_TRIGGER)
        )
        off_trigger = self._pending_decorations.get(
            CONF_DECORATIONS_OFF_TRIGGER, opts.get(CONF_DECORATIONS_OFF_TRIGGER, DEFAULT_DECORATIONS_OFF_TRIGGER)
        )

        if user_input is not None:
            holiday_store.update_options({**self._pending_decorations, **user_input})
            await holiday_store.async_save()
            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
            return self.async_create_entry(title="", data={})

        fields: Dict[Any, Any] = {}
        if on_trigger == "fixed_time":
            fields[
                vol.Required(
                    CONF_DECORATIONS_ON_TIME,
                    default=opts.get(CONF_DECORATIONS_ON_TIME, DEFAULT_DECORATIONS_ON_TIME),
                )
            ] = OptionalTimeSelector()
        else:
            fields[
                vol.Required(
                    CONF_DECORATIONS_SUNSET_OFFSET_MIN,
                    default=opts.get(CONF_DECORATIONS_SUNSET_OFFSET_MIN, DEFAULT_DECORATIONS_SUNSET_OFFSET_MIN),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=-120, max=120, step=5, mode=selector.NumberSelectorMode.BOX)
            )

        if off_trigger == "fixed_time":
            fields[
                vol.Required(
                    CONF_DECORATIONS_OFF_TIME,
                    default=opts.get(CONF_DECORATIONS_OFF_TIME, DEFAULT_DECORATIONS_OFF_TIME),
                )
            ] = OptionalTimeSelector()
        elif off_trigger == "sleep":
            raw_home = opts.get(CONF_HOLIDAY_HOME_STATE_ENTITY, DEFAULT_HOLIDAY_HOME_STATE_ENTITY)
            default_home = (
                _existing_entities_or_empty(self.hass, raw_home)
                if raw_home == DEFAULT_HOLIDAY_HOME_STATE_ENTITY
                else raw_home
            )
            fields[
                vol.Optional(
                    CONF_HOLIDAY_HOME_STATE_ENTITY,
                    description={"suggested_value": default_home},
                )
            ] = OptionalEntitySelector(selector.EntitySelectorConfig(domain=["input_select", "input_boolean", "binary_sensor"]))

        if not fields:
            holiday_store.update_options(self._pending_decorations)
            await holiday_store.async_save()
            coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
            if coordinator:
                self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="holiday_decoration_schedule",
            data_schema=vol.Schema(fields),
        )

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
        options = [selector.SelectOptionDict(value="__add_new__", label="➕ Add New Holiday...")]
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
        """Holiday Step 1: edit metadata, dates, participating targets, and lighting mode."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = {} if is_new else holiday_store.holidays.get(self._selected_holiday_id, {})
        errors: Dict[str, str] = {}

        if user_input is not None:
            if user_input.get("delete_holiday") and not is_new:
                holiday_store.delete_holiday(self._selected_holiday_id)
                await holiday_store.async_save()
                return self.async_create_entry(title="", data={})

            s_date_raw = str(user_input.get("start_date", "10-01")).strip()
            e_date_raw = str(user_input.get("end_date", "10-31")).strip()
            if not _validate_mm_dd(s_date_raw):
                errors["start_date"] = "invalid_date"
            if not _validate_mm_dd(e_date_raw):
                errors["end_date"] = "invalid_date"

            if not errors:
                self._pending_holiday = {**user_input, "start_date": s_date_raw, "end_date": e_date_raw}
                return await self.async_step_holiday_edit_mode()

        fields: Dict[Any, Any] = {
            vol.Required("name", default=curr_holiday.get("name", "Custom Holiday")): selector.TextSelector(),
            vol.Required("enabled", default=curr_holiday.get("enabled", True)): selector.BooleanSelector(),
            vol.Required("start_date", default=curr_holiday.get("start_date", "10-01")): selector.TextSelector(),
            vol.Required("end_date", default=curr_holiday.get("end_date", "10-31")): selector.TextSelector(),
            vol.Required("icon", default=curr_holiday.get("icon", "mdi:ghost")): selector.TextSelector(),
            vol.Optional("phrase", default=curr_holiday.get("phrase", "Happy Holidays!")): selector.TextSelector(),
            vol.Optional("theme_color", default=curr_holiday.get("theme_color", "#9c4600")): selector.TextSelector(),
            vol.Required("light_mode", default=curr_holiday.get("light_mode", LIGHT_MODE_RGB)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_holiday_mode_options())
            ),
            vol.Required("decorations_on", default=curr_holiday.get("decorations_on", True)): selector.BooleanSelector(),
            vol.Optional(
                "participating_lights", default=curr_holiday.get("participating_lights", [])
            ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
            vol.Optional(
                "participating_decorations", default=curr_holiday.get("participating_decorations", [])
            ): OptionalEntitySelector(selector.EntitySelectorConfig(domain="switch", multiple=True)),
        }

        if not is_new:
            fields[vol.Optional("delete_holiday", default=False)] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="holiday_edit",
            data_schema=vol.Schema(fields),
            errors=errors,
        )

    async def async_step_holiday_edit_mode(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Holiday Step 2: show only lighting parameters matching the chosen light_mode."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = {} if is_new else holiday_store.holidays.get(self._selected_holiday_id, {})
        mode = str(self._pending_holiday.get("light_mode", curr_holiday.get("light_mode", LIGHT_MODE_RGB)))
        errors: Dict[str, str] = {}

        if user_input is not None:
            errors = _validate_lighting_mode_fields(mode, user_input)
            if not errors:
                self._pending_holiday_mode_data = dict(user_input)
                self._pending_light_overrides = copy.deepcopy(curr_holiday.get("light_overrides") or {})
                if user_input.get("customize_individual_lights"):
                    return await self.async_step_holiday_light_select()
                return await self._async_finalize_holiday_save()

        fields = _build_lighting_mode_fields(self.hass, mode, curr_holiday, target_light_id=None)
        fields[
            vol.Optional(
                "customize_individual_lights",
                default=bool(curr_holiday.get("light_overrides")),
            )
        ] = selector.BooleanSelector()

        return self.async_show_form(
            step_id="holiday_edit_mode",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "holiday_name": str(self._pending_holiday.get("name", "Holiday")),
                "mode_name": _HOLIDAY_MODE_LABELS.get(mode, mode),
            },
        )

    def _get_holiday_candidate_lights(self, curr_holiday: Mapping[str, Any]) -> List[str]:
        """Resolve all candidate lights for per-light holiday customization."""
        holiday_coord = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
        explicit = self._pending_holiday.get("participating_lights") or []
        raw_list: List[str] = []
        if explicit:
            raw_list.extend(explicit)
        elif holiday_coord:
            raw_list.extend(holiday_coord.resolve_participating_lights({**curr_holiday, "participating_lights": []}))
        else:
            raw_list.extend(curr_holiday.get("participating_lights") or [])

        expanded: List[str] = []
        for lid in raw_list:
            if not lid:
                continue
            members = get_light_members(self.hass, lid)
            for m in (members if len(members) > 1 else [lid]):
                if m not in expanded:
                    expanded.append(m)

        for ov_id in self._pending_light_overrides:
            if ov_id and ov_id not in expanded:
                expanded.append(ov_id)

        return expanded

    async def async_step_holiday_light_select(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Per-light Holiday Step 3: choose a participating light to customize or save."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = {} if is_new else holiday_store.holidays.get(self._selected_holiday_id, {})

        if user_input is not None:
            extra_light = str(user_input.get("add_extra_light") or "").strip()
            selected_action = str(user_input.get("selected_light_action") or "__save__")
            if extra_light:
                self._editing_holiday_light_id = extra_light
                return await self.async_step_holiday_light_mode()
            if selected_action == "__save__":
                return await self._async_finalize_holiday_save()
            self._editing_holiday_light_id = selected_action
            return await self.async_step_holiday_light_mode()

        candidates = self._get_holiday_candidate_lights(curr_holiday)
        summary_lines = []
        options = [selector.SelectOptionDict(value="__save__", label="✅ Save & Finish Holiday")]
        for lid in candidates:
            st = self.hass.states.get(lid)
            fname = st.attributes.get("friendly_name", lid) if st else lid
            ov_cfg = self._pending_light_overrides.get(lid)
            ov_label = _format_override_summary(ov_cfg)
            summary_lines.append(f"- **{fname}** (`{lid}`): {ov_label}")
            options.append(
                selector.SelectOptionDict(value=lid, label=f"Customize: {fname} [{ov_label}]")
            )

        overrides_summary = (
            "\n".join(summary_lines)
            if summary_lines
            else "No default participating lights configured yet. Use **Add Any Light to Customize** below."
        )

        schema = vol.Schema(
            {
                vol.Required("selected_light_action", default="__save__"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                ),
                vol.Optional("add_extra_light"): OptionalEntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
            }
        )
        return self.async_show_form(
            step_id="holiday_light_select",
            data_schema=schema,
            description_placeholders={
                "holiday_name": str(self._pending_holiday.get("name", "Holiday")),
                "overrides_summary": overrides_summary,
            },
        )

    async def async_step_holiday_light_mode(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Per-light Holiday Step 4: choose the mode for one specific light."""
        light_id = self._editing_holiday_light_id or ""
        if not light_id:
            return await self.async_step_holiday_light_select()

        if user_input is not None:
            chosen_mode = str(user_input.get("light_mode", LIGHT_MODE_DEFAULT))
            if chosen_mode == LIGHT_MODE_DEFAULT:
                self._pending_light_overrides.pop(light_id, None)
                return await self.async_step_holiday_light_select()
            if chosen_mode == LIGHT_MODE_OFF:
                self._pending_light_overrides[light_id] = {"light_mode": LIGHT_MODE_OFF}
                return await self.async_step_holiday_light_select()
            self._editing_holiday_light_mode = chosen_mode
            return await self.async_step_holiday_light_details()

        curr_ov = self._pending_light_overrides.get(light_id, {})
        st = self.hass.states.get(light_id)
        light_name = st.attributes.get("friendly_name", light_id) if st else light_id
        schema = vol.Schema(
            {
                vol.Required(
                    "light_mode", default=curr_ov.get("light_mode", LIGHT_MODE_DEFAULT)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_per_light_mode_options())
                )
            }
        )
        return self.async_show_form(
            step_id="holiday_light_mode",
            data_schema=schema,
            description_placeholders={
                "holiday_name": str(self._pending_holiday.get("name", "Holiday")),
                "light_name": light_name,
                "light_entity": light_id,
            },
        )

    async def async_step_holiday_light_details(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Per-light Holiday Step 5: configure mode-specific parameters for one light."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = (
            {} if (is_new or not holiday_store) else holiday_store.holidays.get(self._selected_holiday_id, {})
        )

        light_id = self._editing_holiday_light_id or ""
        mode = self._editing_holiday_light_mode or LIGHT_MODE_RGB
        errors: Dict[str, str] = {}

        if user_input is not None:
            errors = _validate_lighting_mode_fields(mode, user_input)
            if not errors:
                clean_ov: Dict[str, Any] = {"light_mode": mode}
                for key, val in user_input.items():
                    if key == "rgb_color" and isinstance(val, (list, tuple)) and len(val) >= 3:
                        clean_ov["rgb_color"] = [int(val[0]), int(val[1]), int(val[2])]
                    elif key in ("color_temp_kelvin", "brightness_pct") and val is not None:
                        clean_ov[key] = int(val)
                    elif key == "dynamic_scene":
                        clean_ov[key] = bool(val)
                    elif val is not None:
                        clean_ov[key] = str(val).strip()
                self._pending_light_overrides[light_id] = clean_ov
                return await self.async_step_holiday_light_select()

        defaults = {**curr_holiday, **self._pending_holiday_mode_data, **self._pending_light_overrides.get(light_id, {})}
        fields = _build_lighting_mode_fields(self.hass, mode, defaults, target_light_id=light_id)
        st = self.hass.states.get(light_id)
        light_name = st.attributes.get("friendly_name", light_id) if st else light_id

        return self.async_show_form(
            step_id="holiday_light_details",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "holiday_name": str(self._pending_holiday.get("name", "Holiday")),
                "light_name": light_name,
                "mode_name": _HOLIDAY_MODE_LABELS.get(mode, mode),
            },
        )

    async def _async_finalize_holiday_save(self) -> config_entries.ConfigFlowResult:
        """Persist holiday definition including any per-light overrides."""
        holiday_store = self.hass.data.get(DOMAIN, {}).get("holiday_store")
        if not holiday_store:
            return self.async_abort(reason="store_unavailable")

        is_new = getattr(self, "_selected_holiday_id", "__add_new__") == "__add_new__"
        curr_holiday = {} if is_new else holiday_store.holidays.get(self._selected_holiday_id, {})
        mode_data = self._pending_holiday_mode_data
        mode = str(self._pending_holiday.get("light_mode", curr_holiday.get("light_mode", LIGHT_MODE_RGB)))

        h_name = str(self._pending_holiday.get("name", curr_holiday.get("name", "Custom Holiday"))).strip()
        h_id = (
            self._selected_holiday_id
            if not is_new
            else _slugify_room_id(h_name.replace("'", "")) or "custom_holiday"
        )

        raw_rgb = mode_data.get("rgb_color", curr_holiday.get("rgb_color", [255, 140, 0]))
        if isinstance(raw_rgb, (list, tuple)) and len(raw_rgb) >= 3:
            rgb = [int(raw_rgb[0]), int(raw_rgb[1]), int(raw_rgb[2])]
        else:
            rgb = curr_holiday.get("rgb_color", [255, 140, 0])

        clean_overrides = {
            lid: ov
            for lid, ov in self._pending_light_overrides.items()
            if lid and isinstance(ov, dict) and ov.get("light_mode", LIGHT_MODE_DEFAULT) != LIGHT_MODE_DEFAULT
        }

        holiday_data = {
            "id": h_id,
            "name": h_name,
            "enabled": bool(self._pending_holiday.get("enabled", True)),
            "start_date": self._pending_holiday["start_date"],
            "end_date": self._pending_holiday["end_date"],
            "icon": str(self._pending_holiday.get("icon", "mdi:calendar-star")).strip(),
            "phrase": str(self._pending_holiday.get("phrase", "")).strip(),
            "theme_color": str(self._pending_holiday.get("theme_color", "#9c4600")).strip(),
            "light_mode": mode,
            "hue_scene": str(mode_data.get("hue_scene", curr_holiday.get("hue_scene", "")) or "").strip(),
            "dynamic_scene": bool(mode_data.get("dynamic_scene", curr_holiday.get("dynamic_scene", True))),
            "ha_scene": str(mode_data.get("ha_scene", curr_holiday.get("ha_scene", "")) or "").strip(),
            "wled_preset_entity": str(mode_data.get("wled_preset_entity", curr_holiday.get("wled_preset_entity", "")) or "").strip(),
            "wled_preset": str(mode_data.get("wled_preset", curr_holiday.get("wled_preset", "")) or "").strip(),
            "wled_palette_entity": str(mode_data.get("wled_palette_entity", curr_holiday.get("wled_palette_entity", "")) or "").strip(),
            "wled_palette": str(mode_data.get("wled_palette", curr_holiday.get("wled_palette", "")) or "").strip(),
            "effect": str(mode_data.get("effect", curr_holiday.get("effect", "")) or "").strip(),
            "fallback_effect": str(mode_data.get("fallback_effect", curr_holiday.get("fallback_effect", "")) or "").strip(),
            "rgb_color": rgb,
            "color_temp_kelvin": int(mode_data.get("color_temp_kelvin", curr_holiday.get("color_temp_kelvin", 2200))),
            "brightness_pct": int(mode_data.get("brightness_pct", curr_holiday.get("brightness_pct", 100))),
            "decorations_on": bool(self._pending_holiday.get("decorations_on", True)),
            "participating_lights": self._pending_holiday.get("participating_lights") or [],
            "participating_decorations": self._pending_holiday.get("participating_decorations") or [],
            "light_overrides": clean_overrides,
        }

        holiday_store.set_holiday(h_id, holiday_data)
        await holiday_store.async_save()

        coordinator = self.hass.data.get(DOMAIN, {}).get("holiday_coordinator")
        if coordinator:
            coordinator._active_holiday = coordinator.evaluate_active_holiday()
            self.hass.async_create_task(coordinator._async_evaluate_schedule_trigger())

        return self.async_create_entry(title="", data={})

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
            {vol.Required("confirm_reset", default=False): selector.BooleanSelector()}
        )
        return self.async_show_form(step_id="holiday_reset", data_schema=schema)
