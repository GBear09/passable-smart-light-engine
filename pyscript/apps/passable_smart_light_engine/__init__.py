import json
import time
import math
import os
import pathlib
import copy

# ==========================================
# GLOBAL STATE & CONSTANTS
# ==========================================
# Global dictionary to store the AI learning data for all rooms in memory.
LEARNING_DATA = {"user_prefs": {}, "room_curves": {}, "media_prefs": {}, "late_night_prefs": {}}

# Global dictionary to store recent lux readings per room for spike filtering.
LUX_HISTORY = {}

# Minimum brightness percentage that produces visible light output.
MIN_VISIBLE_PCT = 5

# Path to the JSON file where learning data will be persisted across HA restarts
DATA_FILE = "/config/pyscript/apps/passable_smart_light_engine/learning_data.json"
LEGACY_DATA_FILE = "/config/pyscript/apps/smart_light_engine/learning_data.json"

# States that represent an entity being "active" or "on"
ACTIVE_STATES = ["on", "playing", "true", "home", "paused", "idle", "standby", "buffering"]


def safe_get_state(entity_id, default=0):
    """
    Safely fetches a state from Home Assistant.
    Prevents exceptions if an entity doesn't exist yet, is unavailable, or if Pyscript is still loading.
    """
    try:
        if "." in entity_id and len(entity_id.split(".")) == 3:
            domain, entity, attr = entity_id.split(".")
            attrs = state.getattr(f"{domain}.{entity}")
            if attrs is not None and attr in attrs:
                val = attrs[attr]
                if val is not None and val not in ["unknown", "unavailable"]:
                    return val
            return default

        val = state.get(entity_id)
        if val is not None and val not in ["unknown", "unavailable"]:
            return val
        return default
    except Exception:
        return default

def get_smoothed_lux(room_id, lux_sensor, max_readings=5):
    """
    Returns a spike-resistant lux reading by maintaining a short history of recent
    sensor values and returning the median.
    """
    global LUX_HISTORY
    if room_id not in LUX_HISTORY:
        LUX_HISTORY[room_id] = []

    current_raw = float(safe_get_state(lux_sensor, 0))
    now = time.time()

    LUX_HISTORY[room_id].append((now, current_raw))

    if len(LUX_HISTORY[room_id]) > max_readings:
        LUX_HISTORY[room_id] = LUX_HISTORY[room_id][-max_readings:]

    cutoff = now - 1800
    LUX_HISTORY[room_id] = [(t, v) for t, v in LUX_HISTORY[room_id] if t >= cutoff]

    if not LUX_HISTORY[room_id]:
        return current_raw

    values = sorted([v for _, v in LUX_HISTORY[room_id]])
    mid = len(values) // 2
    if len(values) % 2 == 0 and len(values) > 1:
        return (values[mid - 1] + values[mid]) / 2.0
    return values[mid]

def parse_entity_list(raw_input):
    """Safely unpacks list strings passed from Home Assistant Blueprints."""
    if not raw_input: return []
    if isinstance(raw_input, list): return raw_input
    if isinstance(raw_input, str):
        raw_str = raw_input.strip()
        if raw_str.startswith("[") and raw_str.endswith("]"):
            raw_str = raw_str[1:-1] 
            ents = []
            for x in raw_str.split(","):
                cleaned = x.strip().strip("'").strip('"')
                if cleaned: ents.append(cleaned)
            return ents
        if "," in raw_str:
            return [x.strip() for x in raw_str.split(",")]
        return [raw_str]
    return []

def get_expected_lux(curve, pct, default_ratio=1.0):
    """Interpolates the expected lux yield for a given brightness percentage."""
    if pct <= 0: return 0.0
    if not curve: return float(pct) * float(default_ratio)
    points = sorted([(int(k), float(v)) for k, v in curve.items()])
    if not points: return float(pct) * float(default_ratio)

    if points[0][0] > 0 and pct <= points[0][0]:
        return (points[0][1] / points[0][0]) * pct
    elif points[0][0] == 0 and pct <= points[0][0]:
        return points[0][1]

    if points[-1][0] > 0 and pct >= points[-1][0]:
        return (points[-1][1] / points[-1][0]) * pct

    for i in range(len(points) - 1):
        p1_pct, p1_lux = points[i]
        p2_pct, p2_lux = points[i+1]
        if p1_pct <= pct <= p2_pct:
            progress = (pct - p1_pct) / (p2_pct - p1_pct) if p2_pct != p1_pct else 0
            return p1_lux + ((p2_lux - p1_lux) * progress)
    return float(pct) * float(default_ratio)

