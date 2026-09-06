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
