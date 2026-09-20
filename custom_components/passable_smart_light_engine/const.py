"""Constants for the Passable Adaptive Smart Lighting Controller integration."""

from typing import List

DOMAIN = "passable_smart_light_engine"
LEGACY_DOMAIN = "smart_light_engine"

PLATFORMS = ["switch", "sensor", "binary_sensor", "number", "button", "select"]

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_learning_data"
LEGACY_DATA_PATHS = [
    "/config/pyscript/apps/smart_light_engine/learning_data.json",
    "/config/pyscript/apps/passable_smart_light_engine/learning_data.json",
]

# Configuration keys
CONF_ROOM_ID = "room_id"
CONF_LIGHT_ENTITY = "light_entity"
CONF_SECONDARY_LIGHTS = "secondary_lights"
CONF_SUPPRESS_MAIN_WHEN_SECONDARY_ON = "suppress_main_when_secondary_on"
CONF_PRESENCE_ENTITIES = "presence_entity"
CONF_LUX_SENSOR = "lux_sensor"
CONF_TARGET_LUX = "target_lux"
CONF_DEFAULT_LUX_RATIO = "default_lux_ratio"
CONF_PRESENCE_TIMEOUT_MIN = "presence_timeout_min"
CONF_MIN_OCCUPIED_PCT = "min_occupied_pct"

CONF_CIRCADIAN_ENABLED = "circadian_enabled"
CONF_MIN_COLOR_TEMP = "min_color_temp"
CONF_MAX_COLOR_TEMP = "max_color_temp"

CONF_MEDIA_ENTITIES = "media_entities"
CONF_MEDIA_SEED_PCT = "media_seed_pct"
CONF_MEDIA_RESPECT_AMBIENT_LUX = "media_respect_ambient_lux"

CONF_BYPASS_FREEZE_ENTITIES = "bypass_freeze_entities"
CONF_BYPASS_OFF_ENTITIES = "bypass_off_entities"
CONF_OVERRIDE_TIMEOUT_MIN = "override_timeout_min"
CONF_MANUAL_OVERRIDE_ENTITY = "manual_override_entity"
CONF_CREATE_OVERRIDE_SWITCH = "create_override_switch"
CONF_CREATE_FREEZE_SWITCH = "create_freeze_switch"
CONF_IGNORE_MAX_BRIGHTNESS_OVERRIDE = "ignore_max_brightness_override"

CONF_LATE_NIGHT_ENABLED = "late_night_enabled"
CONF_LATE_NIGHT_PCT = "late_night_pct"
CONF_LATE_NIGHT_CONDITION_TYPE = "late_night_condition_type"
CONF_LATE_NIGHT_ENTITY = "late_night_entity"
CONF_LATE_NIGHT_START_TIME = "late_night_start_time"
CONF_LATE_NIGHT_START_ENTITY = "late_night_start_entity"
CONF_LATE_NIGHT_STOP_TIME = "late_night_stop_time"
CONF_LATE_NIGHT_STOP_ENTITY = "late_night_stop_entity"

CONF_POWER_GRID_ENTITY = "power_grid_entity"
CONF_SETTLING_COOLDOWN_SEC = "settling_cooldown_sec"

# UI Section Identifiers
SECTION_HARDWARE = "hardware_presence"
SECTION_CIRCADIAN = "circadian"
SECTION_LATE_NIGHT = "late_night"
SECTION_MEDIA = "media"
SECTION_BYPASSES = "bypasses"

# Default values
DEFAULT_TARGET_LUX = 40
DEFAULT_LUX_RATIO = 0.20
DEFAULT_PRESENCE_TIMEOUT_MIN = 5
DEFAULT_MIN_OCCUPIED_PCT = 0
DEFAULT_SETTLING_COOLDOWN_SEC = 45.0
DEFAULT_SECONDARY_LIGHTS: List[str] = []
DEFAULT_SUPPRESS_MAIN_WHEN_SECONDARY_ON = False
MAX_CLOSED_LOOP_TRIM_PCT = 15
SEVERE_LUX_DEFICIT_THRESHOLD = 15.0

