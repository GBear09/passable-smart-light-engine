# 🧠 Passable AI Smart Lighting Controller

An adaptive, machine-learning-inspired lighting automation system for Home Assistant. Combines a user-friendly frontend **Blueprint** with a high-performance **Pyscript** backend engine.

---

## ⚙️ Key Features

- **📈 Adaptive Lux Yield Curve Learning:** Calculates how much ambient lux each 1% of brightness produces in your specific room, adjusting dimmer levels smoothly to maintain your target lux.
- **🎓 Dual-Track Preference Learning:** Learns your personal brightness preferences based on sun elevation whenever you manually override the lights.
- **⏱️ Sensor Lag Compensation:** Asynchronously waits for slow sensors (e.g., Philips Hue, Zigbee motion/illuminance sensors) to report final lux values before saving preference data.
- **🛡️ Trajectory-Bounded Echo Guard:** Intelligent detection to prevent delayed hardware status updates or multi-bulb group state updates from causing false manual override triggers (with a 30s grace window and 8% quantization tolerance).
- **☀️ Sun-Based Circadian Rhythm:** Dynamically shifts color temperature between configured warm and cool Kelvin values based on sun elevation throughout the day.
- **📺 Media Player Integration:** Automatically applies learned TV/media lighting presets when media players are active.
- **🌙 Late Night Mode:** Overrides sun-based targeting during night hours with configurable start/stop times or helper entity triggers.
- **🛑 Flexible Bypasses & Overrides:** Support for Freeze Bypasses (stay as-is), Force-Off Bypasses (e.g., Away mode), and customizable manual override timeouts.
- **🧹 Dynamic Active Rooms State Sync:** Publishes `active_rooms` and `available_reset_types` state attributes to `pyscript.passable_smart_light_engine_ready`, allowing zero-helper dynamic dashboard cards & popup actions to auto-populate learning data reset options.

---

## 📂 Architecture

The repository consists of two main components working together:

1. **`passable_smart_light_engine.yaml`**: The Home Assistant Blueprint frontend that exposes settings, handles presence/illuminance/media triggers, and dispatches events to Pyscript.
2. **`__init__.py`**: The Pyscript backend engine (`pyscript.passable_smart_light_engine`) that runs the core mathematics, hysteresis checks, curve building, and state persistence.

---

## 🚀 Installation

### Option 1: Direct Blueprint Import & Pyscript Setup

1. **Backend (Pyscript):**
   Copy `__init__.py` to your Home Assistant instance at:
   `/config/pyscript/apps/passable_smart_light_engine/__init__.py`

2. **Frontend (Blueprint):**
   Import the blueprint into Home Assistant via the UI:
   - Go to **Settings → Automations & Scenes → Blueprints**.
   - Click **Import Blueprint** and paste the raw GitHub URL:
     ```text
     https://github.com/GBear09/passable-smart-light-engine/blob/main/passable_smart_light_engine.yaml
     ```

---

### Option 2: HACS Custom Repository (Option B)

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add `https://github.com/GBear09/passable-smart-light-engine` as a **Blueprint** or **Pyscript** repository.
4. Click **Install**.

---

### Option 3: Git Pull Add-on Deployment (Option C - Automated Personal Deployment)

For a continuous deployment workflow directly from GitHub to your Home Assistant server:

1. Install the **Git Pull Add-on** from the Home Assistant Add-on Store.
2. Configure the add-on to sync this repository (`https://github.com/GBear09/passable-smart-light-engine`) into your Home Assistant directory:
   - Sync `__init__.py` to `/config/pyscript/apps/passable_smart_light_engine/__init__.py`
   - Sync `passable_smart_light_engine.yaml` to `/config/blueprints/automation/passable_smart_light_engine.yaml`
3. (Optional) Set up a GitHub Webhook to trigger the Git Pull Add-on automatically on every `git push`.

---

## 📋 Configuration & Blueprint Inputs

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `room_id` | String | Unique identifier (e.g. `living_room`) used as the key in persistent memory. |
| `presence_entity` | Entity List | Binary sensors (PIR, mmWave, Bayesian) indicating room occupancy. |
| `light_entity` | Entity | The main light or light group to control. |
| `lux_sensor` | Entity | Ambient illuminance sensor (lux). |
| `target_lux` | Number | Baseline lux level to maintain (Seed default: `40`). |
| `override_timeout_min` | Number | Duration (minutes) to pause automations when a manual override is detected (Default: `60`). |
| `manual_override_entity` | Entity | Optional `input_boolean` helper tracking active manual overrides. |
| `circadian_enabled` | Boolean | Enables Kelvin color temp shifting based on sun position. |

---

## 📄 License

Distributed under the [MIT License](LICENSE).