def get_pct_for_lux(curve, target_artificial_lux, default_ratio=1.0):
    """Finds the required brightness percentage to hit a target artificial lux."""
    if target_artificial_lux <= 0: return 0
    if not curve: return min(100, int(target_artificial_lux / float(default_ratio)))
    points = sorted([(int(k), float(v)) for k, v in curve.items()])
    if not points: return min(100, int(target_artificial_lux / float(default_ratio)))

    if points[0][1] > 0 and target_artificial_lux <= points[0][1]:
        return int((target_artificial_lux / points[0][1]) * points[0][0])
    elif points[0][1] == 0 and target_artificial_lux <= points[0][1]:
        return points[0][0]

    if points[-1][1] > 0 and target_artificial_lux >= points[-1][1]:
        pct = (target_artificial_lux / points[-1][1]) * points[-1][0]
        return min(100, int(pct))

    for i in range(len(points) - 1):
        p1_pct, p1_lux = points[i]
        p2_pct, p2_lux = points[i+1]
        if p1_lux <= target_artificial_lux <= p2_lux and p1_lux != p2_lux:
            progress = (target_artificial_lux - p1_lux) / (p2_lux - p1_lux)
            return int(p1_pct + ((p2_pct - p1_pct) * progress))
    return 100

# ==========================================
# INITIALIZATION & STATE PERSISTENCE
# ==========================================
@time_trigger("startup")
def load_data():
    """Loads saved AI learning data into global memory dictionary."""
    global LEARNING_DATA
    try:
        target_file = DATA_FILE
        if not task.executor(os.path.exists, target_file) or task.executor(os.path.getsize, target_file) < 150:
            if task.executor(os.path.exists, LEGACY_DATA_FILE):
                target_file = LEGACY_DATA_FILE

        if task.executor(os.path.exists, target_file):
            p = pathlib.Path(target_file)
            data_str = task.executor(p.read_text)
            if data_str:
                loaded = json.loads(data_str)
                for k in LEARNING_DATA:
                    if k in loaded: 
                        LEARNING_DATA[k] = loaded[k]
                log.info(f"PassableSmartLighting: Loaded learning data from {target_file} for {len(LEARNING_DATA.get('user_prefs', {}))} rooms.")
        else:
            log.info("PassableSmartLighting: No existing JSON data found. Starting fresh.")
    except Exception as e:
        log.warning(f"PassableSmartLighting: Failed to load JSON data. ({e})")

    # Announce that Pyscript has loaded and sync active room state attributes
    sync_active_rooms_state()

def sync_active_rooms_state():
    """
    Exposes active rooms and their non-empty dataset keys as state attributes on Pyscript status entities.
    Enables zero-helper dynamic dashboard popups to auto-populate room and dataset reset options.
    """
    try:
        room_datasets = {}
        for category_key, category_dict in LEARNING_DATA.items():
            if isinstance(category_dict, dict):
                for rid, data in category_dict.items():
                    if data:
                        if rid not in room_datasets:
                            room_datasets[rid] = []
                        room_datasets[rid].append(category_key)
        
        active_rooms = sorted(list(room_datasets.keys()))
        reset_types = ["all", "user_prefs", "room_curves", "media_prefs", "late_night_prefs"]
        
        attrs = {
            "startup_time": time.time(),
            "active_rooms": active_rooms,
            "room_datasets": room_datasets,
            "available_reset_types": reset_types
        }
        
        state.set("pyscript.passable_smart_light_engine_ready", "on", new_attributes=attrs)
        state.set("pyscript.smart_light_engine_ready", "on", new_attributes=attrs)
    except Exception as e:
        log.warning(f"PassableSmartLighting: Failed to sync active room state attributes. ({e})")

def save_data():
    """Saves LEARNING_DATA snapshot to JSON file."""
    try:
        p = pathlib.Path(DATA_FILE)
        task.executor(p.parent.mkdir, parents=True, exist_ok=True)
        data_copy = copy.deepcopy(LEARNING_DATA)
        data_str = json.dumps(data_copy, indent=4)
        task.executor(p.write_text, data_str)
        log.info("PassableSmartLighting: 💾 Successfully saved updated AI preferences to JSON.")
        sync_active_rooms_state()
    except Exception as e:
        log.error(f"PassableSmartLighting: Failed to save JSON data - {e}")