DEFAULT_CIRCADIAN_ENABLED = True
DEFAULT_MIN_COLOR_TEMP = 2700
DEFAULT_MAX_COLOR_TEMP = 5500

DEFAULT_MEDIA_SEED_PCT = 20
DEFAULT_MEDIA_RESPECT_AMBIENT_LUX = True

DEFAULT_OVERRIDE_TIMEOUT_MIN = 60
DEFAULT_IGNORE_MAX_BRIGHTNESS_OVERRIDE = True

DEFAULT_LATE_NIGHT_ENABLED = False
DEFAULT_LATE_NIGHT_PCT = 20
DEFAULT_LATE_NIGHT_CONDITION_TYPE = "time"
DEFAULT_LATE_NIGHT_START_TIME = "22:00:00"
DEFAULT_LATE_NIGHT_STOP_TIME = "06:00:00"

DEFAULT_POWER_GRID_ENTITY = "binary_sensor.power_grid_status"

MIN_VISIBLE_PCT = 5
ECHO_GUARD_WINDOW_SEC = 30.0
ECHO_GUARD_TOLERANCE_PCT = 8.0

# Mesh, convergence, and arbitration timings
DEFAULT_MESH_SETTLE_SEC = 12.0
ECHO_CONVERGENCE_SETTLE_SEC = 2.5
STARTUP_SETTLE_SEC = 30.0
DWELL_TIME_SEC = 180.0
SENSOR_DEBOUNCE_SEC = 0.5
LUX_ADJUST_RATE_LIMIT_SEC = 25.0
LUX_DEADBAND_PCT = 0.10
MIN_LUX_DEADBAND = 5.0
BRIGHTNESS_HYSTERESIS_PCT = 7
OVERRIDE_FADE_TRANSITION_SEC = 7.0

# Active states: idle and standby excluded to prevent media lockup
ACTIVE_STATES = ["on", "playing", "true", "home", "paused", "buffering"]

# Event names (for backward compatibility)
EVENT_SMART_LIGHT_ENGINE = "smart_light_engine_event"
EVENT_PASSABLE_SMART_LIGHT_ENGINE = "passable_smart_light_engine_event"

# Services
SERVICE_RESET_LEARNING_DATA = "reset_learning_data"
ATTR_RESET_ROOM_ID = "room_id"
ATTR_RESET_TYPE = "reset_type"
RESET_TYPES = ["all", "user_prefs", "room_curves", "media_prefs", "late_night_prefs"]

SERVICE_CALIBRATE_ROOM_CURVE = "calibrate_room_curve"
ATTR_CALIBRATE_ROOM_ID = "room_id"
ATTR_CALIBRATE_FORCE = "force"

# Presence Simulation configuration keys
CONF_SIMULATION_ENABLED = "simulation_enabled"
CONF_SIMULATION_LABEL = "simulation_label"
CONF_SIMULATION_MODE = "simulation_mode"
CONF_SIMULATION_LOOKBACK_DAYS = "simulation_lookback_days"
CONF_SIMULATION_JITTER_MIN = "simulation_jitter_min"
CONF_SIMULATION_MAX_BRIGHTNESS_PCT = "simulation_max_brightness_pct"
CONF_SIMULATION_ARRIVAL_GRACE_MIN = "simulation_arrival_grace_min"

# Presence Simulation modes
SIMULATION_MODE_HYBRID = "hybrid"
SIMULATION_MODE_HISTORY = "history_replay"
SIMULATION_MODE_SYNTHETIC = "synthetic_routine"
SIMULATION_MODES = [SIMULATION_MODE_HYBRID, SIMULATION_MODE_HISTORY, SIMULATION_MODE_SYNTHETIC]

# Presence Simulation defaults
DEFAULT_SIMULATION_ENABLED = True
DEFAULT_SIMULATION_LABEL = "lights_presence_simulation"
DEFAULT_SIMULATION_MODE = SIMULATION_MODE_HYBRID
DEFAULT_SIMULATION_LOOKBACK_DAYS = 7
DEFAULT_SIMULATION_JITTER_MIN = 15
DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT = 40
DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN = 5

