"""Presence Simulation Coordinator for Passable Adaptive Smart Lighting Controller."""

import asyncio
from datetime import datetime, timedelta
import logging
import random
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from homeassistant.components import recorder
from homeassistant.components.recorder import history
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
import homeassistant.util.dt as dt_util

from .const import (
    CONF_HOLIDAY_HOME_STATE_ENTITY,
    CONF_LIGHT_ENTITY,
    CONF_SECONDARY_LIGHTS,
    CONF_SIMULATION_ARRIVAL_GRACE_MIN,
    CONF_SIMULATION_ENABLED,
    CONF_SIMULATION_JITTER_MIN,
    CONF_SIMULATION_LABEL,
    CONF_SIMULATION_LOOKBACK_DAYS,
    CONF_SIMULATION_MAX_BRIGHTNESS_PCT,
    CONF_SIMULATION_MODE,
    DEFAULT_HOLIDAY_HOME_STATE_ENTITY,
    DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
    DEFAULT_SIMULATION_ENABLED,
    DEFAULT_SIMULATION_JITTER_MIN,
    DEFAULT_SIMULATION_LABEL,
    DEFAULT_SIMULATION_LOOKBACK_DAYS,
    DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT,
    DEFAULT_SIMULATION_MODE,
    DOMAIN,
    MODE_PRESENCE_SIMULATION,
    SIMULATION_MODE_HISTORY,
    SIMULATION_MODE_HYBRID,
    SIMULATION_MODE_SYNTHETIC,
)
from .engine import clamp_kelvin_for_entity, get_light_members

if TYPE_CHECKING:
    from .engine import PassableLightingEngine, RoomController

_LOGGER = logging.getLogger(__name__)


class SimulationEvent:
    """Represents a scheduled lighting transition."""

    def __init__(self, target_time: datetime, entity_id: str, state: str, brightness_pct: Optional[int] = None) -> None:
        """Initialize a simulation event."""
        self.target_time = target_time
        self.entity_id = entity_id
        self.state = state  # "on" or "off"
        self.brightness_pct = brightness_pct

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<SimulationEvent {self.entity_id} -> {self.state} at {self.target_time.strftime('%H:%M:%S')}>"


