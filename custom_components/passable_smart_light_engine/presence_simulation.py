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
    CONF_SIMULATION_ARRIVAL_GRACE_MIN,
    CONF_SIMULATION_JITTER_MIN,
    CONF_SIMULATION_LABEL,
    CONF_SIMULATION_LOOKBACK_DAYS,
    CONF_SIMULATION_MAX_BRIGHTNESS_PCT,
    CONF_SIMULATION_MODE,
    DEFAULT_SIMULATION_ARRIVAL_GRACE_MIN,
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
        self._is_on: bool = False
        self._status: str = "idle"  # idle, planning, simulating, handover
        self._active_simulated_lights: Set[str] = set()
        self._scheduled_callbacks: List[CALLBACK_TYPE] = []
        self._scheduled_events: List[SimulationEvent] = []
        self._next_event: Optional[Dict[str, Any]] = None
        self._plan_unsub: Optional[CALLBACK_TYPE] = None
        self._switch_entity: Any = None
        self._listeners: List[CALLBACK_TYPE] = []

    @property
    def is_on(self) -> bool:
        """Return True if presence simulation switch is turned on."""
        return self._is_on

    @property
    def status(self) -> str:
        """Return operational status."""
        return self._status

    @property
    def active_simulated_lights(self) -> List[str]:
        """Return list of entities currently turned on by simulation."""
        return sorted(list(self._active_simulated_lights))

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

    def update_options(self, options: Dict[str, Any]) -> None:
        """Update coordinator options."""
        self._options.update(options)

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

        _LOGGER.debug(
            "PresenceSimulation: Resolved %d entities for label '%s': %s",
            len(matching_entities),
            target_label,
            matching_entities,
        )
        return matching_entities

    async def async_start(self) -> None:
        """Turn on presence simulation and schedule evening activities."""
        if self._is_on:
            return

        self._is_on = True
        self._status = "planning"
        _LOGGER.info("PresenceSimulation: Simulation activated. Resolving targets and building schedule.")

        if self._switch_entity:
            self._switch_entity.async_write_ha_state()

        await self._async_build_and_queue_schedule()

    async def async_stop(self) -> None:
        """Turn off presence simulation and handle graceful handover or cleanup."""
        if not self._is_on:
            return

        self._is_on = False
        _LOGGER.info("PresenceSimulation: Simulation deactivated. Assessing departure/arrival context.")
        self._clear_scheduled_timers()

        # Check ambient context: Sun elevation & Home Mode
        sun_state = self.hass.states.get("sun.sun")
        sun_is_down = sun_state is not None and sun_state.state == "below_horizon"

        home_mode_state = self.hass.states.get("input_select.home_mode")
        home_mode = home_mode_state.state if home_mode_state else "Home"

        is_arrival_at_night = sun_is_down and home_mode == "Home"

        if is_arrival_at_night:
            # =========================================================================
            # GRACEFUL ARRIVAL HANDOVER
            # The user arrived home in the dark. Do NOT extinguish illuminated lights!
            # Instead, hand them over to RoomControllers and vacancy timers.
            # =========================================================================
            self._status = "handover"
            _LOGGER.info(
                "PresenceSimulation [Graceful Handover]: Arrived home at night with %d active simulated lights. Handing over to room controllers without blackout.",
                len(self._active_simulated_lights),
            )

            grace_sec = float(self.arrival_grace_min * 60)
            for light_id in list(self._active_simulated_lights):
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
                    room_ctrl.schedule_evaluation("handover_arrival", delay_sec=0.1)
                else:
                    _LOGGER.info(
                        "PresenceSimulation: Standalone light '%s' will remain illuminated for %ds arrival grace.",
                        light_id,
                        int(grace_sec),
                    )
                    # Schedule delayed sweep for standalone lights
                    @callback
                    def _delayed_sweep(entity: str = light_id) -> None:
                        self.hass.async_create_task(self._async_turn_off_simulated_light(entity))

                    async_call_later(self.hass, grace_sec, lambda _now, ent=light_id: _delayed_sweep(ent))

            self._active_simulated_lights.clear()
            self._status = "idle"

        else:
            # =========================================================================
            # MORNING / STILL AWAY CLEANUP
            # Either sunrise arrived or the user is still on vacation / away.
            # Turn off all active simulated lights.
            # =========================================================================
            self._status = "idle"
            _LOGGER.info(
                "PresenceSimulation [Cleanup]: Simulation stopped (Sun down: %s, Home mode: %s). Sweeping off %d active lights.",
                sun_is_down,
                home_mode,
                len(self._active_simulated_lights),
            )
            for light_id in list(self._active_simulated_lights):
                await self._async_turn_off_simulated_light(light_id)
            self._active_simulated_lights.clear()

        self._next_event = None
        if self._switch_entity:
            self._switch_entity.async_write_ha_state()

    def _clear_scheduled_timers(self) -> None:
        """Cancel all pending transition callbacks and planning timers."""
        for unsub in self._scheduled_callbacks:
            try:
                unsub()
            except Exception:
                pass
        self._scheduled_callbacks.clear()
        self._scheduled_events.clear()

        if self._plan_unsub:
            try:
                self._plan_unsub()
            except Exception:
                pass
            self._plan_unsub = None

    def _find_room_controller_for_light(self, light_id: str) -> Optional["RoomController"]:
        """Find the RoomController managing a specific light entity."""
        for ctrl in self.engine.controllers.values():
            if ctrl.entry_data.get("light_entity") == light_id:
                return ctrl
            sec_lights = ctrl.entry_data.get("secondary_lights", [])
            if isinstance(sec_lights, list) and light_id in sec_lights:
                return ctrl
        return None

    async def _async_build_and_queue_schedule(self) -> None:
        """Build the transition schedule for the current night using the configured strategy."""
        target_entities = self.async_resolve_target_entities()
        if not target_entities:
            _LOGGER.warning("PresenceSimulation: No light entities found with label '%s'. Simulation idle.", self.label)
            self._status = "idle"
            if self._switch_entity:
                self._switch_entity.async_write_ha_state()
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
            return

        # Sort chronologically and filter out past events
        events.sort(key=lambda x: x.target_time)
        upcoming_events = [e for e in events if e.target_time > now]

        _LOGGER.info(
            "PresenceSimulation: Schedule constructed with %d total events (%d upcoming tonight).",
            len(events),
            len(upcoming_events),
        )

        self._scheduled_events = upcoming_events
        self._schedule_upcoming_events()

        # Also schedule next day plan rollover at sunrise/morning
        self._schedule_next_planning_cycle()

    async def _async_extract_history_events(self, entities: List[str]) -> List[SimulationEvent]:
        """Extract state transitions from Home Assistant recorder history with vacation lookback."""
        now = dt_util.now()
        lookback_delta = timedelta(days=self.lookback_days)

        # Baseline window: same time of day, N days ago
        base_start = (now - lookback_delta).replace(hour=16, minute=0, second=0, microsecond=0)
        base_end = base_start + timedelta(hours=14)  # 4:00 PM to 6:00 AM next morning

        def _fetch_history() -> Dict[str, List[State]]:
            return history.get_significant_states(
                self.hass,
                start_time=base_start,
                end_time=base_end,
                entity_ids=entities,
                include_start_time_state=True,
                significant_changes_only=True,
            )

        try:
            hist_data = await recorder.get_instance(self.hass).async_add_executor_job(_fetch_history)
        except Exception as err:
            _LOGGER.error("PresenceSimulation: Recorder history query failed: %s", err)
            return []

        events: List[SimulationEvent] = []
        jitter_range_sec = self.jitter_min * 60

        for entity_id, state_list in hist_data.items():
            prev_state = None
            for st in state_list:
                state_val = st.state
                if state_val not in ("on", "off"):
                    continue
                if state_val == prev_state:
                    continue

                # Map historical timestamp to current night
                hist_ts = dt_util.as_local(st.last_changed)
                time_offset = hist_ts - base_start
                projected_time = now.replace(hour=16, minute=0, second=0, microsecond=0) + time_offset

                # Apply humanized jitter
                jitter = random.randint(-jitter_range_sec, jitter_range_sec)
                final_time = projected_time + timedelta(seconds=jitter)

                # Brightness handling
                brightness = None
                if state_val == "on":
                    raw_b = st.attributes.get("brightness")
                    if raw_b is not None:
                        brightness = int(round((raw_b / 255.0) * 100))
                    else:
                        brightness = self.max_brightness_pct

                events.append(SimulationEvent(final_time, entity_id, state_val, brightness))
                prev_state = state_val

        return events

    def _generate_synthetic_routine(self, entities: List[str]) -> List[SimulationEvent]:
        """Generate a realistic, humanized evening lighting routine without requiring recorder DB."""
        now = dt_util.now()
        events: List[SimulationEvent] = []

        # Today's reference evening anchor (approx. 5:30 PM / sunset anchor)
        evening_start = now.replace(hour=17, minute=30, second=0, microsecond=0)
        bedtime_start = now.replace(hour=22, minute=0, second=0, microsecond=0)
        night_start = now.replace(hour=23, minute=30, second=0, microsecond=0)

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

        if self._switch_entity:
            self._switch_entity.async_write_ha_state()

        for event in upcoming:
            @callback
            def _fire(target_event: SimulationEvent = event) -> None:
                self.hass.async_create_task(self._async_execute_event(target_event))

            delay = (event.target_time - now).total_seconds()
            unsub = async_call_later(self.hass, max(0.5, delay), lambda _now, ev=event: _fire(ev))
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
            b_pct = event.brightness_pct or self.max_brightness_pct
            service_data["brightness_pct"] = max(10, min(100, b_pct))

            # Apply circadian warm color temperature (e.g. 2700K) if light supports color temp
            service_data["color_temp_kelvin"] = 2700

            try:
                await self.hass.services.async_call("light", "turn_on", service_data, context=ctx)
            except Exception as err:
                _LOGGER.error("PresenceSimulation: Failed to turn on light '%s': %s", event.entity_id, err)

            # Update room controller active mode if registered
            if room_ctrl:
                room_ctrl.schedule_evaluation("presence_simulation_event", delay_sec=0.1)

        else:
            self._active_simulated_lights.discard(event.entity_id)
            try:
                await self.hass.services.async_call(
                    "light", "turn_off", {ATTR_ENTITY_ID: event.entity_id}, context=ctx
                )
            except Exception as err:
                _LOGGER.error("PresenceSimulation: Failed to turn off light '%s': %s", event.entity_id, err)

            room_ctrl = self._find_room_controller_for_light(event.entity_id)
            if room_ctrl:
                room_ctrl.schedule_evaluation("presence_simulation_event", delay_sec=0.1)

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

        if self._switch_entity:
            self._switch_entity.async_write_ha_state()

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
        now = dt_util.now()
        # Next afternoon at 3:30 PM to compile next night's schedule
        next_plan_time = (now + timedelta(days=1)).replace(hour=15, minute=30, second=0, microsecond=0)
        delay = (next_plan_time - now).total_seconds()

        @callback
        def _plan_next(_now: Any) -> None:
            if self._is_on:
                self.hass.async_create_task(self._async_build_and_queue_schedule())

        self._plan_unsub = async_call_later(self.hass, max(60.0, delay), _plan_next)