MODE_PRESENCE_SIMULATION = "presence_simulation"

# Presence Simulation services
SERVICE_START_PRESENCE_SIMULATION = "start_presence_simulation"
SERVICE_STOP_PRESENCE_SIMULATION = "stop_presence_simulation"

# Entity IDs & unique IDs for drop-in compatibility
PRESENCE_SIMULATION_SWITCH_ENTITY_ID = "switch.simulate_presence_away_mode"
PRESENCE_SIMULATION_SWITCH_UNIQUE_ID = "switch.simulate_presence__away_mode_"
PRESENCE_SIMULATION_MASTER_SWITCH_ENTITY_ID = "switch.presence_simulation"
PRESENCE_SIMULATION_MASTER_SWITCH_UNIQUE_ID = "passable_presence_simulation_master"

# Holiday Lighting configuration keys
CONF_HOLIDAY_LIGHTING_ENABLED = "holiday_lighting_enabled"
CONF_HOLIDAY_DECORATIONS_ENABLED = "holiday_decorations_enabled"
CONF_HOLIDAY_GLOBAL_LIGHTS = "holiday_global_lights"
CONF_HOLIDAY_GLOBAL_DECORATIONS = "holiday_global_decorations"
CONF_HOLIDAY_GLOBAL_LABEL = "holiday_global_label"
CONF_HOLIDAY_SUNSET_OFFSET_MIN = "holiday_sunset_offset_min"
CONF_HOLIDAY_SUNRISE_OFFSET_MIN = "holiday_sunrise_offset_min"
CONF_HOLIDAY_HOME_STATE_ENTITY = "holiday_home_state_entity"
CONF_HOLIDAY_OFF_TRIGGER = "holiday_off_trigger"
CONF_HOLIDAY_OFF_TIME = "holiday_off_time"
CONF_HOLIDAY_RESPECT_PRESENCE_SIMULATION = "holiday_respect_presence_simulation"

# Dusk-to-Dawn Exterior Lighting configuration keys
CONF_EXTERIOR_DUSK_TO_DAWN_ENABLED = "exterior_dusk_to_dawn_enabled"
CONF_EXTERIOR_LIGHTS = "exterior_lights"
CONF_EXTERIOR_ON_TRIGGER = "exterior_on_trigger"
CONF_EXTERIOR_SUNSET_OFFSET_MIN = "exterior_sunset_offset_min"
CONF_EXTERIOR_ON_TIME = "exterior_on_time"
CONF_EXTERIOR_OFF_TRIGGER = "exterior_off_trigger"
CONF_EXTERIOR_SUNRISE_OFFSET_MIN = "exterior_sunrise_offset_min"
CONF_EXTERIOR_OFF_TIME = "exterior_off_time"
CONF_EXTERIOR_BASELINE_KELVIN = "exterior_baseline_kelvin"
CONF_EXTERIOR_BASELINE_BRIGHTNESS_PCT = "exterior_baseline_brightness_pct"
CONF_HOLIDAY_LATE_NIGHT_BEHAVIOR = "holiday_late_night_behavior"

# Decoration Plugs configuration keys
CONF_DECORATIONS_ON_TRIGGER = "decorations_on_trigger"
CONF_DECORATIONS_SUNSET_OFFSET_MIN = "decorations_sunset_offset_min"
CONF_DECORATIONS_OFF_TRIGGER = "decorations_off_trigger"
CONF_DECORATIONS_OFF_TIME = "decorations_off_time"

# Holiday Lighting defaults
DEFAULT_HOLIDAY_LIGHTING_ENABLED = True
DEFAULT_HOLIDAY_DECORATIONS_ENABLED = True
DEFAULT_HOLIDAY_GLOBAL_LIGHTS = ["light.front_porch"]
DEFAULT_HOLIDAY_GLOBAL_DECORATIONS = []
DEFAULT_HOLIDAY_GLOBAL_LABEL = "holiday_lights"
DEFAULT_HOLIDAY_SUNSET_OFFSET_MIN = -30
DEFAULT_HOLIDAY_SUNRISE_OFFSET_MIN = 30
DEFAULT_HOLIDAY_HOME_STATE_ENTITY = "input_select.home_state"
DEFAULT_HOLIDAY_OFF_TRIGGER = "sleep"
DEFAULT_HOLIDAY_OFF_TIME = "23:00:00"
DEFAULT_HOLIDAY_RESPECT_PRESENCE_SIMULATION = True