class PresenceSimulationCoordinator:
    """Central coordinator for intelligent, vacation-immune presence simulation."""

    def __init__(self, hass: HomeAssistant, engine: "PassableLightingEngine", options: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the presence simulation coordinator."""
        self.hass = hass
        self.engine = engine
        self._options: Dict[str, Any] = options or {}
        self._enabled: bool = bool(self._options.get(CONF_SIMULATION_ENABLED, DEFAULT_SIMULATION_ENABLED))
        self._is_on: bool = False
        self._status: str = "idle"  # idle, planning, simulating, handover
        self._active_simulated_lights: Set[str] = set()
        self._scheduled_callbacks: List[CALLBACK_TYPE] = []
        self._scheduled_events: List[SimulationEvent] = []
        self._next_event: Optional[Dict[str, Any]] = None
        self._plan_unsub: Optional[CALLBACK_TYPE] = None
        self._grace_sweep_unsubs: List[CALLBACK_TYPE] = []
        self._switch_entity: Any = None
        self._master_switch_entity: Any = None
        self._listeners: List[CALLBACK_TYPE] = []

    @property
    def enabled(self) -> bool:
        """Return True if simulation feature is enabled."""
        return self._enabled

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable the presence simulation function."""
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._options[CONF_SIMULATION_ENABLED] = enabled
        _LOGGER.info("PresenceSimulation: Feature enabled status changed to %s", enabled)
        if not enabled and self._is_on:
            await self.async_stop()
        self._notify_state()

    def register_listener(self, cb: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a callback listener for coordinator state updates."""
        self._listeners.append(cb)

        @callback
        def _unsub() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _unsub

    def _notify_state(self) -> None:
        """Push updated coordinator state to switches and status sensors."""
        if self._switch_entity:
            self._switch_entity.async_write_ha_state()
        if self._master_switch_entity:
            self._master_switch_entity.async_write_ha_state()
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                pass

    @property
    def is_on(self) -> bool:
        """Return True if presence simulation switch is turned on."""
        return self._is_on

    @property
    def status(self) -> str:
        """Return operational status."""
        if not self._enabled:
            return "disabled"
        return self._status

    @property
    def active_simulated_lights(self) -> List[str]:
        """Return list of entities currently turned on by simulation."""
        return sorted(list(self._active_simulated_lights))

    @property
    def configured_target_entities(self) -> List[str]:
        """Return all light entities matching the target simulation label."""
        return self.async_resolve_target_entities()

    @property
    def next_event(self) -> Optional[Dict[str, Any]]:
        """Return upcoming transition metadata."""
        return self._next_event

    @property
    def label(self) -> str:
        """Return target entity label."""
        return self._options.get(CONF_SIMULATION_LABEL, DEFAULT_SIMULATION_LABEL)

    @property
    def mode(self) -> str:
        """Return configured simulation mode."""
        return self._options.get(CONF_SIMULATION_MODE, DEFAULT_SIMULATION_MODE)

    @property
    def lookback_days(self) -> int:
        """Return lookback delta days."""
        return int(self._options.get(CONF_SIMULATION_LOOKBACK_DAYS, DEFAULT_SIMULATION_LOOKBACK_DAYS))

    @property
    def jitter_min(self) -> int:
        """Return humanized jitter window in minutes."""
        return int(self._options.get(CONF_SIMULATION_JITTER_MIN, DEFAULT_SIMULATION_JITTER_MIN))

    @property
    def max_brightness_pct(self) -> int:
        """Return max simulated brightness floor/ceiling."""
        return int(self._options.get(CONF_SIMULATION_MAX_BRIGHTNESS_PCT, DEFAULT_SIMULATION_MAX_BRIGHTNESS_PCT))

    @property
    def arrival_grace_min(self) -> int:
        """Return arrival grace period in minutes."""
        return int(self._options.get(CONF_SIMULATION_ARRIVAL_GRACE_MIN, DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN))

    def register_switch(self, switch_entity: Any) -> None:
        """Register the switch entity instance for state callbacks."""
        self._switch_entity = switch_entity

    def register_master_switch(self, master_switch_entity: Any) -> None:
        """Register the master enable switch entity instance."""
        self._master_switch_entity = master_switch_entity

    def update_options(self, options: Dict[str, Any]) -> None:
        """Update coordinator options."""
        self._options.update(options)
        if CONF_SIMULATION_ENABLED in options:
            new_enabled = bool(options[CONF_SIMULATION_ENABLED])
            if self._enabled != new_enabled:
                self.hass.async_create_task(self.async_set_enabled(new_enabled))

    def is_light_simulating(self, entity_id: str) -> bool:
        """Check if a light entity is currently actively engaged in simulation."""
        if not self._is_on:
            return False
        return entity_id in self._active_simulated_lights

    def async_resolve_target_entities(self) -> List[str]:
        """Dynamically resolve all light entities tagged with the configured label."""
        reg = er.async_get(self.hass)
        target_label = self.label
        matching_entities: List[str] = []

        for entity in reg.entities.values():
            if entity.domain != "light":
                continue
            if entity.disabled:
                continue
            if target_label in entity.labels:
                matching_entities.append(entity.entity_id)

        return sorted(matching_entities)

    async def async_start(self) -> None:
        """Turn on presence simulation and schedule evening activities."""
        if not self._enabled:
            _LOGGER.warning("PresenceSimulation: Simulation is disabled in configuration. Ignoring start.")
            if self._switch_entity:
                self._switch_entity.async_write_ha_state()
            return

        if self._is_on:
            return

        for unsub in self._grace_sweep_unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._grace_sweep_unsubs.clear()

        self._is_on = True
        self._status = "planning"
        _LOGGER.info("PresenceSimulation: Simulation activated. Resolving targets and building schedule.")

        self._notify_state()

        await self._async_build_and_queue_schedule()

    async def async_stop(self) -> None:
        """Turn off presence simulation and handle graceful handover or cleanup."""
        if not self._is_on:
            return

        self._is_on = False
        _LOGGER.info("PresenceSimulation: Simulation deactivated. Assessing departure/arrival context.")
        self._clear_scheduled_timers()

        # Check ambient context: Sun elevation & Home Mode / Home State
        sun_state = self.hass.states.get("sun.sun")
        sun_is_down = sun_state is not None and sun_state.state == "below_horizon"

        home_entity = DEFAULT_HOLIDAY_HOME_STATE_ENTITY
        if self.engine.holiday_lighting and getattr(self.engine.holiday_lighting, "home_state_entity", None):
            home_entity = self.engine.holiday_lighting.home_state_entity

        away_states = ("away", "vacation", "extended_away", "not_home", "off", "unoccupied")
        home_mode_st = self.hass.states.get("input_select.home_mode")
        home_state_st = self.hass.states.get(home_entity) if home_entity else None

        if home_mode_st and home_mode_st.state and home_mode_st.state not in ("unknown", "unavailable"):
            home_mode = str(home_mode_st.state).strip()
            is_away = home_mode.lower() in away_states
            if (
                not is_away
                and home_entity != DEFAULT_HOLIDAY_HOME_STATE_ENTITY
                and home_state_st
                and home_state_st.state
                and str(home_state_st.state).strip().lower() in away_states
            ):
                home_mode = str(home_state_st.state).strip()
                is_away = True
        elif home_state_st and home_state_st.state and home_state_st.state not in ("unknown", "unavailable"):
            home_mode = str(home_state_st.state).strip()
            is_away = home_mode.lower() in away_states
        else:
            home_mode = "Home"
            is_away = False

        is_arrival_at_night = sun_is_down and not is_away

        if is_arrival_at_night:
            # =========================================================================
            # GRACEFUL ARRIVAL HANDOVER
            # The user arrived home in the dark. Do NOT extinguish illuminated lights!
            # Instead, hand them over to RoomControllers and vacancy timers.
            # =========================================================================
            self._status = "handover"
            active_lights = list(self._active_simulated_lights)
            self._active_simulated_lights.clear()
            _LOGGER.info(
                "PresenceSimulation [Graceful Handover]: Arrived home at night with %d active simulated lights. Handing over to room controllers without blackout.",
                len(active_lights),
            )

            grace_sec = float(self.arrival_grace_min * 60)
            for light_id in active_lights:
                # Check if this light belongs to a room controller
                room_ctrl = self._find_room_controller_for_light(light_id)
                if room_ctrl:
                    _LOGGER.info(
                        "PresenceSimulation: Handing over '%s' to room '%s' with %ds vacancy grace timer.",
                        light_id,
                        room_ctrl.room_id,
                        int(grace_sec),
                    )
                    # Trigger room evaluation: if occupied, stays on; if vacant, starts countdown
                    room_ctrl.schedule_vacancy_timer(delay_sec=grace_sec)
                    room_ctrl.notify_entities()
                    room_ctrl.schedule_evaluation("handover_arrival", delay_sec=0.1)
                else:
                    _LOGGER.info(
                        "PresenceSimulation: Standalone light '%s' will remain illuminated for %ds arrival grace.",
                        light_id,
                        int(grace_sec),
                    )
                    # Schedule delayed sweep for standalone lights
                    @callback
                    def _delayed_sweep(_now: Any, entity: str = light_id) -> None:
                        self.hass.async_create_task(self._async_turn_off_simulated_light(entity))

                    unsub_grace = async_call_later(
                        self.hass, grace_sec, _delayed_sweep
                    )
                    self._grace_sweep_unsubs.append(unsub_grace)

            self._status = "idle"

        else:
            # =========================================================================
            # MORNING / STILL AWAY CLEANUP
            # Either sunrise arrived or the user is still on vacation / away.
            # Turn off all active simulated lights.
            # =========================================================================
            self._status = "idle"
            active_lights = list(self._active_simulated_lights)
            self._active_simulated_lights.clear()
            _LOGGER.info(
                "PresenceSimulation [Cleanup]: Simulation stopped (Sun down: %s, Home mode: %s). Sweeping off %d active lights.",
                sun_is_down,
                home_mode,
                len(active_lights),
            )
            for light_id in active_lights:
                await self._async_turn_off_simulated_light(light_id)
                room_ctrl = self._find_room_controller_for_light(light_id)
                if room_ctrl:
                    room_ctrl.notify_entities()

        self._next_event = None
        self._notify_state()

    def _clear_scheduled_timers(self) -> None:
        """Cancel all pending transition callbacks and planning timers."""
        for unsub in self._scheduled_callbacks:
            try:
                unsub()
            except Exception:
                pass
        self._scheduled_callbacks.clear()
        self._scheduled_events.clear()

        for unsub in self._grace_sweep_unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._grace_sweep_unsubs.clear()

        if self._plan_unsub:
            try:
                self._plan_unsub()
            except Exception:
                pass
            self._plan_unsub = None

    def _find_room_controller_for_light(self, light_id: str) -> Optional["RoomController"]:
        """Find the RoomController managing a specific light entity or light group member."""
        for ctrl in self.engine.controllers.values():
            main_light = ctrl.entry_data.get(CONF_LIGHT_ENTITY) or ctrl.entry_data.get("light_entity")
            if main_light == light_id:
                return ctrl
            if main_light and light_id in get_light_members(self.hass, main_light):
                return ctrl
            sec_lights = ctrl.entry_data.get(CONF_SECONDARY_LIGHTS) or ctrl.entry_data.get("secondary_lights", [])
            if isinstance(sec_lights, str):
                sec_lights = [sec_lights]
            if isinstance(sec_lights, list):
                if light_id in sec_lights:
                    return ctrl
                for sec in sec_lights:
                    if sec and light_id in get_light_members(self.hass, sec):
                        return ctrl
        return None

    async def _async_build_and_queue_schedule(self) -> None:
        """Build the transition schedule for the current night using the configured strategy."""
        target_entities = self.async_resolve_target_entities()
        if not target_entities:
            _LOGGER.warning("PresenceSimulation: No light entities found with label '%s'. Simulation idle.", self.label)
            self._status = "idle"
            self._notify_state()
            return

        now = dt_util.now()
        events: List[SimulationEvent] = []

        mode = self.mode
        if mode in (SIMULATION_MODE_HISTORY, SIMULATION_MODE_HYBRID):
            _LOGGER.info("PresenceSimulation: Querying recorder history for smart baseline lookback.")
            events = await self._async_extract_history_events(target_entities)

        if not events and mode in (SIMULATION_MODE_SYNTHETIC, SIMULATION_MODE_HYBRID):
            _LOGGER.info("PresenceSimulation: Insufficient history; generating realistic synthetic evening routine.")
            events = self._generate_synthetic_routine(target_entities)

        if not events:
            _LOGGER.warning("PresenceSimulation: Could not construct simulation schedule. Retrying next cycle.")
            self._status = "idle"
            self._schedule_next_planning_cycle()
            return

        # Sort chronologically
        events.sort(key=lambda x: x.target_time)

        # Mid-evening initial state catch-up: if simulation starts after an entity's scheduled turn-on
        # and before its scheduled turn-off, actuate that initial ON state immediately
        sun_state = self.hass.states.get("sun.sun")
        sun_is_down = sun_state is not None and sun_state.state == "below_horizon"
        if sun_is_down:
            for ent in target_entities:
                past_for_ent = [e for e in events if e.entity_id == ent and e.target_time <= now]
                if past_for_ent and past_for_ent[-1].state == "on":
                    await self._async_execute_event(past_for_ent[-1])

        upcoming_events = [e for e in events if e.target_time > now]

        _LOGGER.info(
            "PresenceSimulation: Schedule constructed with %d total events (%d upcoming tonight, %d currently active).",
            len(events),
            len(upcoming_events),
            len(self._active_simulated_lights),
        )

        self._scheduled_events = upcoming_events
        self._schedule_upcoming_events()

        # Also schedule next day plan rollover at afternoon planning window
        self._schedule_next_planning_cycle()

    async def _async_extract_history_events(self, entities: List[str]) -> List[SimulationEvent]:
        """Extract state transitions from Home Assistant recorder history with vacation lookback."""
        now = dt_util.now()

        # Anchor to yesterday's date if started after midnight (00:00 - 05:59) so we replay the current night
        anchor_date = (now - timedelta(days=1)).date() if now.hour < 6 else now.date()
        tonight_start = dt_util.start_of_local_day(
            datetime.combine(anchor_date, datetime.min.time())
        ).replace(hour=16, minute=0, second=0, microsecond=0)

        jitter_range_sec = self.jitter_min * 60
        best_events: List[SimulationEvent] = []

        # Try up to 3 lookback multiples (e.g. 7, 14, 21 days) so if a prior lookback night had
        # insufficient genuine sessions, we step back one additional week automatically.
        for mult in (1, 2, 3):
            lookback_delta = timedelta(days=self.lookback_days * mult)
            base_date = anchor_date - lookback_delta
            base_start = dt_util.start_of_local_day(
                datetime.combine(base_date, datetime.min.time())
            ).replace(hour=16, minute=0, second=0, microsecond=0)
            base_end = base_start + timedelta(hours=14)  # 4:00 PM to 6:00 AM next morning

            def _fetch_history(
                start_t: datetime = base_start, end_t: datetime = base_end
            ) -> Dict[str, List[State]]:
                return history.get_significant_states(
                    self.hass,
                    start_time=start_t,
                    end_time=end_t,
                    entity_ids=entities,
                    include_start_time_state=True,
                    significant_changes_only=True,
                )

            try:
                hist_data = await recorder.get_instance(self.hass).async_add_executor_job(_fetch_history)
            except Exception as err:
                _LOGGER.error("PresenceSimulation: Recorder history query failed: %s", err)
                return []

            candidate_events: List[SimulationEvent] = []
            active_entity_count = 0

            for entity_id, state_list in hist_data.items():
                raw_sessions: List[Tuple[datetime, datetime, int]] = []
                prev_state: Optional[str] = None
                current_on_ts: Optional[datetime] = None
                current_brightness: int = self.max_brightness_pct

                for st in state_list:
                    state_val = st.state
                    if state_val not in ("on", "off"):
                        continue
                    if state_val == prev_state:
                        continue

                    # Skip initial 'off' boundary state at 4:00 PM so we don't schedule redundant off events
                    if prev_state is None and state_val == "off":
                        prev_state = "off"
                        continue

                    hist_ts = max(base_start, dt_util.as_local(st.last_changed))

                    if state_val == "on":
                        current_on_ts = hist_ts
                        raw_b = st.attributes.get("brightness")
                        if raw_b is not None:
                            current_brightness = max(
                                10, min(100, int(round((raw_b / 255.0) * 100)))
                            )
                        else:
                            current_brightness = self.max_brightness_pct
                        prev_state = "on"
                    elif state_val == "off" and prev_state == "on" and current_on_ts is not None:
                        off_ts = max(current_on_ts, hist_ts)
                        duration_sec = (off_ts - current_on_ts).total_seconds()
                        prev_state = "off"
                        # Ignore transient sub-5s switch bounces or aborted pulses
                        if duration_sec < 5.0:
                            current_on_ts = None
                            continue
                        raw_sessions.append((current_on_ts, off_ts, current_brightness))
                        current_on_ts = None

                # Guarantee a morning/late-night turn-off if historical window ended with the light still ON
                if prev_state == "on" and current_on_ts is not None:
                    dawn_cutoff = base_start + timedelta(hours=13, minutes=30)
                    fallback_off = max(
                        current_on_ts + timedelta(minutes=15),
                        min(dawn_cutoff, current_on_ts + timedelta(hours=2)),
                    )
                    raw_sessions.append((current_on_ts, fallback_off, current_brightness))

                if not raw_sessions:
                    continue

                # Merge sessions separated by brief <60s off gaps
                merged_sessions: List[Tuple[datetime, datetime, int]] = [raw_sessions[0]]
                for s_on, s_off, s_b in raw_sessions[1:]:
                    prev_on, prev_off, prev_b = merged_sessions[-1]
                    if (s_on - prev_off).total_seconds() < 60.0:
                        merged_sessions[-1] = (prev_on, max(prev_off, s_off), prev_b)
                    else:
                        merged_sessions.append((s_on, s_off, s_b))

                active_entity_count += 1
                last_event_time: Optional[datetime] = None

                for hist_on, hist_off, brightness in merged_sessions:
                    time_offset = max(timedelta(0), hist_on - base_start)
                    projected_on = tonight_start + time_offset
                    hist_duration = max(timedelta(minutes=2), hist_off - hist_on)

                    # Shift session start by humanized jitter while preserving session duration
                    start_jitter = random.randint(-jitter_range_sec, jitter_range_sec)
                    final_on = projected_on + timedelta(seconds=start_jitter)
                    if last_event_time is not None and final_on <= last_event_time + timedelta(minutes=2):
                        final_on = last_event_time + timedelta(minutes=random.randint(3, 6))

                    max_dur_jitter = min(jitter_range_sec // 2, int(hist_duration.total_seconds() * 0.2))
                    dur_jitter = (
                        random.randint(-max_dur_jitter, max_dur_jitter) if max_dur_jitter > 0 else 0
                    )
                    final_duration = max(
                        timedelta(minutes=2), hist_duration + timedelta(seconds=dur_jitter)
                    )
                    final_off = final_on + final_duration

                    candidate_events.append(SimulationEvent(final_on, entity_id, "on", brightness))
                    candidate_events.append(SimulationEvent(final_off, entity_id, "off"))
                    last_event_time = final_off

            if len(candidate_events) > len(best_events):
                best_events = candidate_events

            if active_entity_count >= min(2, len(entities)):
                return candidate_events

        return best_events

    def _generate_synthetic_routine(self, entities: List[str]) -> List[SimulationEvent]:
        """Generate a realistic, humanized evening lighting routine without requiring recorder DB."""
        now = dt_util.now()
        events: List[SimulationEvent] = []

        anchor_date = (now - timedelta(days=1)).date() if now.hour < 6 else now.date()
        base_day = datetime.combine(anchor_date, datetime.min.time(), tzinfo=now.tzinfo)

        # Solar-aware evening start (local sunset minus 15 min, clamped between 17:00 and 21:00)
        evening_start = base_day.replace(hour=17, minute=30, second=0, microsecond=0)
        sun_state = self.hass.states.get("sun.sun")
        if sun_state and sun_state.attributes.get("next_setting"):
            try:
                next_set = dt_util.parse_datetime(str(sun_state.attributes["next_setting"]))
                if next_set:
                    local_set = dt_util.as_local(next_set)
                    candidate = base_day.replace(
                        hour=local_set.hour, minute=local_set.minute, second=0, microsecond=0
                    ) - timedelta(minutes=15)
                    earliest = base_day.replace(hour=17, minute=0, second=0, microsecond=0)
                    latest = base_day.replace(hour=21, minute=0, second=0, microsecond=0)
                    evening_start = max(earliest, min(latest, candidate))
            except Exception:
                pass

        bedtime_start = max(
            base_day.replace(hour=22, minute=0, second=0, microsecond=0),
            evening_start + timedelta(minutes=90),
        )
        night_start = base_day.replace(hour=23, minute=30, second=0, microsecond=0)

        # Categorize target entities based on typical household room roles
        living_lights: List[str] = []
        bedroom_lights: List[str] = []
        transitional_lights: List[str] = []

        for ent in entities:
            lower = ent.lower()
            if any(k in lower for k in ("bed", "master", "kids", "max", "maggie", "madeleine")):
                bedroom_lights.append(ent)
            elif any(k in lower for k in ("stair", "hall", "foyer", "entry", "corridor")):
                transitional_lights.append(ent)
            else:
                living_lights.append(ent)

        jitter_sec = self.jitter_min * 60

        # 1. Living / Kitchen / Dining Routine (Active throughout evening 17:30 - 22:30)
        for ent in living_lights:
            # 2 to 3 active sessions
            num_sessions = random.randint(2, 3)
            current_cursor = evening_start + timedelta(minutes=random.randint(0, 45))

            for _ in range(num_sessions):
                on_duration = timedelta(minutes=random.randint(25, 60))
                off_duration = timedelta(minutes=random.randint(15, 40))

                on_time = current_cursor + timedelta(seconds=random.randint(-jitter_sec, jitter_sec))
                off_time = on_time + on_duration

                if on_time < bedtime_start + timedelta(minutes=30):
                    events.append(SimulationEvent(on_time, ent, "on", self.max_brightness_pct))
                    events.append(SimulationEvent(off_time, ent, "off"))

                current_cursor = off_time + off_duration

        # 2. Transitional Lights (Stairs, Foyer, Hallway) - Periodic brief activations
        for ent in transitional_lights:
            num_trips = random.randint(3, 5)
            for i in range(num_trips):
                trip_offset = timedelta(minutes=random.randint(30, 300))
                on_time = evening_start + trip_offset + timedelta(seconds=random.randint(-jitter_sec, jitter_sec))
                duration = timedelta(minutes=random.randint(4, 12))
                off_time = on_time + duration

                events.append(SimulationEvent(on_time, ent, "on", min(35, self.max_brightness_pct)))
                events.append(SimulationEvent(off_time, ent, "off"))

        # 3. Bedroom Routine (Bedtime preparation 21:45 - 23:15)
        for ent in bedroom_lights:
            bedtime_offset = timedelta(minutes=random.randint(0, 60))
            on_time = bedtime_start + bedtime_offset + timedelta(seconds=random.randint(-jitter_sec, jitter_sec))
            duration = timedelta(minutes=random.randint(15, 35))
            off_time = on_time + duration

            events.append(SimulationEvent(on_time, ent, "on", min(30, self.max_brightness_pct)))
            events.append(SimulationEvent(off_time, ent, "off"))

        return events

    def _schedule_upcoming_events(self) -> None:
        """Schedule asynchronous callbacks for all remaining events."""
        now = dt_util.now()
        for unsub in self._scheduled_callbacks:
            try:
                unsub()
            except Exception:
                pass
        self._scheduled_callbacks.clear()

        # Find first event and update metadata
        upcoming = [e for e in self._scheduled_events if e.target_time > now]
        if upcoming:
            first = upcoming[0]
            self._next_event = {
                "entity_id": first.entity_id,
                "state": first.state,
                "time": first.target_time.isoformat(),
            }
            self._status = "simulating"
        else:
            self._next_event = None
            self._status = "idle"

        self._notify_state()

        for event in upcoming:
            @callback
            def _fire(_now: Any, target_event: SimulationEvent = event) -> None:
                self.hass.async_create_task(self._async_execute_event(target_event))

            delay = (event.target_time - now).total_seconds()
            unsub = async_call_later(self.hass, max(0.5, delay), _fire)
            self._scheduled_callbacks.append(unsub)

    async def _async_execute_event(self, event: SimulationEvent) -> None:
        """Execute a scheduled transition with integration engine context."""
        if not self._is_on:
            return

        _LOGGER.info("PresenceSimulation: Executing scheduled event: %s -> %s", event.entity_id, event.state)

        # Register engine context to prevent echo guard and manual override locks
        ctx = Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)

        if event.state == "on":
            self._active_simulated_lights.add(event.entity_id)

            # Check if this entity has a room controller for circadian warmth
            room_ctrl = self._find_room_controller_for_light(event.entity_id)
            service_data: Dict[str, Any] = {
                ATTR_ENTITY_ID: event.entity_id,
            }

            # Set brightness
            b_pct = max(10, min(100, event.brightness_pct or self.max_brightness_pct))
            service_data["brightness_pct"] = b_pct

            # Apply circadian warm color temperature (e.g. 2700K) only if light supports color_temp
            clamped_k = clamp_kelvin_for_entity(self.hass, event.entity_id, 2700)
            if clamped_k is not None:
                service_data["color_temp_kelvin"] = clamped_k

            if room_ctrl:
                room_ctrl.cancel_vacancy_timer()
                self.engine.set_echo_guard(room_ctrl.room_id, b_pct, 0, 1.0)

            try:
                await self.hass.services.async_call("light", "turn_on", service_data, context=ctx)
            except Exception as err:
                _LOGGER.error("PresenceSimulation: Failed to turn on light '%s': %s", event.entity_id, err)

            # Update room controller active mode sensor if registered
            if room_ctrl:
                room_ctrl.notify_entities()

        else:
            room_ctrl = self._find_room_controller_for_light(event.entity_id)
            if room_ctrl:
                self.engine.set_echo_guard(room_ctrl.room_id, 0, 0, 1.0)
            try:
                await self.hass.services.async_call(
                    "light", "turn_off", {ATTR_ENTITY_ID: event.entity_id}, context=ctx
                )
            except Exception as err:
                _LOGGER.error("PresenceSimulation: Failed to turn off light '%s': %s", event.entity_id, err)
            finally:
                self._active_simulated_lights.discard(event.entity_id)

            if room_ctrl:
                room_ctrl.notify_entities()

        # Update next event display
        now = dt_util.now()
        upcoming = [e for e in self._scheduled_events if e.target_time > now]
        if upcoming:
            first = upcoming[0]
            self._next_event = {
                "entity_id": first.entity_id,
                "state": first.state,
                "time": first.target_time.isoformat(),
            }
        else:
            self._next_event = None

        self._notify_state()

    async def _async_turn_off_simulated_light(self, entity_id: str) -> None:
        """Safely turn off an actively simulated light with engine context."""
        ctx = Context()
        self.engine.register_engine_context(ctx.id, ttl_sec=30.0)
        try:
            await self.hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: entity_id}, context=ctx)
        except Exception as err:
            _LOGGER.debug("PresenceSimulation: Error turning off '%s' during sweep: %s", entity_id, err)

    def _schedule_next_planning_cycle(self) -> None:
        """Schedule planning for next sunset/evening when simulation remains active across multiple days."""
        if self._plan_unsub:
            try:
                self._plan_unsub()
            except Exception:
                pass
            self._plan_unsub = None

        now = dt_util.now()
        # Next afternoon at 3:30 PM to compile next night's schedule
        today_plan = now.replace(hour=15, minute=30, second=0, microsecond=0)
        next_plan_time = today_plan if now < today_plan else (today_plan + timedelta(days=1))
        delay = (next_plan_time - now).total_seconds()

        @callback
        def _plan_next(_now: Any) -> None:
            self._plan_unsub = None
            if self._is_on:
                self.hass.async_create_task(self._async_build_and_queue_schedule())

        self._plan_unsub = async_call_later(self.hass, max(60.0, delay), _plan_next)

    def stop(self) -> None:
        """Clean up scheduled timers on coordinator unload."""
        self._clear_scheduled_timers()
