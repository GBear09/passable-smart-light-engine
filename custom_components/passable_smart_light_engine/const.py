"""Constants for the Passable AI Smart Lighting Controller integration."""

DOMAIN = "passable_smart_light_engine"
LEGACY_DOMAIN = "smart_light_engine"

PLATFORMS = ["switch", "sensor", "binary_sensor", "number"]

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_learning_data"
LEGACY_DATA_PATHS = [
    "/config/pyscript/apps/smart_light_engine/learning_data.json",
    "/config/pyscript/apps/passable_smart_light_engine/learning_data.json",
]

# Configuration keys
CONF_ROOM_ID = "room_id"
CONF_LIGHT_ENTITY = "light_entity"
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

# Default values
DEFAULT_TARGET_LUX = 40
DEFAULT_LUX_RATIO = 1.0
DEFAULT_PRESENCE_TIMEOUT_MIN = 5
DEFAULT_MIN_OCCUPIED_PCT = 0

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

ACTIVE_STATES = ["on", "playing", "true", "home", "paused", "idle", "standby", "buffering"]

# Event names (for backward compatibility)
EVENT_SMART_LIGHT_ENGINE = "smart_light_engine_event"
EVENT_PASSABLE_SMART_LIGHT_ENGINE = "passable_smart_light_engine_event"

# Services
SERVICE_RESET_LEARNING_DATA = "reset_learning_data"
ATTR_RESET_ROOM_ID = "room_id"
ATTR_RESET_TYPE = "reset_type"
RESET_TYPES = ["all", "user_prefs", "room_curves", "media_prefs", "late_night_prefs"]