# Dusk-to-Dawn Exterior Lighting defaults
DEFAULT_EXTERIOR_DUSK_TO_DAWN_ENABLED = True
DEFAULT_EXTERIOR_LIGHTS = ["light.front_porch"]
DEFAULT_EXTERIOR_ON_TRIGGER = "sunset"
DEFAULT_EXTERIOR_SUNSET_OFFSET_MIN = -30
DEFAULT_EXTERIOR_ON_TIME = "18:00:00"
DEFAULT_EXTERIOR_OFF_TRIGGER = "sunrise"
DEFAULT_EXTERIOR_SUNRISE_OFFSET_MIN = 30
DEFAULT_EXTERIOR_OFF_TIME = "06:00:00"
DEFAULT_EXTERIOR_BASELINE_KELVIN = 2000
DEFAULT_EXTERIOR_BASELINE_BRIGHTNESS_PCT = 100
DEFAULT_HOLIDAY_LATE_NIGHT_BEHAVIOR = "all_night"

DEFAULT_DECORATIONS_ON_TRIGGER = "sunset"
DEFAULT_DECORATIONS_SUNSET_OFFSET_MIN = 0
DEFAULT_DECORATIONS_OFF_TRIGGER = "sleep"
DEFAULT_DECORATIONS_OFF_TIME = "23:00:00"

# Holiday Lighting modes & settings
MODE_HOLIDAY = "holiday"
MODE_EXTERIOR_BASELINE = "exterior_baseline"
LIGHT_MODE_HUE_SCENE = "hue_scene"
LIGHT_MODE_EFFECT = "effect"
LIGHT_MODE_RGB = "rgb"
LIGHT_MODE_COLOR_TEMP = "color_temp"
LIGHT_MODES = [LIGHT_MODE_HUE_SCENE, LIGHT_MODE_EFFECT, LIGHT_MODE_RGB, LIGHT_MODE_COLOR_TEMP]

# Holiday Lighting entity IDs & unique IDs
HOLIDAY_LIGHTING_MASTER_SWITCH_ENTITY_ID = "switch.holiday_lighting"
HOLIDAY_LIGHTING_MASTER_SWITCH_UNIQUE_ID = "passable_holiday_lighting_master"
HOLIDAY_DECORATIONS_SWITCH_ENTITY_ID = "switch.holiday_decorations"
HOLIDAY_DECORATIONS_SWITCH_UNIQUE_ID = "passable_holiday_decorations_switch"
EXTERIOR_LIGHTING_SWITCH_ENTITY_ID = "switch.exterior_dusk_to_dawn_lighting"
EXTERIOR_LIGHTING_SWITCH_UNIQUE_ID = "passable_exterior_lighting_switch"
ACTIVE_HOLIDAY_SENSOR_ENTITY_ID = "sensor.active_holiday"
ACTIVE_HOLIDAY_SENSOR_UNIQUE_ID = "passable_active_holiday"

# Holiday Lighting storage
HOLIDAY_STORAGE_KEY = f"{DOMAIN}_holidays"
HOLIDAY_STORAGE_VERSION = 1

# Holiday Lighting services
SERVICE_APPLY_HOLIDAY_LIGHTING = "apply_holiday_lighting"
SERVICE_PREVIEW_HOLIDAY = "preview_holiday"
ATTR_HOLIDAY_NAME = "holiday_name"
ATTR_DURATION_SEC = "duration_sec"