def get_circadian_temp(min_temp=2700, max_temp=5500):
    """Calculates color temperature (Kelvin) based on sun elevation."""
    try:
        sun_attrs = state.getattr("sun.sun")
        elev = float(sun_attrs.get("elevation", 0)) if sun_attrs else 0
    except Exception: elev = 0
    
    elev_clamped = max(-10.0, min(50.0, elev))
    pct = (elev_clamped + 10.0) / 60.0
    temp = min_temp + (pct * (max_temp - min_temp))
    return max(2000, min(6500, int(temp)))

# ==========================================
# MAIN SMART LIGHT ENGINE (SERVICE & EVENT)
# ==========================================
@event_trigger("passable_smart_light_engine_event")
@event_trigger("smart_light_engine_event")  # Legacy event trigger alias
def passable_smart_light_engine_event_wrapper(trigger_type=None, event_type=None, context=None, **kwargs):
    """
    Wrapper to allow the blueprint to fire an event instead of a service call.
    Supports both passable_smart_light_engine_event and legacy smart_light_engine_event.
    """
    passable_smart_light_engine(**kwargs)

@service
def smart_light_engine(**kwargs):
    """Legacy service alias for backward compatibility with existing automations."""
    passable_smart_light_engine(**kwargs)

@service
def passable_smart_light_engine(
    trigger_id=None, trigger_to_state=None, trigger_context_id=None, 
    trigger_user_id=None, trigger_from_state=None, trigger_from_brightness=0,
    room_id=None, presence_entity=None, light_entity=None, lux_sensor=None, 
    target_lux=None, default_lux_ratio=1.0, presence_timeout_min=None, 
    override_timeout_min=None, circadian_enabled=True, min_color_temp=2700, 
    max_color_temp=5500, media_entities=None, media_seed_pct=None, 
    bypass_freeze_entities=None, bypass_off_entities=None, manual_override_entity=None, 
    ignore_max_brightness_override=True, late_night_enabled=True, late_night_pct=0, 
    late_night_condition_type="time", late_night_entity=None,
    late_night_start_time="22:00:00", late_night_start_entity=None, 
    late_night_stop_time="06:00:00", late_night_stop_entity=None,
    **kwargs
):
    """
    The core control logic. Called by Home Assistant Blueprint events.
    """
    if not room_id: return
    log.info(f"PassableSmartLighting [{room_id}]: Engine triggered by '{trigger_id}'")
    
    global LEARNING_DATA
    for key in ["user_prefs", "room_curves", "media_prefs", "late_night_prefs"]:
        if room_id not in LEARNING_DATA[key]: 
            LEARNING_DATA[key][room_id] = [] if "prefs" in key else {}

    def is_late_night():
        if str(late_night_enabled).lower() not in ["true", "on"]: return False
        if late_night_condition_type == "entity_state":
            if late_night_entity and str(late_night_entity).lower() not in ["none", ""]:
                return safe_get_state(late_night_entity, "off") in ACTIVE_STATES
            return False

        s_ent = str(late_night_start_entity)
        start_str = safe_get_state(s_ent, late_night_start_time) if s_ent and s_ent.lower() not in ["none", ""] else late_night_start_time
        e_ent = str(late_night_stop_entity)
        stop_str = safe_get_state(e_ent, late_night_stop_time) if e_ent and e_ent.lower() not in ["none", ""] else late_night_stop_time
        try:
            start_clean = str(start_str).split(" ")[1] if " " in str(start_str) else str(start_str)
            stop_clean = str(stop_str).split(" ")[1] if " " in str(stop_str) else str(stop_str)

            now_str = time.strftime("%H:%M")
            st, sp = start_clean[:5], stop_clean[:5]
            if st < sp: return st <= now_str <= sp
            else: return st <= now_str or now_str <= sp
        except Exception: return False

    late_night_active = is_late_night()

    def mark_auto_action(t_duration=0, start_pct=0, target_pct=None):
        now = time.time()
        state.set(f"pyscript.last_auto_{room_id}", str(now + t_duration))
        state.set(f"pyscript.last_auto_ts_{room_id}", str(now))
        state.set(f"pyscript.last_auto_duration_{room_id}", str(t_duration))
        if target_pct is not None:
            state.set(f"pyscript.last_target_pct_{room_id}", str(target_pct))
            state.set(f"pyscript.last_start_pct_{room_id}", str(start_pct))

    def enforce_monotonic_curve(curve):
        if not curve: return curve
        points = sorted([(int(k), float(v)) for k, v in curve.items()])
        cleaned = {}
        max_lux = -1.0
        for p, lux in points:
            if lux > max_lux:
                cleaned[str(p)] = lux
                max_lux = lux
        return cleaned

    def auto_calibrate_task(r_id, l_ent, lux_sens, from_pct, pct_target, duration):
        task.unique(f"sl_auto_cal_{r_id}")
        try:
            sun_attrs = state.getattr("sun.sun")
            elev = float(sun_attrs.get("elevation", 0)) if sun_attrs else 0
            if elev >= 0: return 
            
            lux_before = float(safe_get_state(lux_sens, 0))

            curve = LEARNING_DATA["room_curves"].get(r_id, {})
            expected_lux_before = get_expected_lux(curve, from_pct, float(default_lux_ratio))
            expected_lux_after = get_expected_lux(curve, pct_target, float(default_lux_ratio))
            expected_delta = expected_lux_after - expected_lux_before
            
            task.sleep(duration + 2)

            try:
                current_lux_str = str(safe_get_state(lux_sens, 0))
                log.info(f"PassableSmartLighting [{r_id}]: Fade finished. Waiting for final Lux report...")
                task.wait_until(state_trigger=f"{lux_sens} != '{current_lux_str}'", timeout=120)
            except task.TimeoutError:
                log.warning(f"PassableSmartLighting [{r_id}]: Lux sensor timed out after fade. Using current reading.")

            current_bright_val = safe_get_state(f"{l_ent}.brightness", 0)
            current_pct = int((float(current_bright_val) / 255) * 100) if current_bright_val else 0

            if abs(current_pct - pct_target) > 5 or current_pct < 20 or current_pct == 0: return

            lux_after = float(safe_get_state(lux_sens, 0))
            actual_delta = lux_after - lux_before

            if (pct_target > from_pct and actual_delta > 0) or (pct_target < from_pct and actual_delta < 0) or (from_pct == 0 and actual_delta > 0):
                if from_pct == 0:
                    new_yield = actual_delta
                else:
                    new_yield = expected_lux_after + (actual_delta - expected_delta)
                    
                if new_yield > 0:
                    cur_avg = LEARNING_DATA["room_curves"][r_id].get(str(pct_target))
                    if cur_avg is None:
                        LEARNING_DATA["room_curves"][r_id][str(pct_target)] = new_yield
                    else:
                        LEARNING_DATA["room_curves"][r_id][str(pct_target)] = (cur_avg * 0.8) + (new_yield * 0.2)
                    
                    LEARNING_DATA["room_curves"][r_id] = enforce_monotonic_curve(LEARNING_DATA["room_curves"][r_id])
                    save_data()
        finally:
            state.set(f"pyscript.sensor_stale_{r_id}", "false")

    def turn_on_light(pct, transition_time=None):
        if int(pct) == 0:
            turn_off_light(transition_time or 5)
            return

        current_bright_val = safe_get_state(f"{light_entity}.brightness", 0)
        from_pct = int((float(current_bright_val) / 255) * 100) if current_bright_val else 0
        was_off = from_pct == 0

        t_time = 1 if was_off else (transition_time if transition_time is not None else 5)
        mark_auto_action(t_time, start_pct=from_pct, target_pct=int(pct)) 

        payload = {"entity_id": light_entity, "brightness_pct": int(pct)}
        
        if str(circadian_enabled).lower() in ["true", "on"]:
            attrs = state.getattr(light_entity) or {}
            if isinstance(attrs, dict) and "color_temp" in attrs.get("supported_color_modes", []):
                payload["color_temp_kelvin"] = get_circadian_temp(float(min_color_temp), float(max_color_temp))
        
        payload["transition"] = t_time
        light.turn_on(**payload)
        
        if pct > 0:
            state.set(f"pyscript.sensor_stale_{room_id}", "true")
            task.create(auto_calibrate_task, room_id, light_entity, lux_sensor, from_pct, int(pct), t_time)

    def turn_off_light(transition_time=5):
        current_bright_val = safe_get_state(f"{light_entity}.brightness", 0)
        from_pct = int((float(current_bright_val) / 255) * 100) if current_bright_val else 0
        mark_auto_action(transition_time, start_pct=from_pct, target_pct=0)
        state.set(f"pyscript.sensor_stale_{room_id}", "false")
        light.turn_off(entity_id=light_entity, transition=transition_time)

    def async_set_override(entity, state_str):
        domain = entity.split(".")[0]
        if domain == "input_boolean":
            if state_str == "on": input_boolean.turn_on(entity_id=entity)
            else: input_boolean.turn_off(entity_id=entity)
        else: state.set(entity, state_str)

    def set_manual_override(state_str):
        if not manual_override_entity: return
        task.create(async_set_override, manual_override_entity, state_str)

    # ==========================================
    # OVERRIDE & BYPASS CHECKS
    # ==========================================
    override_key = f"pyscript.override_{room_id}"
    override_time = float(safe_get_state(override_key, 0))
    manual_off_key = f"pyscript.manual_off_{room_id}"
    manual_off_time = float(safe_get_state(manual_off_key, 0))

    if trigger_id == "light_change":
        current_bright_val = safe_get_state(f"{light_entity}.brightness", 0)
        is_off = (trigger_to_state == "off") or (not current_bright_val)
        if is_off:
            state.set(override_key, "0")
            state.set(f"pyscript.sensor_stale_{room_id}", "false")
            if manual_override_entity:
                async_set_override(manual_override_entity, "off")
            
            try: timeout_m = float(presence_timeout_min or 5.0)
            except (ValueError, TypeError): timeout_m = 5.0
            state.set(manual_off_key, str(time.time() + (timeout_m * 60)))
            return

    if manual_override_entity and trigger_id != "override_change":
        ui_state = safe_get_state(manual_override_entity, "off")
        is_expired = (override_time > 0 and override_time < time.time())
        is_stuck_on = (override_time == 0 and ui_state == "on")
        if is_expired or is_stuck_on:
            if ui_state == "on": async_set_override(manual_override_entity, "off")
            state.set(override_key, "0")
            override_time = 0

    if bypass_off_entities:
        for entity in parse_entity_list(bypass_off_entities):
            if safe_get_state(entity, "off") in ACTIVE_STATES:
                if safe_get_state(light_entity, "off") != "off": turn_off_light(5)
                return

    if bypass_freeze_entities:
        for entity in parse_entity_list(bypass_freeze_entities):
            if manual_override_entity and entity == manual_override_entity:
                if override_time <= time.time() or trigger_id == "presence_off_timeout":
                    continue
            if safe_get_state(entity, "off") in ACTIVE_STATES: return

    presence_active = False
    if presence_entity:
        for entity in parse_entity_list(presence_entity):
            if safe_get_state(entity, "off") == "on":
                presence_active = True
                break

    media_active = False
    if media_entities:
        for entity in parse_entity_list(media_entities):
            if safe_get_state(entity, "off") in ACTIVE_STATES:
                media_active = True
                break

    # ==========================================
    # CORE ALGORITHM: UNIFIED EVALUATION
    # ==========================================
    eval_triggers = ["presence_on", "media_change", "lux_change", "bypass_change", "heartbeat"]
    if trigger_id in eval_triggers:
        if safe_get_state(light_entity, "off") == "on" and safe_get_state(f"pyscript.sensor_stale_{room_id}", "false") == "true":
            last_auto_ts = float(safe_get_state(f"pyscript.last_auto_ts_{room_id}", 0))
            if trigger_id == "lux_change":
                task.sleep(2)
                state.set(f"pyscript.sensor_stale_{room_id}", "false")
            elif time.time() - last_auto_ts > 15:
                state.set(f"pyscript.sensor_stale_{room_id}", "false")
            else:
                return

        if manual_off_time > time.time():
            if presence_active and trigger_id == "presence_on":
                state.set(manual_off_key, "0")
            elif safe_get_state(light_entity, "off") == "on":
                pass
            else:
                return

        if trigger_id == "lux_change":
            last_auto_end = float(safe_get_state(f"pyscript.last_auto_{room_id}", 0))
            if time.time() - last_auto_end < 15:
                return
                
        if override_time > time.time(): return 

        is_light_on = safe_get_state(light_entity, "off") == "on"

        if not (presence_active or media_active or is_light_on) and trigger_id != "presence_on":
            return

        current_bright_val = safe_get_state(f"{light_entity}.brightness", 0)
        current_pct = int((float(current_bright_val) / 255) * 100) if current_bright_val else 0

        # SCENARIO A: Media Active
        if media_active:
            current_lux = get_smoothed_lux(room_id, lux_sensor)

            prefs = LEARNING_DATA["media_prefs"][room_id]
            seed_target = float(media_seed_pct or 20)
            if prefs:
                sorted_prefs = sorted(prefs)
                median = sorted_prefs[len(sorted_prefs) // 2]
                n_count = len(prefs)
                w_learned = min(1.0, n_count / 10.0)
                target_pct = (seed_target * (1.0 - w_learned)) + (median * w_learned)
            else:
                target_pct = seed_target
            target_pct = min(100, max(0, int(target_pct)))

            curve = LEARNING_DATA["room_curves"][room_id]
            media_target_lux = get_expected_lux(curve, target_pct, default_lux_ratio)

            if current_pct == 0 and current_lux >= (media_target_lux + 3.0):
                return

            if abs(target_pct - current_pct) > 5 or trigger_id == "media_change":
                turn_on_light(target_pct, transition_time=15)
                
        # SCENARIO B: Late Night Active
        elif late_night_active:
            if not (presence_active or media_active):
                if safe_get_state(light_entity, "off") != "off": turn_off_light(15)
            elif int(late_night_pct or 0) == 0:
                if safe_get_state(light_entity, "off") != "off": turn_off_light(5)
            else:
                prefs = LEARNING_DATA["late_night_prefs"][room_id]
                seed_target = float(late_night_pct)
                if prefs:
                    sorted_prefs = sorted(prefs)
                    median = sorted_prefs[len(sorted_prefs) // 2]
                    n_count = len(prefs)
                    w_learned = min(1.0, n_count / 10.0)
                    target_pct = (seed_target * (1.0 - w_learned)) + (median * w_learned)
                else:
                    target_pct = seed_target
                if abs(target_pct - current_pct) > 5 or trigger_id == "presence_on":
                    turn_on_light(target_pct, transition_time=15)
                
        # SCENARIO C: Standard Daytime Logic
        else:
            current_lux = get_smoothed_lux(room_id, lux_sensor)
            seed_target_lux = float(target_lux or 40)
            try:
                sun_attrs = state.getattr("sun.sun")
                elev = float(sun_attrs.get("elevation", 0)) if sun_attrs else 0
            except Exception: elev = 0

            prefs = LEARNING_DATA["user_prefs"][room_id]
            active_target_lux = seed_target_lux
            if prefs:
                total_w, weighted_lux = 0, 0
                for p in prefs:
                    w = math.exp(-abs(p.get("sun_elev", 0) - elev) / 10)
                    weighted_lux += p.get("preferred_lux", 0) * w
                    total_w += w
                if total_w > 0:
                    learned_lux = weighted_lux / total_w
                    n_count = len(prefs)
                    w_learned = min(1.0, n_count / 10.0)
                    active_target_lux = (seed_target_lux * (1.0 - w_learned)) + (learned_lux * w_learned)

            naturally_bright = current_pct == 0 and current_lux >= active_target_lux
            lux_gap = active_target_lux - current_lux

            deadband = 3 if trigger_id == "presence_on" else 5
            if abs(lux_gap) > deadband or (current_pct == 0 and lux_gap > 0):
                curve = LEARNING_DATA["room_curves"][room_id]
                current_artificial_lux = get_expected_lux(curve, current_pct, default_lux_ratio)

                k_p = 1.0 if trigger_id in ["presence_on", "media_change"] else 0.5
                needed_artificial_lux = current_artificial_lux + (lux_gap * k_p)

                calc_pct = get_pct_for_lux(curve, needed_artificial_lux, default_lux_ratio)
                target_pct = min(100, max(0, int(calc_pct)))

                if 0 < target_pct < MIN_VISIBLE_PCT:
                    target_pct = MIN_VISIBLE_PCT

                ambient_estimate = current_lux - current_artificial_lux
                if target_pct == 0 and ambient_estimate < active_target_lux and presence_active:
                    target_pct = MIN_VISIBLE_PCT

                if naturally_bright and target_pct > 0 and trigger_id != "presence_on":
                    return

                if abs(target_pct - current_pct) >= 2 or (current_pct == 0 and target_pct > 0):
                    turn_on_light(target_pct, transition_time=10)

    # ------------------------------------------
    # PATH 2: PRESENCE VACANCY TIMEOUT
    # ------------------------------------------
    elif trigger_id == "presence_off_timeout":
        log.info(f"PassableSmartLighting [{room_id}]: Presence Timeout Fired.")
        if media_active: return
        
        state.set(manual_off_key, "0")

        if override_time <= time.time():
            state.set(override_key, "0")
            set_manual_override("off")
            turn_off_light(5)
        else:
            log.info(f"PassableSmartLighting [{room_id}]: Vacancy timeout ignored — manual override still active.")

    # ------------------------------------------
    # PATH 3: LIGHT STATE CHANGES (The Override & Learning Engine)
    # ------------------------------------------
    elif trigger_id == "light_change":
        current_bright_val = safe_get_state(f"{light_entity}.brightness", 0)
        current_pct = int((float(current_bright_val) / 255) * 100) if current_bright_val else 0

        uid = str(trigger_user_id or "").strip().lower()
        pid = str(trigger_context_id or "").strip().lower()
        _null = ("", "none", "null")

        is_ui_manual = uid not in _null
        is_physical  = uid in _null and pid in _null

        # Trajectory-bounded automation echo guard with 30s grace window
        last_auto_end = float(safe_get_state(f"pyscript.last_auto_{room_id}", 0))
        last_target_pct = safe_get_state(f"pyscript.last_target_pct_{room_id}", None)
        last_start_pct = safe_get_state(f"pyscript.last_start_pct_{room_id}", None)

        within_grace_period = time.time() <= (last_auto_end + 30)

        is_pct_match = False
        if within_grace_period and last_target_pct is not None and str(last_target_pct).lower() not in ["none", "unknown"]:
            try:
                # 8% tolerance accounts for hardware dimming curve & quantization rounding
                is_pct_match = abs(current_pct - int(float(last_target_pct))) <= 8
            except (ValueError, TypeError):
                is_pct_match = False

        is_in_fade_trajectory = False
        if within_grace_period and last_start_pct is not None and last_target_pct is not None:
            try:
                s_pct = int(float(last_start_pct))
                t_pct = int(float(last_target_pct))
                min_p, max_p = min(s_pct, t_pct), max(s_pct, t_pct)
                is_in_fade_trajectory = (min_p <= current_pct <= max_p)
            except (ValueError, TypeError):
                is_in_fade_trajectory = False

        is_auto_echo = is_in_fade_trajectory or is_pct_match

        try:
            if str(trigger_from_brightness).lower() == "none":
                from_pct = current_pct
            else:
                from_pct = int((float(trigger_from_brightness) / 255) * 100)
        except (ValueError, TypeError):
            from_pct = current_pct

        is_device_echo = is_physical and abs(current_pct - from_pct) <= 3
        is_reconnect = trigger_from_state in ["unavailable", "unknown", "none"]

        is_manual = (is_ui_manual or is_physical) and not is_auto_echo and not is_device_echo and not is_reconnect

        if not is_manual:
            log.debug(
                f"PassableSmartLighting [{room_id}]: Ignored — "
                f"{'device confirmation echo' if is_device_echo else 'automation echo' if is_auto_echo else 'automation-triggered'} "
                f"(uid={uid or 'null'}, pid={pid or 'null'}, "
                f"current={current_pct}%)"
            )
            return

        source = "UI/dashboard" if is_ui_manual else "physical switch"
        log.info(f"PassableSmartLighting [{room_id}]: ✅ Manual override detected via {source} at {current_pct}%")

        skip_override_timer = False
        if str(ignore_max_brightness_override).lower() in ["true", "on"]:
            was_off = trigger_from_state == "off" or from_pct == 0
            is_max = current_pct >= 95
            if was_off and is_max:
                log.info(f"PassableSmartLighting [{room_id}]: Max brightness from off — skipping override timer per config.")
                skip_override_timer = True

        if not skip_override_timer:
            try:    timeout_val = float(override_timeout_min)
            except: timeout_val = 60.0
            state.set(override_key, str(time.time() + (timeout_val * 60)))
            set_manual_override("on")

        # AI LEARNING
        if media_active:
            def _save_media():
                task.unique(f"sl_save_media_{room_id}")
                if current_pct >= 95 and int(media_seed_pct or 20) < 50:
                    log.info(f"PassableSmartLighting [{room_id}]: Rejecting media learning — {current_pct}% is too far from seed {media_seed_pct}%")
                    return
                LEARNING_DATA["media_prefs"][room_id].append(current_pct)
                if len(LEARNING_DATA["media_prefs"][room_id]) > 20:
                    LEARNING_DATA["media_prefs"][room_id].pop(0)
                save_data()
            task.create(_save_media)

        elif late_night_active:
            def _save_late_night():
                task.unique(f"sl_save_late_{room_id}")
                if current_pct >= 95 and int(late_night_pct or 0) < 50:
                    log.info(f"PassableSmartLighting [{room_id}]: Rejecting late-night learning — {current_pct}% is too far from seed {late_night_pct}%")
                    return
                LEARNING_DATA["late_night_prefs"][room_id].append(current_pct)
                if len(LEARNING_DATA["late_night_prefs"][room_id]) > 20:
                    LEARNING_DATA["late_night_prefs"][room_id].pop(0)
                save_data()
            task.create(_save_late_night)

        else:
            captured_pct = current_pct
            def _save_daytime():
                task.unique(f"sl_save_daytime_{room_id}")
                lux_before = float(safe_get_state(lux_sensor, 0))
                try:
                    current_lux_str = str(safe_get_state(lux_sensor, 0))
                    log.info(f"PassableSmartLighting [{room_id}]: ⏳ Waiting up to 120s for lux sensor to stabilize...")
                    task.wait_until(state_trigger=f"{lux_sensor} != '{current_lux_str}'", timeout=120)
                    lux_after = float(safe_get_state(lux_sensor, 0))

                    if lux_after <= 0:
                        log.warning(f"PassableSmartLighting [{room_id}]: Rejecting user pref — lux_after is {lux_after} (sensor may be dead)")
                        return

                    smoothed = get_smoothed_lux(room_id, lux_sensor)
                    if abs(lux_after - smoothed) > 20:
                        log.info(f"PassableSmartLighting [{room_id}]: Lux reading {lux_after} looks contaminated (smoothed={smoothed}). Using smoothed value.")
                        lux_after = smoothed

                    try:
                        sun_attrs = state.getattr("sun.sun")
                        elev = float(sun_attrs.get("elevation", 0)) if sun_attrs else 0
                    except Exception: elev = 0

                    curve = LEARNING_DATA["room_curves"].get(room_id, {})
                    ambient_est = max(0.0, lux_before - get_expected_lux(curve, from_pct, default_lux_ratio))
                    net_pref_lux = lux_after - ambient_est
                    target_save_lux = lux_after if net_pref_lux <= 0 else lux_after

                    LEARNING_DATA["user_prefs"][room_id].append({"sun_elev": elev, "preferred_lux": target_save_lux})
                    if len(LEARNING_DATA["user_prefs"][room_id]) > 50:
                        LEARNING_DATA["user_prefs"][room_id].pop(0)

                    save_data()

                except task.TimeoutError:
                    log.warning(f"PassableSmartLighting [{room_id}]: Lux sensor timed out. Discarding manual preference.")

            task.create(_save_daytime)

    # ------------------------------------------
    # PATH 4: MANUAL OVERRIDE DASHBOARD TOGGLE
    # ------------------------------------------
    elif trigger_id == "override_change":
        if safe_get_state(manual_override_entity, "off") == "on":
            try: timeout_val = float(override_timeout_min)
            except (ValueError, TypeError): timeout_val = 60.0
            state.set(override_key, str(time.time() + (timeout_val * 60)))
        else:
            if override_time > time.time(): state.set(override_key, "0")
            if not (presence_active or media_active):
                if safe_get_state(light_entity, "off") != "off":
                    turn_off_light(5)

# ==========================================
# LEARNING DATA MANAGEMENT SERVICE
# ==========================================
@service
def passable_smart_light_engine_reset(room_id=None, reset_type="all"):
    """
    Resets learning data for a specific room or all rooms.
    Call from HA Developer Tools → Services: pyscript.passable_smart_light_engine_reset
    """
    global LEARNING_DATA
    if not room_id:
        log.warning("PassableSmartLighting: Reset called without room_id — resetting ALL rooms.")
        targets = [reset_type] if reset_type != "all" else ["user_prefs", "room_curves", "media_prefs", "late_night_prefs"]
        for key in targets:
            if key in LEARNING_DATA:
                for rid in LEARNING_DATA[key]:
                    LEARNING_DATA[key][rid] = [] if "prefs" in key else {}
                log.info(f"PassableSmartLighting: 🗑️ Reset {key} for all rooms")
        save_data()
        return

    targets = [reset_type] if reset_type != "all" else ["user_prefs", "room_curves", "media_prefs", "late_night_prefs"]

    for key in targets:
        if key in LEARNING_DATA and room_id in LEARNING_DATA[key]:
            LEARNING_DATA[key][room_id] = [] if "prefs" in key else {}
            log.info(f"PassableSmartLighting [{room_id}]: 🗑️ Reset {key}")

    save_data()
    log.info(f"PassableSmartLighting [{room_id}]: Learning data reset complete ({reset_type}).")

@service
def smart_light_engine_reset(room_id=None, reset_type="all"):
    """Legacy reset service alias for existing automations/dashboards."""
    passable_smart_light_engine_reset(room_id=room_id, reset_type=reset_type)