# Default Holiday Catalog
DEFAULT_HOLIDAYS = {
    "halloween": {
        "id": "halloween",
        "name": "Halloween",
        "enabled": True,
        "start_date": "10-01",
        "end_date": "10-31",
        "icon": "mdi:ghost",
        "phrase": "Spooky Season is Here!",
        "theme_color": "#9c4600",
        "rgb_color": [156, 70, 0],
        "color_temp_kelvin": 2000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_HUE_SCENE,
        "hue_scene": "scene.front_porch_spooky",
        "dynamic_scene": True,
        "fallback_effect": "fire",
        "decorations_on": True,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "christmas": {
        "id": "christmas",
        "name": "Christmas",
        "enabled": True,
        "start_date": "12-01",
        "end_date": "12-25",
        "icon": "mdi:pine-tree",
        "phrase": "Merry Christmas!",
        "theme_color": "#2e5c3e",
        "rgb_color": [46, 92, 62],
        "color_temp_kelvin": 2000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_HUE_SCENE,
        "hue_scene": "scene.front_porch_christmas",
        "dynamic_scene": True,
        "fallback_effect": "prism",
        "decorations_on": True,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "thanksgiving": {
        "id": "thanksgiving",
        "name": "Thanksgiving",
        "enabled": True,
        "start_date": "11-15",
        "end_date": "11-30",
        "icon": "mdi:turkey",
        "phrase": "Happy Thanksgiving!",
        "theme_color": "#b45f06",
        "rgb_color": [255, 140, 0],
        "color_temp_kelvin": 2200,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": True,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "new_years_eve": {
        "id": "new_years_eve",
        "name": "New Year's Eve",
        "enabled": True,
        "start_date": "12-31",
        "end_date": "01-01",
        "icon": "mdi:party-popper",
        "phrase": "Happy New Year!",
        "theme_color": "#FFD700",
        "rgb_color": [255, 215, 0],
        "color_temp_kelvin": 2500,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": True,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "july_4th": {
        "id": "july_4th",
        "name": "July 4th",
        "enabled": True,
        "start_date": "07-01",
        "end_date": "07-05",
        "icon": "mdi:firework",
        "phrase": "Happy Independence Day!",
        "theme_color": "#1a3a6e",
        "rgb_color": [26, 58, 110],
        "color_temp_kelvin": 3000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": False,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "memorial_day": {
        "id": "memorial_day",
        "name": "Memorial Day",
        "enabled": True,
        "start_date": "05-24",
        "end_date": "05-31",
        "icon": "mdi:flag-variant",
        "phrase": "Honoring Our Heroes",
        "theme_color": "#1a3a6e",
        "rgb_color": [26, 58, 110],
        "color_temp_kelvin": 3000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": False,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "labor_day": {
        "id": "labor_day",
        "name": "Labor Day",
        "enabled": True,
        "start_date": "09-01",
        "end_date": "09-07",
        "icon": "mdi:flag-variant",
        "phrase": "Happy Labor Day!",
        "theme_color": "#1a3a6e",
        "rgb_color": [26, 58, 110],
        "color_temp_kelvin": 3000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": False,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "valentines_day": {
        "id": "valentines_day",
        "name": "Valentine's Day",
        "enabled": True,
        "start_date": "02-07",
        "end_date": "02-14",
        "icon": "mdi:heart-multiple",
        "phrase": "Love is in the Air!",
        "theme_color": "#8a1c2e",
        "rgb_color": [138, 28, 46],
        "color_temp_kelvin": 2200,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": False,
        "participating_lights": [],
        "participating_decorations": [],
    },
    "st_patricks_day": {
        "id": "st_patricks_day",
        "name": "St. Patrick's Day",
        "enabled": True,
        "start_date": "03-10",
        "end_date": "03-17",
        "icon": "mdi:clover",
        "phrase": "Feeling Lucky?",
        "theme_color": "#51f569",
        "rgb_color": [81, 245, 105],
        "color_temp_kelvin": 3000,
        "brightness_pct": 100,
        "light_mode": LIGHT_MODE_RGB,
        "hue_scene": "",
        "dynamic_scene": False,
        "fallback_effect": "",
        "decorations_on": False,
        "participating_lights": [],
        "participating_decorations": [],
    },
}

