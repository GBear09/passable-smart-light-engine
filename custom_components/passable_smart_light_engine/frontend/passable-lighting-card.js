/**
 * Passable Lighting Card
 * Bundled companion card for Passable Smart Light Engine
 * https://github.com/GBear09/passable-smart-light-engine
 */

const CARD_VERSION = "2.9.0";
const ENGINE_DOMAIN = "passable_smart_light_engine";

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ||
    customElements.get("hui-entities-card") ||
    customElements.get("hui-masonry-view") ||
    customElements.get("hc-main")
);
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;
const svg =
  LitElement.prototype.svg ||
  ((strings, ...values) => {
    const result = html(strings, ...values);
    if (result && typeof result === "object") {
      return Object.assign({}, result, { _$litType$: 2, type: "svg" });
    }
    return result;
  });

console.info(
  `%c PASSABLE-LIGHTING-CARD %c v${CARD_VERSION} IS LOADED `,
  "color: #ffffff; background: #d97706; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #b45309; background: #fef3c7; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);

const MODE_LABELS = {
  occupied: "Occupied",
  vacant: "Vacant",
  manual_override: "Override",
  disabled: "Auto Off",
  holiday: "Holiday",
  presence_simulation: "Away Sim",
  forced_off: "Forced Off",
  frozen: "Frozen",
  notification: "Notify",
  media: "Media",
  late_night: "Late Night",
  secondary_active: "Task Light",
};

const RESET_TYPE_OPTIONS = [
  { value: "all", label: "All Datasets" },
  { value: "user_prefs", label: "User Sun Prefs" },
  { value: "room_curves", label: "Lux Yield Curves" },
  { value: "media_prefs", label: "Media Presets" },
  { value: "late_night_prefs", label: "Late Night Presets" },
];

class PassableLightingCard extends LitElement {
  static getConfigElement() {
    return document.createElement("passable-lighting-card-editor");
  }

  static getStubConfig() {
    return {
      title: "Lighting",
      show_header: false,
      layout: "tiles",
      master_light: "light.all_lights",
      show_summary_strip: true,
      show_holiday_banner: true,
      show_master_dimmer: true,
      show_engine_footer: true,
      default_expanded_floor: "",
      stats_navigation_path: "",
      exclude_entities: [],
      alerts: [],
      floors: [],
    };
  }

  static get properties() {
    return {
      hass: { attribute: false },
      config: { state: true },
      _wsData: { state: true },
      _wsError: { state: true },
      _drawerMode: { state: true },
      _drawerOnOnly: { state: true },
      _modalOpen: { state: true },
      _modalTab: { state: true },
      _modalFloorFilter: { state: true },
      _expandedEngineRoom: { state: true },
      _resetTargetByRoom: { state: true },
      _confirmResetRoom: { state: true },
      _calibratingRoom: { state: true },
      _draggingSliders: { state: true },
      _toastMsg: { state: true },
      _tickNow: { state: true },
    };
  }

  constructor() {
    super();
    this._wsData = null;
    this._wsError = null;
    this._wsUnsub = null;
    this._wsSubscribing = false;
    this._wsSnapshotAt = Date.now();
    this._drawerMode = null;
    this._drawerInitialized = false;
    this._drawerOnOnly = false;
    this._modalOpen = false;
    this._modalTab = "lights";
    this._modalFloorFilter = "active";
    this._expandedEngineRoom = null;
    this._resetTargetByRoom = {};
    this._confirmResetRoom = null;
    this._calibratingRoom = null;
    this._draggingSliders = {};
    this._toastMsg = null;
    this._tickNow = Date.now();
    this._countdownInterval = null;
    this._closeModalTimer = null;
    this._toastTimer = null;
    this._confirmResetTimer = null;
    this._ringHoldTimer = null;
    this._ringHoldFired = false;
    this._onKeyDown = (ev) => {
      if (ev.key === "Escape" && this._modalOpen) {
        this._closeModal();
      }
    };
  }

  setConfig(config) {
    if (!config) {
      throw new Error("Invalid configuration");
    }
    this.config = {
      title: "Lighting",
      show_header: false,
      layout: "tiles",
      master_light: "light.all_lights",
      show_summary_strip: true,
      show_holiday_banner: true,
      show_master_dimmer: true,
      show_engine_footer: true,
      default_expanded_floor: "",
      stats_navigation_path: "",
      exclude_entities: [],
      alerts: [],
      floors: [],
      ...config,
    };

    if (!this._drawerInitialized && this.config.default_expanded_floor) {
      this._drawerMode = this.config.default_expanded_floor;
    }
    this._drawerInitialized = true;
  }

  getCardSize() {
    const layout = this.config?.layout || "tiles";
    if (layout === "rings") return 3;
    if (layout === "rows") return 5;
    return 4;
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("keydown", this._onKeyDown);
    if (this.hass && !this._wsUnsub && !this._wsSubscribing) {
      this._subscribeEngine();
    }
    this._syncCountdownTimer();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKeyDown);
    this._unsubscribeEngine();
    clearInterval(this._countdownInterval);
    this._countdownInterval = null;
    clearTimeout(this._closeModalTimer);
    clearTimeout(this._toastTimer);
    clearTimeout(this._confirmResetTimer);
    clearTimeout(this._ringHoldTimer);
  }

  updated(changedProps) {
    super.updated(changedProps);
    if (changedProps.has("hass") && this.hass && !this._wsUnsub && !this._wsSubscribing && !this._wsData) {
      this._subscribeEngine();
    }
  }

  shouldUpdate(changedProps) {
    if (!changedProps.has("hass")) return true;
    for (const key of changedProps.keys()) {
      if (key !== "hass") return true;
    }
    const oldHass = changedProps.get("hass");
    const newHass = this.hass;
    if (!oldHass || !newHass || !oldHass.states || !newHass.states) return true;
    return this._hasRelevantHassStateChange(oldHass, newHass);
  }

  _hasRelevantHassStateChange(oldHass, newHass) {
    const oldStates = oldHass.states;
    const newStates = newHass.states;

    const watched = new Set([
      "sensor.passable_smart_light_engine_summary",
      "sensor.passable_smart_light_engine_ready",
      "sensor.active_holiday",
      "switch.holiday_lighting",
      "switch.holiday_decorations",
      "switch.exterior_dusk_to_dawn_lighting",
      "switch.simulate_presence_away_mode",
      "switch.presence_simulation",
      "sensor.presence_simulation_status",
      "sun.sun",
    ]);

    if (this.config?.master_light) {
      watched.add(this.config.master_light);
    }
    if (Array.isArray(this.config?.alerts)) {
      for (const a of this.config.alerts) {
        if (a?.entity) watched.add(a.entity);
      }
    }
    if (Array.isArray(this.config?.floors)) {
      for (const f of this.config.floors) {
        if (f?.entity) watched.add(f.entity);
        if (Array.isArray(f?.entities)) {
          f.entities.forEach((eid) => eid && watched.add(eid));
        }
      }
    }
    if (Array.isArray(this._wsData?.rooms)) {
      for (const r of this._wsData.rooms) {
        if (r.light_entity) watched.add(r.light_entity);
        if (r.lux_sensor) watched.add(r.lux_sensor);
        (r.secondary_lights || []).forEach((id) => id && watched.add(id));
        (r.leaf_lights || []).forEach((id) => id && watched.add(id));
        if (r.entities) {
          Object.values(r.entities).forEach((id) => id && watched.add(id));
        }
      }
    }

    for (const id of watched) {
      if (oldStates[id] !== newStates[id]) return true;
    }

    // Also watch all light.* entities in HA so floor stats/leaf brightness stay live
    const checkKeys = (statesObj) => {
      for (const id of Object.keys(statesObj)) {
        if (id.startsWith("light.") && oldStates[id] !== newStates[id]) {
          return true;
        }
      }
      return false;
    };
    return checkKeys(newStates) || checkKeys(oldStates);
  }

  _unsubscribeEngine() {
    if (this._wsUnsub) {
      try {
        this._wsUnsub();
      } catch (_err) {
        // Ignore teardown errors
      }
      this._wsUnsub = null;
    }
  }

  async _subscribeEngine() {
    if (!this.hass || this._wsUnsub || this._wsSubscribing) return;
    this._wsSubscribing = true;
    try {
      if (this.hass.connection && typeof this.hass.connection.subscribeMessage === "function") {
        const unsub = await this.hass.connection.subscribeMessage(
          (snapshot) => {
            this._wsData = snapshot;
            this._wsSnapshotAt = Date.now();
            this._wsError = null;
            this._syncCountdownTimer();
            this.requestUpdate();
          },
          { type: `${ENGINE_DOMAIN}/subscribe` }
        );
        if (!this.isConnected) {
          unsub();
        } else {
          this._wsUnsub = unsub;
        }
      } else {
        await this._fetchFallbackData();
      }
    } catch (err) {
      this._wsError = err?.message || "WebSocket unavailable";
      await this._fetchFallbackData();
    } finally {
      this._wsSubscribing = false;
    }
  }

  async _fetchFallbackData() {
    if (!this.hass) return;
    try {
      const res = await this.hass.callWS({ type: `${ENGINE_DOMAIN}/get_data` });
      if (res) {
        this._wsData = res;
        this._wsSnapshotAt = Date.now();
        this._wsError = null;
        this._syncCountdownTimer();
      }
    } catch (err) {
      this._wsError = err?.message || "Failed to query engine";
    }
  }

  _syncCountdownTimer() {
    const rooms = this._wsData?.rooms || [];
    const hasOverride = rooms.some((r) => r.override_active);
    const countdownVisible = Boolean(this._drawerMode || this._modalOpen);
    if (hasOverride && countdownVisible) {
      if (!this._countdownInterval) {
        this._countdownInterval = setInterval(() => {
          this._tickNow = Date.now();
        }, 1000);
      }
    } else if (this._countdownInterval) {
      clearInterval(this._countdownInterval);
      this._countdownInterval = null;
    }
  }

  _fireHaptic(type = "light") {
    const ev = new Event("haptic", { bubbles: true, composed: true });
    ev.detail = type;
    this.dispatchEvent(ev);
  }

  _showToast(msg) {
    this._toastMsg = msg;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toastMsg = null;
    }, 2200);
  }

  _showMoreInfo(entityId, ev = null) {
    if (ev) ev.stopPropagation();
    if (!entityId) return;
    this._fireHaptic("light");
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId };
    this.dispatchEvent(event);
  }

  _navigateTo(path) {
    if (!path) return;
    this._fireHaptic("light");
    window.history.pushState(null, "", path);
    window.dispatchEvent(new Event("location-changed", { bubbles: true, composed: true }));
  }

  _executeActionConfig(actionConfig, fallbackEntityId = null) {
    if (!actionConfig || !this.hass) return;
    const action = actionConfig.action;
    if (action === "none") return;
    this._fireHaptic("light");

    if (action === "fire-dom-event") {
      const event = new Event("ll-custom", { bubbles: true, composed: true, cancelable: false });
      event.detail = actionConfig;
      this.dispatchEvent(event);
    } else if (action === "call-service" || action === "perform-action") {
      const serviceString = actionConfig.perform_action || actionConfig.service || "";
      if (serviceString.includes(".")) {
        const [domain, service] = serviceString.split(".", 2);
        const serviceData = {
          ...(actionConfig.data || {}),
          ...(actionConfig.target || {}),
        };
        if (fallbackEntityId && !serviceData.entity_id && !actionConfig.target) {
          serviceData.entity_id = fallbackEntityId;
        }
        this.hass.callService(domain, service, serviceData);
      }
    } else if (action === "navigate") {
      this._navigateTo(actionConfig.navigation_path);
    } else if (action === "url" && actionConfig.url_path) {
      window.open(actionConfig.url_path, "_blank");
    } else if (action === "toggle") {
      const target = actionConfig.entity || fallbackEntityId;
      if (target) {
        const domain = target.split(".")[0];
        this.hass.callService(domain === "light" ? "light" : "homeassistant", "toggle", {
          entity_id: target,
        });
      }
    } else if (action === "more-info") {
      this._showMoreInfo(actionConfig.entity || fallbackEntityId);
    }
  }

  // ==========================================
  // DISCOVERY & STATE AGGREGATION
  // ==========================================

  _getExcludeSet() {
    const arr = Array.isArray(this.config?.exclude_entities)
      ? this.config.exclude_entities
      : [];
    return new Set(arr.filter(Boolean));
  }

  _expandLightGroup(entityId, visited = new Set()) {
    if (!entityId || visited.has(entityId)) return [];
    const excludeSet = this._getExcludeSet();
    if (excludeSet.has(entityId)) return [];

    const st = this.hass?.states?.[entityId];
    if (!st) return [entityId];

    const members = st.attributes?.entity_id;
    if (Array.isArray(members) && members.length > 0) {
      const nextVisited = new Set(visited);
      nextVisited.add(entityId);
      const result = [];
      for (const child of members) {
        if (typeof child === "string") {
          for (const leaf of this._expandLightGroup(child, nextVisited)) {
            if (!result.includes(leaf)) result.push(leaf);
          }
        }
      }
      return result;
    }

    return [entityId];
  }

  _cleanFloorName(rawName, entityId = "") {
    let name = String(rawName || entityId || "")
      .replace(/^light\./i, "")
      .replace(/_/g, " ")
      .trim();
    name = name.replace(/\s+lights?$/i, "").trim();
    return name || rawName || "Lights";
  }

  _inferFloorIcon(floorId, floorName, explicitIcon) {
    if (explicitIcon) return explicitIcon;
    const key = `${floorId} ${floorName}`.toLowerCase();
    if (key.includes("attic")) return "mdi:home-roof";
    if (key.includes("upstairs") || key.includes("floor 2") || key.includes("second")) {
      return "mdi:home-floor-2";
    }
    if (key.includes("downstairs") || key.includes("main") || key.includes("first") || key.includes("ground")) {
      return "mdi:home-floor-1";
    }
    if (key.includes("basement") || key.includes("lower") || key.includes("cellar")) {
      return "mdi:home-floor-b";
    }
    if (key.includes("outside") || key.includes("exterior") || key.includes("outdoor") || key.includes("porch") || key.includes("yard")) {
      return "mdi:pine-tree";
    }
    return "mdi:lightbulb-group";
  }

  _resolveFloors() {
    const excludeSet = this._getExcludeSet();
    const explicitFloors = this.config?.floors;

    // 1. Explicit YAML floor configuration
    if (Array.isArray(explicitFloors) && explicitFloors.length > 0) {
      return explicitFloors
        .map((f, idx) => {
          const id = f.id || f.entity || `floor_${idx}`;
          const leaves = [];
          if (f.entity) {
            this._expandLightGroup(f.entity).forEach((l) => !leaves.includes(l) && leaves.push(l));
          }
          if (Array.isArray(f.entities)) {
            f.entities.forEach((ent) => {
              this._expandLightGroup(ent).forEach((l) => !leaves.includes(l) && leaves.push(l));
            });
          }
          const st = f.entity ? this.hass?.states?.[f.entity] : null;
          const name = f.name || this._cleanFloorName(st?.attributes?.friendly_name || id, f.entity);
          return {
            id,
            name,
            entity: f.entity || null,
            icon: this._inferFloorIcon(id, name, f.icon),
            leaves,
          };
        })
        .filter((f) => f.leaves.length > 0 || f.entity);
    }

    // 2. Recursive expansion from master_light (e.g. light.all_lights)
    const masterId = this.config?.master_light || "light.all_lights";
    const masterSt = masterId ? this.hass?.states?.[masterId] : null;
    const masterMembers = masterSt?.attributes?.entity_id;
    if (Array.isArray(masterMembers) && masterMembers.length > 0) {
      const floors = [];
      const looseLeaves = [];

      for (const childId of masterMembers) {
        if (excludeSet.has(childId)) continue;
        const childSt = this.hass?.states?.[childId];
        const childMembers = childSt?.attributes?.entity_id;
        if (Array.isArray(childMembers) && childMembers.length > 0) {
          const leaves = this._expandLightGroup(childId);
          if (leaves.length === 0) continue;
          const name = this._cleanFloorName(childSt?.attributes?.friendly_name || childId, childId);
          floors.push({
            id: childId,
            name,
            entity: childId,
            icon: this._inferFloorIcon(childId, name, childSt?.attributes?.icon),
            leaves,
          });
        } else {
          looseLeaves.push(childId);
        }
      }

      if (looseLeaves.length > 0) {
        floors.push({
          id: "other_lights",
          name: "Other",
          entity: null,
          icon: "mdi:lightbulb-group",
          leaves: looseLeaves,
        });
      }

      if (floors.length > 0) return floors;
    }

    // 3. Fallback to Home Assistant Floor & Area Registry from WebSocket
    const haHierarchy = this._wsData?.ha_hierarchy;
    if (haHierarchy) {
      const isGroupLight = (eid) => {
        const members = this.hass?.states?.[eid]?.attributes?.entity_id;
        return Array.isArray(members) && members.length > 0;
      };
      const floors = [];
      for (const fl of haHierarchy.floors || []) {
        const leaves = [];
        for (const area of fl.areas || []) {
          for (const lid of area.lights || []) {
            if (!excludeSet.has(lid) && !isGroupLight(lid) && !leaves.includes(lid)) {
              leaves.push(lid);
            }
          }
        }
        if (leaves.length > 0) {
          floors.push({
            id: fl.floor_id,
            name: fl.name,
            entity: null,
            icon: this._inferFloorIcon(fl.floor_id, fl.name, fl.icon),
            leaves,
          });
        }
      }

      const unassignedLeaves = [];
      for (const area of haHierarchy.unassigned_areas || []) {
        for (const lid of area.lights || []) {
          if (!excludeSet.has(lid) && !isGroupLight(lid) && !unassignedLeaves.includes(lid)) {
            unassignedLeaves.push(lid);
          }
        }
      }
      if (unassignedLeaves.length > 0) {
        floors.push({
          id: "exterior_other",
          name: "Exterior & Other",
          entity: null,
          icon: "mdi:pine-tree",
          leaves: unassignedLeaves,
        });
      }
      if (floors.length > 0) return floors;
    }

    // 4. Final fallback: all non-group lights in engine rooms or hass.states
    const allLeaves = [];
    for (const r of this._wsData?.rooms || []) {
      for (const lid of r.leaf_lights || []) {
        if (!excludeSet.has(lid) && !allLeaves.includes(lid)) {
          allLeaves.push(lid);
        }
      }
    }
    if (allLeaves.length === 0 && this.hass?.states) {
      for (const [eid, st] of Object.entries(this.hass.states)) {
        if (
          eid.startsWith("light.") &&
          !excludeSet.has(eid) &&
          !(Array.isArray(st.attributes?.entity_id) && st.attributes.entity_id.length > 0)
        ) {
          allLeaves.push(eid);
        }
      }
    }
    return allLeaves.length > 0
      ? [
          {
            id: "all",
            name: "All Lights",
            entity: this.config?.master_light || null,
            icon: "mdi:lightbulb-group",
            leaves: allLeaves,
          },
        ]
      : [];
  }

  _getAllLeafLights(floors) {
    const all = [];
    for (const f of floors) {
      for (const lid of f.leaves) {
        if (!all.includes(lid)) all.push(lid);
      }
    }
    return all;
  }

  _buildEngineRoomMaps() {
    const rooms = this._wsData?.rooms || [];
    const leafToRoom = {};
    for (const room of rooms) {
      const candidates = new Set(room.leaf_lights || []);
      if (room.light_entity) {
        this._expandLightGroup(room.light_entity).forEach((l) => candidates.add(l));
      }
      (room.secondary_lights || []).forEach((s) => {
        this._expandLightGroup(s).forEach((l) => candidates.add(l));
      });
      for (const lid of candidates) {
        if (!leafToRoom[lid]) {
          leafToRoom[lid] = room;
        }
      }
    }
    return { rooms, leafToRoom };
  }

  _buildLeafSubgroupLabels(floors) {
    const leafGroupName = {};
    for (const f of floors) {
      const parentSt = f.entity ? this.hass?.states?.[f.entity] : null;
      const children = parentSt?.attributes?.entity_id;
      if (Array.isArray(children)) {
        for (const childId of children) {
          const childSt = this.hass?.states?.[childId];
          const subMembers = childSt?.attributes?.entity_id;
          if (Array.isArray(subMembers) && subMembers.length > 0) {
            const label = this._cleanFloorName(
              childSt?.attributes?.friendly_name || childId,
              childId
            );
            for (const leaf of this._expandLightGroup(childId)) {
              if (!leafGroupName[leaf]) leafGroupName[leaf] = label;
            }
          }
        }
      }
    }
    return leafGroupName;
  }

  _isLightOn(entityId) {
    return this.hass?.states?.[entityId]?.state === "on";
  }

  _getLightPct(entityId) {
    if (this._draggingSliders && this._draggingSliders[entityId] !== undefined) {
      return this._draggingSliders[entityId];
    }
    const st = this.hass?.states?.[entityId];
    if (!st || st.state !== "on") return 0;
    const rawBrightness = st.attributes?.brightness;
    if (rawBrightness != null && !isNaN(Number(rawBrightness))) {
      return Math.max(1, Math.min(100, Math.round((Number(rawBrightness) / 255) * 100)));
    }
    return 100;
  }

  _isLightDimmable(entityId) {
    const st = this.hass?.states?.[entityId];
    if (!st) return false;
    const modes = st.attributes?.supported_color_modes;
    if (Array.isArray(modes) && modes.length > 0) {
      return modes.some((m) => m !== "onoff");
    }
    return st.attributes?.brightness !== undefined;
  }

  _getLightName(entityId) {
    const st = this.hass?.states?.[entityId];
    return st?.attributes?.friendly_name || entityId.replace(/^light\./, "").replace(/_/g, " ");
  }

  _getFloorStats(floor, leafToRoom) {
    const total = floor.leaves.length;
    const active = floor.leaves.filter((id) => this._isLightOn(id));
    const on = active.length;
    const pct = on > 0
      ? Math.round(active.reduce((sum, id) => sum + this._getLightPct(id), 0) / on)
      : 0;
    const hasOverride = floor.leaves.some((id) => leafToRoom[id]?.override_active);
    const hasNotify = floor.leaves.some((id) => leafToRoom[id]?.notification_showing);
    return { total, on, pct, hasOverride, hasNotify };
  }

  _getOverrideRemainingSec(room) {
    if (!room?.override_active) return 0;
    const elapsedSec = Math.floor((this._tickNow - this._wsSnapshotAt) / 1000);
    return Math.max(0, Math.round((room.override_remaining_sec || 0) - elapsedSec));
  }

  _formatCountdown(sec) {
    if (!sec || sec <= 0) return "0m";
    if (sec >= 3600) {
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      return `${h}h ${m}m`;
    }
    if (sec >= 60) {
      return `${Math.ceil(sec / 60)}m`;
    }
    return `${sec}s`;
  }

  _getSummaryMetrics(allLeaves) {
    const totalLights = allLeaves.length;
    const activeLeaves = allLeaves.filter((id) => this._isLightOn(id));
    const onLights = activeLeaves.length;
    const avgPct =
      this._draggingSliders?.__master__ !== undefined
        ? this._draggingSliders.__master__
        : onLights > 0
          ? Math.round(activeLeaves.reduce((s, id) => s + this._getLightPct(id), 0) / onLights)
          : 0;

    const wsSummary = this._wsData?.summary || {};
    const summaryAttr = this.hass?.states?.["sensor.passable_smart_light_engine_summary"]?.attributes || {};

    const totalRooms = wsSummary.total_rooms ?? summaryAttr.total_rooms ?? (this._wsData?.rooms?.length || 0);
    const autoRooms = wsSummary.rooms_auto_enabled ?? summaryAttr.rooms_auto_enabled ?? 0;
    const overrideCount = wsSummary.manual_overrides_count ?? summaryAttr.manual_overrides_count ?? 0;
    const circadianKelvin = wsSummary.current_circadian_kelvin ?? summaryAttr.current_circadian_kelvin ?? null;

    return {
      totalLights,
      onLights,
      activeLeaves,
      avgPct,
      totalRooms,
      autoRooms,
      overrideCount,
      circadianKelvin,
    };
  }

  _getActiveAlerts() {
    const alerts = Array.isArray(this.config?.alerts) ? this.config.alerts : [];
    return alerts.filter((alert) => {
      if (!alert?.entity || !this.hass?.states?.[alert.entity]) return false;
      const stVal = String(this.hass.states[alert.entity].state);
      if (alert.state !== undefined && alert.state !== null && alert.state !== "") {
        return stVal === String(alert.state);
      }
      if (alert.operator && alert.value !== undefined) {
        const numState = parseFloat(stVal);
        const numVal = parseFloat(alert.value);
        if (isNaN(numState) || isNaN(numVal)) return false;
        switch (alert.operator) {
          case ">": return numState > numVal;
          case "<": return numState < numVal;
          case ">=": return numState >= numVal;
          case "<=": return numState <= numVal;
          case "==": return numState === numVal;
          case "!=": return numState !== numVal;
        }
      }
      return stVal === "on";
    });
  }

  // ==========================================
  // INTERACTION & SERVICE HANDLERS
  // ==========================================

  _toggleLight(entityId, ev = null) {
    if (ev) ev.stopPropagation();
    if (!this.hass || !entityId) return;
    this._fireHaptic("light");
    this.hass.callService("light", "toggle", { entity_id: entityId });
  }

  _toggleFloor(floor, ev = null) {
    if (ev) ev.stopPropagation();
    if (!this.hass || !floor) return;
    this._fireHaptic("medium");
    const activeLeaves = floor.leaves.filter((id) => this._isLightOn(id));
    if (activeLeaves.length > 0) {
      if (floor.entity) {
        this.hass.callService("light", "turn_off", { entity_id: floor.entity });
      } else {
        this.hass.callService("light", "turn_off", { entity_id: activeLeaves });
      }
    } else if (floor.entity) {
      this.hass.callService("light", "turn_on", { entity_id: floor.entity });
    } else if (floor.leaves.length > 0) {
      this.hass.callService("light", "turn_on", { entity_id: floor.leaves });
    }
  }

  _turnOffFloor(floor) {
    if (!this.hass || !floor) return;
    this._fireHaptic("medium");
    if (floor.entity) {
      this.hass.callService("light", "turn_off", { entity_id: floor.entity });
    } else {
      const active = floor.leaves.filter((id) => this._isLightOn(id));
      if (active.length > 0) {
        this.hass.callService("light", "turn_off", { entity_id: active });
      }
    }
  }

  _turnOffAllLights(allLeaves) {
    if (!this.hass) return;
    this._fireHaptic("medium");
    const masterId = this.config?.master_light;
    const hasMaster = Boolean(masterId && this.hass.states?.[masterId]);
    if (hasMaster) {
      this.hass.callService("light", "turn_off", { entity_id: masterId });
    }
    const masterLeaves = hasMaster ? new Set(this._expandLightGroup(masterId)) : new Set();
    const activeOutside = allLeaves.filter(
      (id) => this._isLightOn(id) && (!hasMaster || !masterLeaves.has(id))
    );
    if (activeOutside.length > 0) {
      this.hass.callService("light", "turn_off", { entity_id: activeOutside });
    }
  }

  _onLightSliderInput(entityId, ev) {
    const val = parseInt(ev.target.value, 10);
    this._draggingSliders = { ...this._draggingSliders, [entityId]: val };
  }

  _onLightSliderChange(entityId, ev) {
    const val = parseInt(ev.target.value, 10);
    const next = { ...this._draggingSliders };
    delete next[entityId];
    this._draggingSliders = next;
    this._fireHaptic("light");
    if (val <= 0) {
      this.hass.callService("light", "turn_off", { entity_id: entityId });
    } else {
      this.hass.callService("light", "turn_on", {
        entity_id: entityId,
        brightness_pct: val,
      });
    }
  }

  _onMasterSliderInput(ev) {
    const val = parseInt(ev.target.value, 10);
    this._draggingSliders = { ...this._draggingSliders, __master__: val };
  }

  _onMasterSliderChange(allLeaves, ev) {
    const val = parseInt(ev.target.value, 10);
    const next = { ...this._draggingSliders };
    delete next.__master__;
    this._draggingSliders = next;

    this._fireHaptic("light");
    if (val <= 0) {
      this._turnOffAllLights(allLeaves);
      return;
    }
    const activeLeaves = allLeaves.filter((id) => this._isLightOn(id));
    if (activeLeaves.length > 0) {
      this.hass.callService("light", "turn_on", {
        entity_id: activeLeaves,
        brightness_pct: val,
      });
    }
  }

  _toggleDrawer(mode) {
    this._fireHaptic("light");
    this._drawerMode = this._drawerMode === mode ? null : mode;
    this._syncCountdownTimer();
  }

  _openModal(tab = "lights", floorFilter = null, expandRoomId = null) {
    this._fireHaptic("light");
    this._modalTab = tab || "lights";
    if (floorFilter) {
      this._modalFloorFilter = floorFilter;
    } else if (this._drawerMode) {
      this._modalFloorFilter = this._drawerMode;
    } else {
      this._modalFloorFilter = "active";
    }
    if (expandRoomId) {
      this._expandedEngineRoom = expandRoomId;
    }
    this._modalOpen = true;
    if (!this._wsData) {
      this._fetchFallbackData();
    }
    this._syncCountdownTimer();
  }

  _closeModal() {
    this._fireHaptic("light");
    const overlay = this.shadowRoot?.querySelector(".popup-overlay");
    const content = this.shadowRoot?.querySelector(".popup-content");
    if (overlay) overlay.classList.add("closing");
    if (content) content.classList.add("closing");

    clearTimeout(this._closeModalTimer);
    this._closeModalTimer = setTimeout(() => {
      this._modalOpen = false;
      this._confirmResetRoom = null;
      this._syncCountdownTimer();
    }, 180);
  }

  async _callEngineWS(payload, successToast = null) {
    if (!this.hass) return null;
    try {
      const res = await this.hass.callWS(payload);
      if (successToast) this._showToast(successToast);
      if (!this._wsUnsub) {
        await this._fetchFallbackData();
      }
      return res;
    } catch (err) {
      this._showToast(err?.message || "Action failed");
      return null;
    }
  }

  _clearOverride(roomId = null, ev = null) {
    if (ev) ev.stopPropagation();
    this._fireHaptic("medium");
    this._callEngineWS(
      { type: `${ENGINE_DOMAIN}/clear_override`, room_id: roomId },
      roomId ? "Manual override cleared" : "All overrides cleared"
    );
  }

  _toggleRoomAuto(room, ev = null) {
    if (ev) ev.stopPropagation();
    this._fireHaptic("light");
    this._callEngineWS({
      type: `${ENGINE_DOMAIN}/set_room_auto`,
      room_id: room.room_id,
      enabled: !room.is_enabled,
    });
  }

  _toggleRoomCircadian(room, ev = null) {
    if (ev) ev.stopPropagation();
    this._fireHaptic("light");
    this._callEngineWS({
      type: `${ENGINE_DOMAIN}/set_room_circadian`,
      room_id: room.room_id,
      enabled: !room.circadian_enabled,
    });
  }

  _stepTargetLux(room, delta, ev = null) {
    if (ev) ev.stopPropagation();
    this._fireHaptic("light");
    const nextLux = Math.max(0, Math.min(1000, (room.seed_target_lux ?? 40) + delta));
    this._callEngineWS({
      type: `${ENGINE_DOMAIN}/set_target_lux`,
      room_id: room.room_id,
      target_lux: nextLux,
    });
  }

  async _calibrateRoom(roomId) {
    this._fireHaptic("medium");
    this._calibratingRoom = roomId;
    await this._callEngineWS(
      { type: `${ENGINE_DOMAIN}/calibrate_room`, room_id: roomId },
      `Calibration started for ${roomId.replace(/_/g, " ")}`
    );
    setTimeout(() => {
      if (this._calibratingRoom === roomId) {
        this._calibratingRoom = null;
      }
    }, 2500);
  }

  async _handleResetClick(roomId) {
    this._fireHaptic("medium");
    if (this._confirmResetRoom !== roomId) {
      this._confirmResetRoom = roomId;
      clearTimeout(this._confirmResetTimer);
      this._confirmResetTimer = setTimeout(() => {
        if (this._confirmResetRoom === roomId) {
          this._confirmResetRoom = null;
        }
      }, 4000);
      return;
    }
    this._confirmResetRoom = null;
    clearTimeout(this._confirmResetTimer);
    const resetType = this._resetTargetByRoom[roomId] || "all";
    await this._callEngineWS(
      {
        type: `${ENGINE_DOMAIN}/reset_learning_data`,
        room_id: roomId,
        reset_type: resetType,
      },
      `Reset ${resetType} for ${roomId.replace(/_/g, " ")}`
    );
  }

  _toggleSubsystemEntity(entityId) {
    if (!this.hass || !entityId) return;
    this._fireHaptic("light");
    this.hass.callService("switch", "toggle", { entity_id: entityId });
  }

  _toggleHolidayBannerLights(holidayInfo, ev = null) {
    if (ev) ev.stopPropagation();
    if (!this.hass) return;
    this._fireHaptic("medium");
    const participating = this._resolveHolidayParticipatingLeaves(holidayInfo);
    const anyOn = participating.some((id) => this._isLightOn(id));
    if (anyOn) {
      this.hass.callService("light", "turn_off", { entity_id: participating });
    } else {
      this._callEngineWS(
        {
          type: `${ENGINE_DOMAIN}/apply_holiday`,
          holiday_id: holidayInfo.active_holiday?.id || null,
        },
        `Applied ${holidayInfo.active_holiday?.name || "holiday"} lighting`
      );
    }
  }

  _resolveHolidayParticipatingLeaves(holidayInfo) {
    const raw = holidayInfo?.participating_lights || [];
    const leaves = [];
    for (const id of raw) {
      for (const leaf of this._expandLightGroup(id)) {
        if (!leaves.includes(leaf)) leaves.push(leaf);
      }
    }
    return leaves;
  }

  _handleRingPointerDown(floor) {
    clearTimeout(this._ringHoldTimer);
    this._ringHoldFired = false;
    this._ringHoldTimer = setTimeout(() => {
      this._ringHoldFired = true;
      this._toggleFloor(floor);
    }, 450);
  }

  _handleRingPointerUp(floor) {
    clearTimeout(this._ringHoldTimer);
    if (!this._ringHoldFired) {
      this._toggleDrawer(floor.id);
    }
    this._ringHoldFired = false;
  }

  _handleRingPointerCancel() {
    clearTimeout(this._ringHoldTimer);
    this._ringHoldFired = false;
  }

  // ==========================================
  // RENDERING HELPERS
  // ==========================================

  _renderSummaryStrip(metrics, floors, leafToRoom) {
    const anyOn = metrics.onLights > 0;
    const alerts = this._getActiveAlerts();
    const overrideRoom = (this._wsData?.rooms || []).find((r) => r.override_active);

    return html`
      <div class="light-summary-strip">
        <div class="summary-strip-left">
          <span class="summary-status-dot ${anyOn ? "on" : ""}"></span>
          <button
            type="button"
            class="strip-active-pill ${this._drawerMode === "active" ? "drawer-open" : ""} ${anyOn ? "lit" : ""}"
            @click=${() => this._toggleDrawer("active")}
            title="Tap to expand all currently ON lights"
          >
            ${metrics.onLights}/${metrics.totalLights} On
          </button>
          ${metrics.totalRooms > 0
            ? html`
                <span class="summary-sep">•</span>
                <button
                  type="button"
                  class="strip-link-btn"
                  @click=${() => this._openModal("engine")}
                  title="Open Smart Light Engine Controls"
                >
                  ${metrics.autoRooms}/${metrics.totalRooms} Auto
                </button>
              `
            : ""}
          ${metrics.circadianKelvin
            ? html`
                <span class="summary-sep">•</span>
                <span class="strip-metric-text" title="Current Sun-Elevation Circadian Target">
                  ${metrics.circadianKelvin}K
                </span>
              `
            : ""}
        </div>

        <div class="summary-strip-right">
          ${metrics.overrideCount > 0
            ? html`
                <button
                  type="button"
                  class="zone-inline-chip warning clickable"
                  @click=${() =>
                    this._openModal("engine", null, overrideRoom?.room_id || null)}
                  title="Manual override active — tap to manage or clear"
                >
                  ${metrics.overrideCount} Override
                </button>
              `
            : ""}

          ${alerts.map((alert) => {
            const color = alert.color || "var(--info-color, #0284c7)";
            const label =
              alert.label ||
              this.hass?.states?.[alert.entity]?.attributes?.friendly_name ||
              "Alert";
            return html`
              <button
                type="button"
                class="alert-pill-btn"
                style="color:${color}; border-color:color-mix(in srgb, ${color} 40%, transparent); background:color-mix(in srgb, ${color} 15%, transparent);"
                @click=${(ev) => {
                  ev.stopPropagation();
                  this._executeActionConfig(
                    alert.tap_action || { action: "more-info", entity: alert.entity },
                    alert.entity
                  );
                }}
                title="${label}"
              >
                ${alert.icon
                  ? html`<ha-icon icon="${alert.icon}" style="--mdc-icon-size:14px;"></ha-icon>`
                  : ""}
                <span>${label}</span>
              </button>
            `;
          })}

          ${anyOn
            ? html`
                <button
                  type="button"
                  class="all-off-pill-btn"
                  @click=${() => this._turnOffAllLights(this._getAllLeafLights(floors))}
                  title="Turn off all lights"
                >
                  <ha-icon icon="mdi:power" style="--mdc-icon-size:14px;"></ha-icon>
                  <span>All Off</span>
                </button>
              `
            : ""}

          ${this.config?.stats_navigation_path
            ? html`
                <button
                  type="button"
                  class="icon-circle-btn"
                  @click=${() => this._navigateTo(this.config.stats_navigation_path)}
                  title="Open Light Stats"
                >
                  <ha-icon icon="mdi:chart-line" style="--mdc-icon-size:16px;"></ha-icon>
                </button>
              `
            : ""}

          <button
            type="button"
            class="icon-circle-btn"
            @click=${() => this._openModal("lights")}
            title="Open Lighting Command Center"
          >
            <ha-icon icon="mdi:tune-variant" style="--mdc-icon-size:16px;"></ha-icon>
          </button>
        </div>
      </div>
    `;
  }

  _renderHolidayBanner() {
    if (this.config?.show_holiday_banner === false) return "";
    const holidayInfo = this._wsData?.holiday_exterior;
    const sensorObj = this.hass?.states?.["sensor.active_holiday"];
    const activeHoliday = holidayInfo?.active_holiday;
    const holidayEnabled =
      holidayInfo?.holiday_enabled ??
      (this.hass?.states?.["switch.holiday_lighting"]?.state !== "off");

    let name = activeHoliday?.name;
    let phrase = activeHoliday?.phrase;
    let icon = activeHoliday?.icon;
    let themeColor = activeHoliday?.theme_color;

    if (!activeHoliday && sensorObj && sensorObj.state && sensorObj.state !== "unknown" && sensorObj.state !== "unavailable") {
      name = sensorObj.state;
      phrase = sensorObj.attributes?.current_phrase || name;
      icon = sensorObj.attributes?.current_icon || "mdi:calendar-star";
      themeColor = sensorObj.attributes?.current_theme || "#b45f06";
    }

    if (!holidayEnabled || !name) return "";

    const safeTheme = /^#[0-9a-f]{3,8}$/i.test(String(themeColor || "")) ? themeColor : "#b45f06";
    const participating =
      holidayInfo?.participating_lights?.length > 0
        ? this._resolveHolidayParticipatingLeaves(holidayInfo)
        : (sensorObj?.attributes?.participating_lights || []).flatMap((id) =>
            this._expandLightGroup(id)
          );
    const deduped = [...new Set(participating)];
    const onCount = deduped.filter((id) => this._isLightOn(id)).length;
    const isLit = onCount > 0;
    const subLabel =
      deduped.length === 0
        ? `${name} active`
        : isLit
          ? `${onCount} of ${deduped.length} holiday light${deduped.length === 1 ? "" : "s"} on`
          : `${name} · Ready at sunset`;

    return html`
      <div
        class="holiday-banner ${isLit ? "lit" : "standby"}"
        style="${isLit
          ? `background:${safeTheme}; border-color:${safeTheme}; color:#ffffff;`
          : `background:color-mix(in srgb, ${safeTheme} 11%, transparent); border-color:${safeTheme};`}"
        @click=${() => this._openModal("holiday")}
        title="Tap to manage Holiday & Exterior Lighting"
      >
        <div class="holiday-banner-left">
          <div
            class="holiday-icon-badge"
            style="${isLit
              ? "background:rgba(255,255,255,0.20); color:#ffffff;"
              : `background:${safeTheme}; color:#ffffff;`}"
          >
            <ha-icon icon="${icon || "mdi:calendar-star"}" style="--mdc-icon-size:17px;"></ha-icon>
          </div>
          <div class="holiday-text-wrap">
            <div class="holiday-phrase">${phrase || name}</div>
            <div class="holiday-sub">${subLabel}</div>
          </div>
        </div>
        ${deduped.length > 0
          ? html`
              <button
                type="button"
                class="holiday-action-btn"
                style="${isLit
                  ? "background:rgba(255,255,255,0.18); border-color:rgba(255,255,255,0.45); color:#ffffff;"
                  : `border-color:${safeTheme}; color:${safeTheme}; background:transparent;`}"
                @click=${(ev) =>
                  this._toggleHolidayBannerLights(
                    holidayInfo || { active_holiday: { id: name }, participating_lights: deduped },
                    ev
                  )}
              >
                ${isLit ? "Turn Off" : "Turn On"}
              </button>
            `
          : ""}
      </div>
    `;
  }

  _renderMasterDimmer(metrics, allLeaves) {
    if (this.config?.show_master_dimmer === false) return "";
    const anyOn = metrics.onLights > 0;
    return html`
      <div class="master-dimmer-row">
        <span class="master-label">Master</span>
        <div class="slider-track">
          <div class="slider-fill master" style="width:${metrics.avgPct}%;"></div>
          <input
            type="range"
            min="0"
            max="100"
            .value=${String(metrics.avgPct)}
            ?disabled=${!anyOn}
            class="dimmer-range"
            aria-label="Master brightness of active lights"
            @input=${this._onMasterSliderInput}
            @change=${(ev) => this._onMasterSliderChange(allLeaves, ev)}
          />
        </div>
        <span class="master-pct ${anyOn ? "lit" : ""}">${anyOn ? `${metrics.avgPct}%` : "Off"}</span>
      </div>
    `;
  }

  _renderFloorTiles(floors, leafToRoom) {
    const isOddCount = floors.length % 2 === 1;
    return html`
      <div class="floor-tiles-grid">
        ${floors.map((f, idx) => {
          const fs = this._getFloorStats(f, leafToRoom);
          const isOn = fs.on > 0;
          const isSelected = this._drawerMode === f.id;
          const spanFull = isOddCount && idx === floors.length - 1;
          return html`
            <div
              class="light-zone-card tile ${isOn ? "lit" : ""} ${isSelected ? "selected" : ""} ${spanFull ? "span-2" : ""}"
              @click=${() => this._toggleDrawer(f.id)}
              title="Tap to expand ${f.name} lights"
            >
              <div class="tile-main">
                <div class="tile-identity">
                  <div class="light-zone-icon-wrap compact ${isOn ? "lit" : ""}">
                    <ha-icon icon="${f.icon}" style="--mdc-icon-size:18px;"></ha-icon>
                  </div>
                  <div class="tile-text">
                    <div class="tile-name-row">
                      <span class="tile-name">${f.name}</span>
                      ${fs.hasOverride
                        ? html`<span class="override-dot" title="Manual override active"></span>`
                        : ""}
                    </div>
                    <div class="tile-sub ${isOn ? "lit" : ""}">
                      <span>${fs.on}/${fs.total} on</span>
                      ${isSelected
                        ? html`<ha-icon icon="mdi:chevron-down" style="--mdc-icon-size:14px;"></ha-icon>`
                        : ""}
                    </div>
                  </div>
                </div>
                <div class="tile-controls">
                  <span class="tile-pct ${isOn ? "lit" : ""}">${isOn ? `${fs.pct}%` : "Off"}</span>
                  <button
                    type="button"
                    class="floor-power-btn ${isOn ? "lit" : ""}"
                    @click=${(ev) => this._toggleFloor(f, ev)}
                    title="Toggle all ${f.name} lights"
                  >
                    <ha-icon icon="mdi:power" style="--mdc-icon-size:14px;"></ha-icon>
                  </button>
                </div>
              </div>
              <div class="tile-hairline">
                <div class="tile-hairline-fill" style="width:${fs.pct}%;"></div>
              </div>
            </div>
          `;
        })}
      </div>
    `;
  }

  _renderFloorRings(floors, leafToRoom) {
    const r = 16;
    const c = 2 * Math.PI * r;
    return html`
      <div class="floor-rings-grid" style="grid-template-columns:repeat(${Math.min(5, Math.max(1, floors.length))}, minmax(0, 1fr));">
        ${floors.map((f) => {
          const fs = this._getFloorStats(f, leafToRoom);
          const isOn = fs.on > 0;
          const isSelected = this._drawerMode === f.id;
          const dash = (fs.pct / 100) * c;
          return html`
            <button
              type="button"
              class="ring-tile-btn ${isSelected ? "selected" : ""}"
              @pointerdown=${() => this._handleRingPointerDown(f)}
              @pointerup=${() => this._handleRingPointerUp(f)}
              @pointercancel=${() => this._handleRingPointerCancel()}
              @pointerleave=${() => this._handleRingPointerCancel()}
              title="Tap: expand ${f.name} • Hold: toggle ${f.name}"
            >
              <div class="ring-wrap">
                <svg class="ring-svg" viewBox="0 0 40 40">
                  <circle
                    cx="20"
                    cy="20"
                    r="${r}"
                    fill="none"
                    stroke="${isOn ? "rgba(148,163,184,0.22)" : "rgba(148,163,184,0.14)"}"
                    stroke-width="3.2"
                  ></circle>
                  <circle
                    cx="20"
                    cy="20"
                    r="${r}"
                    fill="none"
                    stroke="#f59e0b"
                    stroke-width="3.2"
                    stroke-linecap="round"
                    stroke-opacity="${fs.pct > 0 ? 1 : 0}"
                    stroke-dasharray="${dash} ${c}"
                  ></circle>
                </svg>
                <span class="ring-val ${isOn ? "lit" : ""}">${isOn ? `${fs.pct}%` : "Off"}</span>
              </div>
              <span class="ring-name ${isOn || isSelected ? "lit" : ""}">${f.name}</span>
              <span class="ring-count ${isOn ? "lit" : ""}">
                ${fs.on}/${fs.total}
                ${fs.hasOverride ? html`<span class="override-dot"></span>` : ""}
              </span>
            </button>
          `;
        })}
      </div>
    `;
  }

  _renderFloorRows(floors, leafToRoom) {
    return html`
      <div class="floor-rows-stack">
        ${floors.map((f) => {
          const fs = this._getFloorStats(f, leafToRoom);
          const isOn = fs.on > 0;
          const isSelected = this._drawerMode === f.id;
          return html`
            <div
              class="light-zone-card row ${isOn ? "lit" : ""} ${isSelected ? "selected" : ""}"
              @click=${() => this._toggleDrawer(f.id)}
              title="Tap to expand ${f.name} lights"
            >
              <div class="row-left">
                <div class="light-zone-icon-wrap ${isOn ? "lit" : ""}">
                  <ha-icon icon="${f.icon}" style="--mdc-icon-size:20px;"></ha-icon>
                </div>
                <div class="row-text">
                  <div class="row-title-line">
                    <span class="row-title">${f.name}</span>
                    ${fs.hasOverride
                      ? html`<span class="zone-inline-chip warning">Override</span>`
                      : ""}
                  </div>
                  <div class="row-sub">
                    <span>${fs.on}/${fs.total} lights on</span>
                    <ha-icon
                      icon="${isSelected ? "mdi:chevron-up" : "mdi:chevron-down"}"
                      style="--mdc-icon-size:15px;"
                    ></ha-icon>
                  </div>
                </div>
              </div>
              <div class="row-right">
                <span class="row-pct ${isOn ? "lit" : ""}">${isOn ? `${fs.pct}%` : "Off"}</span>
                <button
                  type="button"
                  class="floor-power-btn ${isOn ? "lit" : ""}"
                  @click=${(ev) => this._toggleFloor(f, ev)}
                  title="Toggle ${f.name}"
                >
                  <ha-icon icon="mdi:power" style="--mdc-icon-size:15px;"></ha-icon>
                </button>
              </div>
            </div>
          `;
        })}
      </div>
    `;
  }

  _renderLightRow(entityId, leafToRoom, leafGroupName, showFloorContext = false, floorNameByLeaf = {}) {
    const isOn = this._isLightOn(entityId);
    const pct = this._getLightPct(entityId);
    const dimmable = this._isLightDimmable(entityId);
    const name = this._getLightName(entityId);
    const room = leafToRoom[entityId];
    const isNotifClaimed = room?.notification_showing && room?.notification_light_entity === entityId;

    const contextParts = [];
    if (showFloorContext && floorNameByLeaf[entityId]) {
      contextParts.push(floorNameByLeaf[entityId]);
    }
    if (room) {
      contextParts.push(room.name);
    } else if (leafGroupName[entityId]) {
      contextParts.push(leafGroupName[entityId]);
    }
    const subText = contextParts.join(" · ");

    return html`
      <div class="light-item-row ${isOn ? "lit" : ""}">
        <div class="light-item-left">
          <button
            type="button"
            class="bulb-toggle-btn ${isOn ? "lit" : ""}"
            @click=${(ev) => this._toggleLight(entityId, ev)}
            title="Toggle ${name}"
          >
            <ha-icon icon="${isOn ? "mdi:lightbulb" : "mdi:lightbulb-outline"}" style="--mdc-icon-size:15px;"></ha-icon>
          </button>
          <div class="light-item-text">
            <div class="light-item-name-row">
              <button
                type="button"
                class="light-name-btn ${isOn ? "lit" : ""}"
                @click=${(ev) => this._showMoreInfo(entityId, ev)}
                title="Open details & color controls for ${entityId}"
              >
                ${name}
              </button>
              ${isNotifClaimed
                ? html`<span class="zone-inline-chip info">Notify</span>`
                : ""}
              ${room?.override_active
                ? html`
                    <button
                      type="button"
                      class="zone-inline-chip warning clickable"
                      @click=${(ev) => this._clearOverride(room.room_id, ev)}
                      title="Clear manual override for ${room.name}"
                    >
                      Override ${this._formatCountdown(this._getOverrideRemainingSec(room))} ✕
                    </button>
                  `
                : ""}
            </div>
            ${subText ? html`<div class="light-item-sub">${subText}</div>` : ""}
          </div>
        </div>

        <div class="light-item-right">
          ${dimmable
            ? html`
                <div class="slider-track small">
                  <div class="slider-fill" style="width:${pct}%;"></div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    .value=${String(pct)}
                    class="dimmer-range"
                    aria-label="${name} brightness"
                    @input=${(ev) => this._onLightSliderInput(entityId, ev)}
                    @change=${(ev) => this._onLightSliderChange(entityId, ev)}
                  />
                </div>
                <span class="light-pct-label ${isOn ? "lit" : ""}">${isOn ? `${pct}%` : "Off"}</span>
              `
            : html`
                <button
                  type="button"
                  class="onoff-chip ${isOn ? "lit" : ""}"
                  @click=${(ev) => this._toggleLight(entityId, ev)}
                >
                  ${isOn ? "On" : "Off"}
                </button>
              `}
        </div>
      </div>
    `;
  }

  _renderInlineDrawer(floors, allLeaves, leafToRoom, leafGroupName) {
    if (!this._drawerMode) return "";
    const isActiveMode = this._drawerMode === "active";
    const targetFloor = isActiveMode ? null : floors.find((f) => f.id === this._drawerMode);
    if (!isActiveMode && !targetFloor) return "";

    const floorNameByLeaf = {};
    floors.forEach((f) => {
      f.leaves.forEach((lid) => {
        if (!floorNameByLeaf[lid]) floorNameByLeaf[lid] = f.name;
      });
    });

    let list = isActiveMode
      ? allLeaves.filter((id) => this._isLightOn(id))
      : targetFloor.leaves.filter((id) => !this._drawerOnOnly || this._isLightOn(id));

    list = [...list].sort((a, b) => Number(this._isLightOn(b)) - Number(this._isLightOn(a)));

    const floorStats = targetFloor ? this._getFloorStats(targetFloor, leafToRoom) : null;
    const title = isActiveMode
      ? `Active Lights • ${list.length} on`
      : `${targetFloor.name} • ${floorStats.on}/${floorStats.total} on`;

    return html`
      <div class="light-drawer">
        <div class="drawer-header">
          <div class="drawer-title-group">
            <span class="drawer-title">${title}</span>
            ${!isActiveMode
              ? html`
                  <button
                    type="button"
                    class="drawer-filter-btn ${this._drawerOnOnly ? "active" : ""}"
                    @click=${() => {
                      this._fireHaptic("light");
                      this._drawerOnOnly = !this._drawerOnOnly;
                    }}
                  >
                    ${this._drawerOnOnly ? "On Only" : "All"}
                  </button>
                `
              : ""}
          </div>
          <div class="drawer-actions">
            ${!isActiveMode && floorStats.on > 0
              ? html`
                  <button
                    type="button"
                    class="floor-off-pill-btn"
                    @click=${() => this._turnOffFloor(targetFloor)}
                  >
                    Floor Off
                  </button>
                `
              : ""}
            <button
              type="button"
              class="drawer-manage-btn"
              @click=${() =>
                this._openModal("lights", isActiveMode ? "active" : targetFloor.id)}
              title="Open full room & Smart Light Engine controls"
            >
              <span>Manage</span>
              <ha-icon icon="mdi:open-in-new" style="--mdc-icon-size:13px;"></ha-icon>
            </button>
            <button
              type="button"
              class="drawer-close-btn"
              @click=${() => {
                this._fireHaptic("light");
                this._drawerMode = null;
                this._syncCountdownTimer();
              }}
              title="Collapse drawer"
            >
              <ha-icon icon="mdi:close" style="--mdc-icon-size:16px;"></ha-icon>
            </button>
          </div>
        </div>

        <div class="drawer-list thin-scroll">
          ${list.length > 0
            ? list.map((lid) =>
                this._renderLightRow(lid, leafToRoom, leafGroupName, isActiveMode, floorNameByLeaf)
              )
            : html`<div class="drawer-empty">No lights currently on in this view.</div>`}
        </div>
      </div>
    `;
  }

  _renderFooterStrip() {
    if (this.config?.show_engine_footer === false) return "";
    const duskOn = this.hass?.states?.["switch.exterior_dusk_to_dawn_lighting"]?.state === "on";
    const holidayOn = this.hass?.states?.["switch.holiday_lighting"]?.state === "on";
    const awayOn = this.hass?.states?.["switch.simulate_presence_away_mode"]?.state === "on";
    const activeHolidayName =
      this._wsData?.holiday_exterior?.active_holiday?.name ||
      (this.hass?.states?.["sensor.active_holiday"]?.state !== "unknown"
        ? this.hass?.states?.["sensor.active_holiday"]?.state
        : null) ||
      "Holiday";

    return html`
      <div class="engine-footer-strip">
        <div class="footer-chips">
          ${this.hass?.states?.["switch.exterior_dusk_to_dawn_lighting"]
            ? html`
                <button
                  type="button"
                  class="footer-chip ${duskOn ? "sky" : ""}"
                  @click=${() =>
                    this._toggleSubsystemEntity("switch.exterior_dusk_to_dawn_lighting")}
                >
                  Dusk-Dawn
                </button>
              `
            : ""}
          ${this.hass?.states?.["switch.holiday_lighting"]
            ? html`
                <button
                  type="button"
                  class="footer-chip ${holidayOn ? "amber" : ""}"
                  @click=${() => this._toggleSubsystemEntity("switch.holiday_lighting")}
                >
                  ${activeHolidayName}
                </button>
              `
            : ""}
          ${this.hass?.states?.["switch.simulate_presence_away_mode"]
            ? html`
                <button
                  type="button"
                  class="footer-chip ${awayOn ? "amber-strong" : ""}"
                  @click=${() => this._toggleSubsystemEntity("switch.simulate_presence_away_mode")}
                >
                  Away Sim${awayOn ? " · Active" : ""}
                </button>
              `
            : ""}
        </div>
        <button
          type="button"
          class="footer-command-link"
          @click=${() => this._openModal("engine")}
        >
          Command Center →
        </button>
      </div>
    `;
  }

  // ==========================================
  // MODAL COMMAND CENTER (4 TABS)
  // ==========================================

  _renderYieldCurveSvg(room) {
    const curves = room.room_curves || {};
    const points = Object.entries(curves)
      .map(([pct, lux]) => [parseFloat(pct), parseFloat(lux)])
      .filter(([pct, lux]) => !isNaN(pct) && !isNaN(lux))
      .sort((a, b) => a[0] - b[0]);

    const displayPts =
      points.length >= 2
        ? points
        : [25, 50, 75, 100].map((pct) => [pct, Math.round(pct * (room.lux_yield || 0.2) * 10) / 10]);

    const maxLux = Math.max(20, ...displayPts.map(([, lux]) => lux)) * 1.12;
    const coords = displayPts.map(([pct, lux]) => {
      const x = 22 + (Math.max(0, Math.min(100, pct)) / 100) * 224;
      const y = 62 - (lux / maxLux) * 44;
      return { pct: Math.round(pct), lux: Math.round(lux * 10) / 10, x, y };
    });

    const polylinePts = coords.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    // Pick up to 5 evenly spaced labels so crowded curves remain readable
    const labelStep = Math.max(1, Math.ceil(coords.length / 5));

    return html`
      <div class="yield-chart-box">
        <svg viewBox="0 0 268 80" class="yield-svg">
          <line x1="20" y1="62" x2="250" y2="62" stroke="rgba(148,163,184,0.28)" stroke-width="1"></line>
          <line x1="20" y1="36" x2="250" y2="36" stroke="rgba(148,163,184,0.16)" stroke-dasharray="3 3" stroke-width="1"></line>
          <polyline
            fill="none"
            stroke="#f59e0b"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            points="${polylinePts}"
          ></polyline>
          ${coords.map((p, idx) => {
            const showLabel = idx === coords.length - 1 || idx % labelStep === 0;
            return svg`
              <circle cx="${p.x}" cy="${p.y}" r="3.2" fill="#f59e0b" stroke="var(--ha-card-background, #1c1c1e)" stroke-width="1.5"></circle>
              ${showLabel
                ? svg`
                    <text x="${p.x}" y="${Math.max(12, p.y - 7)}" text-anchor="middle" fill="var(--primary-text-color)" font-size="11" font-weight="700">${p.lux}</text>
                    <text x="${p.x}" y="76" text-anchor="middle" fill="var(--secondary-text-color)" font-size="11">${p.pct}%</text>
                  `
                : ""}
            `;
          })}
        </svg>
        ${points.length < 2
          ? html`<div class="yield-fallback-note">Estimated from default lux ratio (${room.lux_yield} lx/%)</div>`
          : ""}
      </div>
    `;
  }

  _renderModalLightsTab(floors, allLeaves, leafToRoom, leafGroupName, metrics) {
    const isActiveOnly = this._modalFloorFilter === "active";
    const targetFloor = isActiveOnly
      ? null
      : floors.find((f) => f.id === this._modalFloorFilter) || floors[0] || null;
    const effectiveFilter = isActiveOnly ? "active" : (targetFloor?.id || "active");

    const sourceLeaves = isActiveOnly
      ? allLeaves.filter((id) => this._isLightOn(id))
      : (targetFloor?.leaves || []);

    // Group sourceLeaves into room buckets (engine rooms first, then manual sub-groups)
    const buckets = [];
    const bucketByKey = {};
    for (const lid of sourceLeaves) {
      const room = leafToRoom[lid];
      const key = room ? `engine:${room.room_id}` : `manual:${leafGroupName[lid] || "Other Lights"}`;
      if (!bucketByKey[key]) {
        bucketByKey[key] = {
          key,
          title: room ? room.name : (leafGroupName[lid] || "Other Lights"),
          room: room || null,
          lights: [],
        };
        buckets.push(bucketByKey[key]);
      }
      bucketByKey[key].lights.push(lid);
    }

    return html`
      <div class="modal-filter-pills">
        <button
          type="button"
          class="modal-filter-pill ${effectiveFilter === "active" ? "active" : ""}"
          @click=${() => {
            this._fireHaptic("light");
            this._modalFloorFilter = "active";
          }}
        >
          Active (${metrics.onLights})
        </button>
        ${floors.map(
          (f) => html`
            <button
              type="button"
              class="modal-filter-pill ${effectiveFilter === f.id ? "active" : ""}"
              @click=${() => {
                this._fireHaptic("light");
                this._modalFloorFilter = f.id;
              }}
            >
              ${f.name}
            </button>
          `
        )}
      </div>

      <div class="modal-scroll-area thin-scroll">
        ${buckets.length > 0
          ? buckets.map((b) => {
              const r = b.room;
              const sortedLights = [...b.lights].sort(
                (a, c) => Number(this._isLightOn(c)) - Number(this._isLightOn(a))
              );
              const modeLabel = r
                ? (MODE_LABELS[r.active_mode] || r.active_mode)
                : "Manual";
              return html`
                <div class="passable-section-card">
                  <div class="room-card-header">
                    <div class="room-card-title-group">
                      <span class="room-card-title">${b.title}</span>
                      ${r
                        ? html`
                            <span class="room-lux-readout">
                              ${r.ambient_lux !== null ? `${r.ambient_lux} / ` : "Target "}${r.blended_target_lux ?? r.seed_target_lux} lx
                            </span>
                          `
                        : html`<span class="room-lux-readout">Manual</span>`}
                    </div>

                    ${r
                      ? html`
                          <div class="room-card-controls">
                            ${r.override_active
                              ? html`
                                  <button
                                    type="button"
                                    class="zone-inline-chip warning clickable"
                                    @click=${(ev) => this._clearOverride(r.room_id, ev)}
                                    title="Tap to clear manual override"
                                  >
                                    Override ${this._formatCountdown(this._getOverrideRemainingSec(r))} ✕
                                  </button>
                                `
                              : html`<span class="zone-inline-chip neutral">${modeLabel}</span>`}
                            <button
                              type="button"
                              class="room-pill-toggle ${r.is_enabled ? "green" : ""}"
                              @click=${(ev) => this._toggleRoomAuto(r, ev)}
                            >
                              Auto
                            </button>
                            <button
                              type="button"
                              class="room-pill-toggle ${r.circadian_enabled ? "sky" : ""}"
                              @click=${(ev) => this._toggleRoomCircadian(r, ev)}
                            >
                              Circadian
                            </button>
                          </div>
                        `
                      : ""}
                  </div>

                  <div class="room-lights-list">
                    ${sortedLights.map((lid) =>
                      this._renderLightRow(lid, leafToRoom, leafGroupName, false)
                    )}
                  </div>
                </div>
              `;
            })
          : html`
              <div class="modal-empty-state">
                All lights are currently off. Switch to a floor pill above to turn lights on.
              </div>
            `}
      </div>
    `;
  }

  _renderModalEngineTab(metrics) {
    const rooms = this._wsData?.rooms || [];
    if (rooms.length === 0) {
      return html`
        <div class="modal-empty-state">
          ${this._wsError
            ? `Smart Light Engine data unavailable: ${this._wsError}`
            : "No Smart Light Engine rooms are configured yet."}
        </div>
      `;
    }

    return html`
      <div class="modal-scroll-area thin-scroll">
        <div class="light-kpi-grid">
          <div class="light-kpi-card">
            <span class="kpi-label">ROOMS AUTO</span>
            <span class="kpi-val green">${metrics.autoRooms}/${metrics.totalRooms}</span>
          </div>
          <button
            type="button"
            class="light-kpi-card clickable ${metrics.overrideCount > 0 ? "warn" : ""}"
            @click=${() => metrics.overrideCount > 0 && this._clearOverride(null)}
            title="${metrics.overrideCount > 0 ? "Tap to clear all manual overrides" : "No active manual overrides"}"
          >
            <span class="kpi-label">OVERRIDES</span>
            <span class="kpi-val ${metrics.overrideCount > 0 ? "amber" : ""}">
              ${metrics.overrideCount}${metrics.overrideCount > 0 ? " ✕" : ""}
            </span>
          </button>
          <div class="light-kpi-card">
            <span class="kpi-label">CIRCADIAN</span>
            <span class="kpi-val sky">${metrics.circadianKelvin ? `${metrics.circadianKelvin}K` : "--"}</span>
          </div>
          <div class="light-kpi-card">
            <span class="kpi-label">LEARNED</span>
            <span class="kpi-val">${rooms.filter((r) => r.curve_points_count > 0).length} Rooms</span>
          </div>
        </div>

        <div class="engine-accordions-list">
          ${rooms.map((r) => {
            const isExpanded = this._expandedEngineRoom === r.room_id;
            const selectedReset = this._resetTargetByRoom[r.room_id] || "all";
            const isConfirmingReset = this._confirmResetRoom === r.room_id;
            const isCalibrating = this._calibratingRoom === r.room_id;
            return html`
              <div class="passable-accordion-card ${isExpanded ? "expanded" : ""}">
                <div class="passable-accordion-header" @click=${() => {
                  this._fireHaptic("light");
                  this._expandedEngineRoom = isExpanded ? null : r.room_id;
                }}>
                  <div class="accordion-room-left">
                    <span class="accordion-main-text">${r.name}</span>
                    ${r.override_active
                      ? html`<span class="zone-inline-chip warning">Override ${this._formatCountdown(this._getOverrideRemainingSec(r))}</span>`
                      : html`<span class="accordion-mode-sub">${MODE_LABELS[r.active_mode] || r.active_mode}</span>`}
                    <ha-icon
                      icon="${isExpanded ? "mdi:chevron-up" : "mdi:chevron-down"}"
                      style="--mdc-icon-size:18px; color:var(--secondary-text-color);"
                    ></ha-icon>
                  </div>

                  <div class="accordion-room-controls" @click=${(ev) => ev.stopPropagation()}>
                    <div class="step-controller-pill compact">
                      <button type="button" class="pill-btn" @click=${(ev) => this._stepTargetLux(r, -5, ev)}>-</button>
                      <span class="pill-value">${r.seed_target_lux} lx</span>
                      <button type="button" class="pill-btn" @click=${(ev) => this._stepTargetLux(r, 5, ev)}>+</button>
                    </div>
                    <button
                      type="button"
                      class="room-pill-toggle ${r.is_enabled ? "green" : ""}"
                      @click=${(ev) => this._toggleRoomAuto(r, ev)}
                    >
                      Auto
                    </button>
                    <button
                      type="button"
                      class="room-pill-toggle ${r.circadian_enabled ? "sky" : ""}"
                      @click=${(ev) => this._toggleRoomCircadian(r, ev)}
                    >
                      Circ
                    </button>
                  </div>
                </div>

                ${isExpanded
                  ? html`
                      <div class="passable-accordion-body">
                        <div class="engine-detail-meta">
                          <span class="detail-yield">
                            Yield: <strong>${r.lux_yield} lx/%</strong>
                            ${r.ambient_lux !== null ? ` • Live: ${r.ambient_lux} lx` : ""}
                            • Blended: ${r.blended_target_lux} lx
                          </span>
                          <div class="detail-badges">
                            <span class="zone-inline-chip neutral">Media ${r.media_target_pct}%</span>
                            <span class="zone-inline-chip neutral">Night ${r.late_night_target_pct}%</span>
                            <span class="zone-inline-chip neutral">Timeout ${r.effective_presence_timeout_min}m</span>
                            ${r.override_active
                              ? html`
                                  <button
                                    type="button"
                                    class="zone-inline-chip warning clickable"
                                    @click=${(ev) => this._clearOverride(r.room_id, ev)}
                                  >
                                    Clear Override ✕
                                  </button>
                                `
                              : ""}
                          </div>
                        </div>

                        ${this._renderYieldCurveSvg(r)}

                        <div class="engine-detail-actions">
                          <button
                            type="button"
                            class="primary-action-btn"
                            ?disabled=${isCalibrating}
                            @click=${() => this._calibrateRoom(r.room_id)}
                          >
                            ${isCalibrating ? "Calibrating..." : "Calibrate Curve"}
                          </button>

                          <div class="reset-controls-group">
                            <select
                              class="compact-select"
                              .value=${selectedReset}
                              @change=${(ev) => {
                                this._resetTargetByRoom = {
                                  ...this._resetTargetByRoom,
                                  [r.room_id]: ev.target.value,
                                };
                              }}
                            >
                              ${RESET_TYPE_OPTIONS.map(
                                (opt) => html`<option value="${opt.value}">${opt.label}</option>`
                              )}
                            </select>
                            <button
                              type="button"
                              class="danger-action-btn ${isConfirmingReset ? "confirming" : ""}"
                              @click=${() => this._handleResetClick(r.room_id)}
                            >
                              ${isConfirmingReset ? "Confirm Reset?" : "Reset"}
                            </button>
                          </div>
                        </div>
                      </div>
                    `
                  : ""}
              </div>
            `;
          })}
        </div>
      </div>
    `;
  }

  _renderModalHolidayTab() {
    const holidayInfo = this._wsData?.holiday_exterior || {};
    const catalog = holidayInfo.catalog || [];
    const active = holidayInfo.active_holiday;
    const duskOn =
      this.hass?.states?.["switch.exterior_dusk_to_dawn_lighting"]?.state === "on" ||
      holidayInfo.exterior_enabled;
    const holidayOn =
      this.hass?.states?.["switch.holiday_lighting"]?.state === "on" ||
      holidayInfo.holiday_enabled;
    const decorOn =
      this.hass?.states?.["switch.holiday_decorations"]?.state === "on" ||
      holidayInfo.decorations_enabled;

    const participating = this._resolveHolidayParticipatingLeaves(holidayInfo);
    const anyHolidayLightOn = participating.some((id) => this._isLightOn(id));
    const safeTheme = /^#[0-9a-f]{3,8}$/i.test(String(active?.theme_color || ""))
      ? active.theme_color
      : "#b45f06";

    return html`
      <div class="modal-scroll-area thin-scroll">
        <div class="subsystem-toggle-grid">
          <button
            type="button"
            class="subsystem-toggle-tile ${duskOn ? "sky" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.exterior_dusk_to_dawn_lighting")}
          >
            <span class="subsys-title">Dusk-to-Dawn</span>
            <span class="subsys-state">${duskOn ? "ON" : "OFF"}</span>
          </button>
          <button
            type="button"
            class="subsystem-toggle-tile ${holidayOn ? "amber" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.holiday_lighting")}
          >
            <span class="subsys-title">Holiday Mode</span>
            <span class="subsys-state">${holidayOn ? "ON" : "OFF"}</span>
          </button>
          <button
            type="button"
            class="subsystem-toggle-tile ${decorOn ? "green" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.holiday_decorations")}
          >
            <span class="subsys-title">Decor Plugs</span>
            <span class="subsys-state">${decorOn ? "ON" : "OFF"}</span>
          </button>
        </div>

        ${active
          ? html`
              <div
                class="holiday-hero-card"
                style="background:${safeTheme}; border-color:${safeTheme}; color:#ffffff;"
              >
                <div class="holiday-hero-text">
                  <div class="holiday-hero-kicker">${active.name} · ${active.start_date} to ${active.end_date}</div>
                  <div class="holiday-hero-phrase">${active.phrase || active.name}</div>
                  <div class="holiday-hero-meta">
                    Mode: ${active.light_mode || "rgb"} · ${participating.length} participating light${participating.length === 1 ? "" : "s"}
                  </div>
                </div>
                ${participating.length > 0
                  ? html`
                      <button
                        type="button"
                        class="holiday-hero-btn"
                        @click=${(ev) => this._toggleHolidayBannerLights(holidayInfo, ev)}
                      >
                        ${anyHolidayLightOn ? "Lights Off" : "Turn On"}
                      </button>
                    `
                  : ""}
              </div>
            `
          : html`
              <div class="passable-section-card">
                <div style="font-size:13px; font-weight:600; color:var(--secondary-text-color);">
                  No calendar holiday is currently active today. Preview or apply any holiday below.
                </div>
              </div>
            `}

        <div class="holiday-catalog-list">
          ${catalog.map((h) => {
            const isSel = active && active.id === h.id;
            const swatch = /^#[0-9a-f]{3,8}$/i.test(String(h.theme_color || ""))
              ? h.theme_color
              : "#b45f06";
            return html`
              <div class="holiday-catalog-row ${isSel ? "active" : ""}">
                <div class="holiday-cat-left">
                  <span class="holiday-swatch" style="background:${swatch};"></span>
                  <div class="holiday-cat-text">
                    <div class="holiday-cat-name">
                      ${h.name}
                      <span class="holiday-cat-dates">· ${h.start_date}–${h.end_date}</span>
                    </div>
                    <div class="holiday-cat-sub">${h.phrase || h.light_mode}</div>
                  </div>
                </div>
                <div class="holiday-cat-actions">
                  <button
                    type="button"
                    class="catalog-btn"
                    @click=${() =>
                      this._callEngineWS(
                        { type: `${ENGINE_DOMAIN}/preview_holiday`, holiday_id: h.id, duration_sec: 60 },
                        `Previewing ${h.name} (60s)`
                      )}
                  >
                    Preview 60s
                  </button>
                  <button
                    type="button"
                    class="catalog-btn ${isSel ? "primary" : ""}"
                    @click=${() =>
                      this._callEngineWS(
                        { type: `${ENGINE_DOMAIN}/apply_holiday`, holiday_id: h.id },
                        `Applied ${h.name}`
                      )}
                  >
                    Apply
                  </button>
                </div>
              </div>
            `;
          })}
        </div>
      </div>
    `;
  }

  _renderModalAwayTab() {
    const sim = this._wsData?.presence_simulation || {};
    const masterEnabled =
      this.hass?.states?.["switch.presence_simulation"]?.state === "on" || sim.enabled;
    const isActive =
      this.hass?.states?.["switch.simulate_presence_away_mode"]?.state === "on" || sim.is_on;
    const configuredLights = sim.configured_lights || [];
    const activeSimSet = new Set(sim.active_simulated_lights || []);
    const statusText = sim.status ? String(sim.status) : (isActive ? "simulating" : "idle");

    return html`
      <div class="modal-scroll-area thin-scroll">
        <div class="away-hero-card ${isActive ? "active" : ""}">
          <div class="away-hero-left">
            <div class="light-zone-icon-wrap ${isActive ? "lit" : ""}">
              <ha-icon icon="mdi:shield-home" style="--mdc-icon-size:20px;"></ha-icon>
            </div>
            <div>
              <div class="away-hero-title">Presence Simulation: ${statusText}</div>
              <div class="away-hero-sub">
                ${sim.next_event
                  ? `Next event: ${sim.next_event.entity_id || ""} (${sim.next_event.time || ""})`
                  : isActive
                    ? `${activeSimSet.size} simulated light${activeSimSet.size === 1 ? "" : "s"} active`
                    : "Standby until Home State switches to Away"}
              </div>
            </div>
          </div>
          <button
            type="button"
            class="away-toggle-btn ${isActive ? "active" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.simulate_presence_away_mode")}
          >
            ${isActive ? "Stop Sim" : "Start Sim"}
          </button>
        </div>

        <div class="subsystem-toggle-grid two-col">
          <button
            type="button"
            class="subsystem-toggle-tile ${masterEnabled ? "green" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.presence_simulation")}
          >
            <span class="subsys-title">Simulation Function</span>
            <span class="subsys-state">${masterEnabled ? "ON" : "OFF"}</span>
          </button>
          <button
            type="button"
            class="subsystem-toggle-tile ${isActive ? "amber" : ""}"
            @click=${() => this._toggleSubsystemEntity("switch.simulate_presence_away_mode")}
          >
            <span class="subsys-title">Simulate Away Mode</span>
            <span class="subsys-state">${isActive ? "ACTIVE" : "IDLE"}</span>
          </button>
        </div>

        <div class="away-meta-chips">
          <span class="zone-inline-chip neutral">Mode: ${sim.mode || "hybrid"}</span>
          <span class="zone-inline-chip neutral">Lookback: ${sim.lookback_days ?? 7}d</span>
          <span class="zone-inline-chip neutral">Jitter: ±${sim.jitter_minutes ?? 15}m</span>
          ${sim.label ? html`<span class="zone-inline-chip neutral">Label: ${sim.label}</span>` : ""}
        </div>

        <div class="passable-section-card">
          <div class="passable-section-header">
            <span class="passable-section-title">Participating Lights (${configuredLights.length})</span>
          </div>
          ${configuredLights.length > 0
            ? html`
                <div class="away-lights-grid">
                  ${configuredLights.map((eid) => {
                    const simLit = activeSimSet.has(eid) || (isActive && this._isLightOn(eid));
                    return html`
                      <button
                        type="button"
                        class="away-light-chip ${simLit ? "lit" : ""}"
                        @click=${(ev) => this._showMoreInfo(eid, ev)}
                      >
                        <span class="away-light-dot ${simLit ? "lit" : ""}"></span>
                        <span class="away-light-name">${this._getLightName(eid)}</span>
                      </button>
                    `;
                  })}
                </div>
              `
            : html`<div class="drawer-empty">Tag lights with label "${sim.label || "lights_presence_simulation"}" to include them.</div>`}
        </div>
      </div>
    `;
  }

  _renderModal(floors, allLeaves, leafToRoom, leafGroupName, metrics) {
    if (!this._modalOpen) return "";
    const anyOn = metrics.onLights > 0;
    const tabs = [
      { id: "lights", label: "Lights", icon: "mdi:lightbulb-group" },
      { id: "engine", label: "Engine", icon: "mdi:brain" },
      { id: "holiday", label: "Holiday & Ext", icon: "mdi:calendar-star" },
      { id: "away", label: "Away Sim", icon: "mdi:shield-home" },
    ];

    return html`
      <div
        class="popup-overlay"
        @click=${(ev) => {
          if (ev.target === ev.currentTarget) this._closeModal();
        }}
      >
        <div class="popup-content">
          <div class="drag-handle"></div>

          <div class="popup-header">
            <div class="popup-header-left">
              <div class="light-zone-icon-wrap ${anyOn ? "lit" : ""}">
                <ha-icon icon="mdi:lightbulb-multiple" style="--mdc-icon-size:20px;"></ha-icon>
              </div>
              <div>
                <h3>Lighting Command Center</h3>
                <div class="popup-header-sub">
                  ${metrics.onLights}/${metrics.totalLights} on
                  ${metrics.totalRooms > 0 ? ` • ${metrics.autoRooms}/${metrics.totalRooms} Auto` : ""}
                  ${metrics.circadianKelvin ? ` • ${metrics.circadianKelvin}K` : ""}
                </div>
              </div>
            </div>
            <div class="popup-header-actions">
              ${anyOn
                ? html`
                    <button
                      type="button"
                      class="all-off-pill-btn"
                      @click=${() => this._turnOffAllLights(allLeaves)}
                    >
                      <ha-icon icon="mdi:power" style="--mdc-icon-size:14px;"></ha-icon>
                      <span>All Off</span>
                    </button>
                  `
                : ""}
              <button
                type="button"
                class="close-button"
                @click=${() => this._closeModal()}
                aria-label="Close"
              >
                <ha-icon icon="mdi:close"></ha-icon>
              </button>
            </div>
          </div>

          <div class="popup-tabs">
            ${tabs.map(
              (t) => html`
                <button
                  type="button"
                  class="popup-tab ${this._modalTab === t.id ? "active-tab" : ""}"
                  @click=${() => {
                    this._fireHaptic("light");
                    this._modalTab = t.id;
                  }}
                >
                  <ha-icon icon="${t.icon}"></ha-icon>
                  <span>${t.label}</span>
                </button>
              `
            )}
          </div>

          ${this._modalTab === "lights"
            ? this._renderModalLightsTab(floors, allLeaves, leafToRoom, leafGroupName, metrics)
            : this._modalTab === "engine"
              ? this._renderModalEngineTab(metrics)
              : this._modalTab === "holiday"
                ? this._renderModalHolidayTab()
                : this._renderModalAwayTab()}
        </div>
      </div>
    `;
  }

  render() {
    if (!this.hass || !this.config) return html``;

    const c = this.config;
    const floors = this._resolveFloors();
    const allLeaves = this._getAllLeafLights(floors);
    const { leafToRoom } = this._buildEngineRoomMaps();
    const leafGroupName = this._buildLeafSubgroupLabels(floors);
    const metrics = this._getSummaryMetrics(allLeaves);
    const layout = c.layout || "tiles";

    return html`
      <ha-card>
        ${c.show_header !== false
          ? html`
              <div class="header">
                <div class="header-top-row">
                  <h1 class="title">
                    <ha-icon
                      icon="mdi:lightbulb-multiple-outline"
                      style="margin-right:8px; color: var(--primary-color);"
                    ></ha-icon>
                    ${c.title || "Lighting"}
                  </h1>
                </div>
                <div class="header-subtitle-row">
                  <p class="subtitle">
                    ${metrics.onLights} of ${metrics.totalLights} lights on
                    ${metrics.totalRooms > 0 ? ` • ${metrics.autoRooms}/${metrics.totalRooms} Auto` : ""}
                  </p>
                </div>
              </div>
            `
          : ""}

        <div class="card-content ${c.show_header === false ? "no-header" : ""}">
          ${c.show_summary_strip !== false
            ? this._renderSummaryStrip(metrics, floors, leafToRoom)
            : ""}

          ${this._renderHolidayBanner()}

          ${this._renderMasterDimmer(metrics, allLeaves)}

          ${floors.length > 0
            ? layout === "rings"
              ? this._renderFloorRings(floors, leafToRoom)
              : layout === "rows"
                ? this._renderFloorRows(floors, leafToRoom)
                : this._renderFloorTiles(floors, leafToRoom)
            : html`<div class="drawer-empty">No lights discovered yet.</div>`}

          ${this._renderInlineDrawer(floors, allLeaves, leafToRoom, leafGroupName)}

          ${this._renderFooterStrip()}
        </div>

        ${this._toastMsg ? html`<div class="card-toast">${this._toastMsg}</div>` : ""}

        ${this._renderModal(floors, allLeaves, leafToRoom, leafGroupName, metrics)}
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      ha-card {
        border-radius: var(--ha-card-border-radius, 12px);
        background: var(--ha-card-background, var(--card-background-color, #fff));
        box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, 0.1));
        overflow: hidden;
        color: var(--primary-text-color);
        position: relative;
      }

      /* HEADER (matches passable-hvac-card) */
      .header {
        padding: 16px 16px 14px;
        display: flex;
        flex-direction: column;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        margin-bottom: 12px;
        gap: 4px;
      }
      .header-top-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
      }
      .title {
        font-size: 24px;
        font-weight: 500;
        margin: 0;
        letter-spacing: -0.01em;
        display: flex;
        align-items: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .header-subtitle-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
        margin-top: 2px;
      }
      .subtitle {
        color: var(--secondary-text-color, #757575);
        font-size: 14px;
        margin: 0;
      }

      .card-content {
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        container-type: inline-size;
      }
      .card-content.no-header {
        padding: 8px 10px;
      }
      .header + .card-content {
        padding-top: 0;
      }

      /* SUMMARY STRIP (sibling of .hvac-summary-strip) */
      .light-summary-strip {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px 10px;
        padding: 6px 10px;
        border-radius: 10px;
        min-height: 36px;
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        box-sizing: border-box;
      }
      .summary-strip-left {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 6px;
        min-width: 0;
      }
      .summary-strip-right {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 5px;
        flex-shrink: 0;
      }
      .summary-status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
        background: var(--disabled-text-color, #94a3b8);
      }
      .summary-status-dot.on {
        background: #f59e0b;
        box-shadow: 0 0 6px rgba(245, 158, 11, 0.65);
      }
      .summary-sep {
        opacity: 0.4;
        font-size: 12px;
      }
      .strip-active-pill {
        padding: 2px 9px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--card-background-color, rgba(128, 128, 128, 0.10));
        color: var(--secondary-text-color);
        cursor: pointer;
        transition: all 0.18s ease;
      }
      .strip-active-pill.lit {
        background: rgba(245, 158, 11, 0.14);
        border-color: rgba(245, 158, 11, 0.40);
        color: #f59e0b;
      }
      .strip-active-pill.drawer-open {
        background: rgba(245, 158, 11, 0.24);
        border-color: #f59e0b;
      }
      .strip-link-btn {
        background: none;
        border: none;
        padding: 0;
        font-family: inherit;
        font-size: 13px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
        cursor: pointer;
      }
      .strip-link-btn:hover {
        color: var(--primary-color, #03a9f4);
      }
      .strip-metric-text {
        font-size: 12.5px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }

      .zone-inline-chip {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
        line-height: 1.25;
        white-space: nowrap;
        flex-shrink: 0;
      }
      .zone-inline-chip.info {
        background: rgba(14, 165, 233, 0.16);
        color: #0284c7;
        border: 1px solid rgba(14, 165, 233, 0.30);
      }
      .zone-inline-chip.warning {
        background: rgba(245, 158, 11, 0.16);
        color: #d97706;
        border: 1px solid rgba(245, 158, 11, 0.36);
      }
      .zone-inline-chip.neutral {
        background: rgba(128, 128, 128, 0.14);
        color: var(--secondary-text-color);
        border: 1px solid rgba(128, 128, 128, 0.24);
      }
      .zone-inline-chip.clickable {
        cursor: pointer;
      }

      .alert-pill-btn,
      .all-off-pill-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: 999px;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        white-space: nowrap;
        border: 1px solid transparent;
        transition: all 0.15s ease;
      }
      .all-off-pill-btn {
        background: rgba(245, 158, 11, 0.16);
        color: #f59e0b;
        border-color: rgba(245, 158, 11, 0.38);
      }
      .all-off-pill-btn:hover {
        background: rgba(245, 158, 11, 0.26);
      }
      .icon-circle-btn {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: var(--card-background-color, rgba(128, 128, 128, 0.10));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.20));
        color: var(--primary-text-color);
        cursor: pointer;
        transition: border-color 0.15s ease;
      }
      .icon-circle-btn:hover {
        border-color: var(--primary-color, #03a9f4);
      }

      /* HOLIDAY ACCENT BANNER */
      .holiday-banner {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 7px 10px;
        border-radius: 12px;
        border: 1.5px solid transparent;
        cursor: pointer;
        transition: all 0.2s ease;
      }
      .holiday-banner-left {
        display: flex;
        align-items: center;
        gap: 9px;
        min-width: 0;
        flex: 1;
      }
      .holiday-icon-badge {
        width: 30px;
        height: 30px;
        border-radius: 9px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .holiday-text-wrap {
        min-width: 0;
        flex: 1;
      }
      .holiday-phrase {
        font-size: 13px;
        font-weight: 700;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .holiday-sub {
        font-size: 12px;
        opacity: 0.85;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .holiday-action-btn {
        padding: 3px 10px;
        border-radius: 999px;
        border: 1px solid currentColor;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        flex-shrink: 0;
      }

      /* MASTER DIMMER & SLIDERS */
      .master-dimmer-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 2px 4px;
      }
      .master-label {
        font-size: 12.5px;
        font-weight: 600;
        color: var(--secondary-text-color);
        flex-shrink: 0;
      }
      .master-pct {
        width: 34px;
        text-align: right;
        font-size: 12.5px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
        flex-shrink: 0;
      }
      .master-pct.lit {
        color: #f59e0b;
      }
      .slider-track {
        position: relative;
        flex: 1;
        height: 8px;
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.22);
        display: flex;
        align-items: center;
      }
      .slider-track.small {
        width: 68px;
        flex: none;
      }
      .slider-fill {
        height: 100%;
        border-radius: 999px;
        background: #f59e0b;
        pointer-events: none;
      }
      .slider-fill.master {
        background: linear-gradient(90deg, #f59e0b, #fbbf24);
      }
      .dimmer-range {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        margin: 0;
        -webkit-appearance: none;
        appearance: none;
        background: transparent;
        cursor: pointer;
      }
      .dimmer-range:disabled {
        cursor: default;
        opacity: 0.45;
      }
      .dimmer-range::-webkit-slider-thumb {
        -webkit-appearance: none;
        appearance: none;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: #f59e0b;
        border: 2px solid var(--ha-card-background, #fff);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
      }
      .dimmer-range::-moz-range-thumb {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: #f59e0b;
        border: 2px solid var(--ha-card-background, #fff);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
      }

      /* FLOOR LAYOUTS (TILES, RINGS, ROWS) */
      .floor-tiles-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 7px;
      }
      .light-zone-card {
        position: relative;
        overflow: hidden;
        border-radius: 12px;
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.14));
        cursor: pointer;
        transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
      }
      .light-zone-card:hover {
        border-color: rgba(var(--rgb-primary-color, 3, 169, 244), 0.38);
      }
      .light-zone-card.lit {
        background: rgba(245, 158, 11, 0.10);
        border-color: rgba(245, 158, 11, 0.42);
        box-shadow: 0 3px 10px rgba(245, 158, 11, 0.12);
      }
      .light-zone-card.selected {
        border-color: var(--primary-color, #03a9f4);
        box-shadow: 0 0 0 1px var(--primary-color, #03a9f4);
      }
      .light-zone-card.tile {
        padding: 8px 10px;
      }
      .light-zone-card.tile.span-2 {
        grid-column: span 2;
      }
      .tile-main {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
      }
      .tile-identity {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1;
      }
      .light-zone-icon-wrap {
        width: 38px;
        height: 38px;
        border-radius: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        background: rgba(128, 128, 128, 0.14);
        color: var(--secondary-text-color);
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        transition: all 0.2s ease;
      }
      .light-zone-icon-wrap.compact {
        width: 32px;
        height: 32px;
        border-radius: 10px;
      }
      .light-zone-icon-wrap.lit {
        background: rgba(245, 158, 11, 0.20);
        color: #f59e0b;
        border-color: rgba(245, 158, 11, 0.45);
        box-shadow: 0 0 8px rgba(245, 158, 11, 0.20);
      }
      .tile-text {
        min-width: 0;
        flex: 1;
      }
      .tile-name-row {
        display: flex;
        align-items: center;
        gap: 5px;
        min-width: 0;
      }
      .tile-name {
        font-size: 13px;
        font-weight: 700;
        color: var(--primary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .override-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #f59e0b;
        display: inline-block;
        flex-shrink: 0;
      }
      .tile-sub {
        display: flex;
        align-items: center;
        gap: 3px;
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .tile-sub.lit {
        color: #f59e0b;
        font-weight: 600;
      }
      .tile-controls {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
      }
      .tile-pct {
        font-size: 13.5px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .tile-pct.lit {
        color: var(--primary-text-color);
      }
      .floor-power-btn {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--card-background-color, rgba(128, 128, 128, 0.12));
        color: var(--secondary-text-color);
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .floor-power-btn.lit {
        background: #f59e0b;
        border-color: #f59e0b;
        color: #ffffff;
      }
      .tile-hairline {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 2.5px;
        background: rgba(148, 163, 184, 0.15);
      }
      .tile-hairline-fill {
        height: 100%;
        background: #f59e0b;
        transition: width 0.25s ease;
      }

      /* RINGS LAYOUT */
      .floor-rings-grid {
        display: grid;
        gap: 4px;
      }
      .ring-tile-btn {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
        padding: 5px 2px;
        border-radius: 11px;
        background: transparent;
        border: 1px solid transparent;
        font-family: inherit;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .ring-tile-btn:hover {
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
      }
      .ring-tile-btn.selected {
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.12));
        border-color: var(--primary-color, #03a9f4);
      }
      .ring-wrap {
        position: relative;
        width: 42px;
        height: 42px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .ring-svg {
        width: 100%;
        height: 100%;
        transform: rotate(-90deg);
      }
      .ring-val {
        position: absolute;
        font-size: 12px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .ring-val.lit {
        color: var(--primary-text-color);
      }
      .ring-name {
        font-size: 12px;
        font-weight: 700;
        color: var(--secondary-text-color);
        max-width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .ring-name.lit {
        color: var(--primary-text-color);
      }
      .ring-count {
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
        display: flex;
        align-items: center;
        gap: 3px;
      }
      .ring-count.lit {
        color: #f59e0b;
        font-weight: 600;
      }

      /* ROWS LAYOUT */
      .floor-rows-stack {
        display: flex;
        flex-direction: column;
        gap: 7px;
      }
      .light-zone-card.row {
        padding: 9px 11px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .row-left {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
        flex: 1;
      }
      .row-text {
        min-width: 0;
        flex: 1;
      }
      .row-title-line {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .row-title {
        font-size: 15px;
        font-weight: 700;
        color: var(--primary-text-color);
      }
      .row-sub {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 12.5px;
        color: var(--secondary-text-color);
      }
      .row-right {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
      }
      .row-pct {
        font-size: 18px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .row-pct.lit {
        color: var(--primary-text-color);
      }

      /* INLINE DRAWER (mirrors .hvac-sensor-tray-grid) */
      @keyframes slideDown {
        from { opacity: 0; transform: translateY(-3px); }
        to { opacity: 1; transform: translateY(0); }
      }
      .light-drawer {
        border-top: 1px dashed var(--divider-color, rgba(128, 128, 128, 0.25));
        padding-top: 8px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        animation: slideDown 0.18s ease-out forwards;
      }
      .drawer-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }
      .drawer-title-group {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
      }
      .drawer-title {
        font-size: 13px;
        font-weight: 700;
        color: var(--primary-text-color);
      }
      .drawer-filter-btn {
        padding: 2px 7px;
        border-radius: 6px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: transparent;
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .drawer-filter-btn.active {
        border-color: rgba(245, 158, 11, 0.45);
        background: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
      }
      .drawer-actions {
        display: flex;
        align-items: center;
        gap: 5px;
      }
      .floor-off-pill-btn {
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid rgba(245, 158, 11, 0.40);
        background: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .drawer-manage-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 9px;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .drawer-manage-btn:hover {
        border-color: var(--primary-color, #03a9f4);
      }
      .drawer-close-btn {
        background: none;
        border: none;
        padding: 2px;
        color: var(--secondary-text-color);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
      }
      .drawer-list {
        max-height: 220px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 5px;
        padding-right: 2px;
      }
      .drawer-empty {
        padding: 12px 8px;
        text-align: center;
        font-size: 12.5px;
        color: var(--secondary-text-color);
      }

      /* LEAF LIGHT ROW */
      .light-item-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        background: var(--card-background-color, rgba(128, 128, 128, 0.06));
      }
      .light-item-row.lit {
        border-color: rgba(245, 158, 11, 0.36);
        background: rgba(245, 158, 11, 0.10);
      }
      .light-item-left {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1;
      }
      .bulb-toggle-btn {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.12));
        color: var(--secondary-text-color);
        cursor: pointer;
      }
      .bulb-toggle-btn.lit {
        background: #f59e0b;
        border-color: #f59e0b;
        color: #ffffff;
      }
      .light-item-text {
        min-width: 0;
        flex: 1;
      }
      .light-item-name-row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 5px;
        min-width: 0;
      }
      .light-name-btn {
        background: none;
        border: none;
        padding: 0;
        font-family: inherit;
        font-size: 12.5px;
        font-weight: 600;
        color: var(--secondary-text-color);
        cursor: pointer;
        text-align: left;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
      }
      .light-name-btn.lit {
        color: var(--primary-text-color);
      }
      .light-name-btn:hover {
        text-decoration: underline;
      }
      .light-item-sub {
        font-size: 12px;
        color: var(--secondary-text-color);
        opacity: 0.85;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .light-item-right {
        display: flex;
        align-items: center;
        gap: 7px;
        flex-shrink: 0;
      }
      .light-pct-label {
        width: 32px;
        text-align: right;
        font-size: 12px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .light-pct-label.lit {
        color: #f59e0b;
      }
      .onoff-chip {
        padding: 2px 9px;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.25));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.12));
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .onoff-chip.lit {
        background: #f59e0b;
        border-color: #f59e0b;
        color: #ffffff;
      }

      /* FOOTER STRIP */
      .engine-footer-strip {
        padding-top: 6px;
        border-top: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
      }
      .footer-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
      }
      .footer-chip {
        padding: 2px 9px;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .footer-chip.sky {
        background: rgba(14, 165, 233, 0.15);
        border-color: rgba(14, 165, 233, 0.35);
        color: #0284c7;
      }
      .footer-chip.amber {
        background: rgba(245, 158, 11, 0.15);
        border-color: rgba(245, 158, 11, 0.38);
        color: #d97706;
      }
      .footer-chip.amber-strong {
        background: rgba(245, 158, 11, 0.22);
        border-color: rgba(245, 158, 11, 0.50);
        color: #f59e0b;
        font-weight: 700;
      }
      .footer-command-link {
        background: none;
        border: none;
        padding: 0;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        color: var(--primary-color, #03a9f4);
        cursor: pointer;
      }
      .footer-command-link:hover {
        text-decoration: underline;
      }

      /* TOAST */
      .card-toast {
        position: fixed;
        bottom: 18px;
        right: 18px;
        z-index: 10001;
        padding: 7px 12px;
        border-radius: 10px;
        background: var(--ha-card-background, #1c1c1e);
        border: 1px solid var(--primary-color, #03a9f4);
        color: var(--primary-text-color);
        font-size: 12.5px;
        font-weight: 600;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        pointer-events: none;
      }

      /* MODAL COMMAND CENTER (matches passable-hvac-card) */
      @keyframes ha-popup-backdrop-fade-in { from { opacity: 0; } to { opacity: 1; } }
      @keyframes ha-popup-backdrop-fade-out { from { opacity: 1; } to { opacity: 0; } }
      @keyframes ha-popup-dialog-in {
        from { opacity: 0; transform: translateY(20px) scale(0.96); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      @keyframes ha-popup-dialog-out {
        from { opacity: 1; transform: translateY(0) scale(1); }
        to { opacity: 0; transform: translateY(12px) scale(0.97); }
      }
      @keyframes ha-popup-sheet-in {
        from { transform: translateY(100%); opacity: 0.5; }
        to { transform: translateY(0); opacity: 1; }
      }
      @keyframes ha-popup-sheet-out {
        from { transform: translateY(0); opacity: 1; }
        to { transform: translateY(100%); opacity: 0; }
      }

      .popup-overlay {
        position: fixed;
        inset: 0;
        background-color: var(--mdc-dialog-scrim-color, var(--dialog-backdrop-background, rgba(0, 0, 0, 0.35)));
        backdrop-filter: var(--dialog-backdrop-filter, none);
        -webkit-backdrop-filter: var(--dialog-backdrop-filter, none);
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 16px;
        box-sizing: border-box;
        z-index: 9999;
        animation: ha-popup-backdrop-fade-in 240ms cubic-bezier(0.2, 0, 0, 1) forwards;
      }
      .popup-overlay.closing {
        animation: ha-popup-backdrop-fade-out 180ms cubic-bezier(0.2, 0, 0, 1) forwards;
      }
      .popup-content {
        background-color: var(--ha-card-background, var(--card-background-color, #fff));
        padding: 16px 18px 20px;
        border-radius: var(--ha-dialog-border-radius, var(--ha-card-border-radius, 24px));
        width: 100%;
        max-width: 520px;
        max-height: 90vh;
        overflow: hidden;
        color: var(--primary-text-color);
        display: flex;
        flex-direction: column;
        gap: 10px;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.4);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
        box-sizing: border-box;
        animation: ha-popup-dialog-in 240ms cubic-bezier(0.2, 0, 0, 1) forwards;
      }
      .popup-content.closing {
        animation: ha-popup-dialog-out 180ms cubic-bezier(0.2, 0, 0, 1) forwards;
      }
      .drag-handle {
        display: none;
      }
      .popup-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
      }
      .popup-header-left {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }
      .popup-header h3 {
        margin: 0;
        font-size: 16px;
        font-weight: 700;
        color: var(--primary-text-color);
      }
      .popup-header-sub {
        font-size: 12px;
        color: var(--secondary-text-color);
        font-variant-numeric: tabular-nums;
      }
      .popup-header-actions {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
      }
      .close-button {
        background: none;
        border: none;
        padding: 4px;
        cursor: pointer;
        color: var(--primary-text-color);
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
      }
      .close-button:hover {
        background-color: rgba(128, 128, 128, 0.15);
      }

      .popup-tabs {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.12));
        padding: 4px;
        border-radius: 14px;
        gap: 4px;
        box-sizing: border-box;
      }
      .popup-tab {
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 3px;
        padding: 7px 4px;
        border-radius: 10px;
        background: transparent;
        border: none;
        font-family: inherit;
        color: var(--secondary-text-color);
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s ease;
      }
      .popup-tab ha-icon {
        --mdc-icon-size: 16px;
      }
      .popup-tab.active-tab {
        background: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #ffffff);
        font-weight: 700;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
      }

      .modal-filter-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
      }
      .modal-filter-pill {
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.10));
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .modal-filter-pill.active {
        background: var(--primary-color, #3b82f6);
        border-color: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #ffffff);
      }

      .modal-scroll-area {
        overflow-y: auto;
        max-height: 55vh;
        display: flex;
        flex-direction: column;
        gap: 10px;
        padding-right: 3px;
      }
      .modal-empty-state {
        padding: 28px 12px;
        text-align: center;
        font-size: 13px;
        color: var(--secondary-text-color);
      }

      .passable-section-card {
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.14));
        border-radius: 16px;
        padding: 11px 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .passable-section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .passable-section-title {
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--primary-text-color);
      }

      .room-card-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
      }
      .room-card-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }
      .room-card-title {
        font-size: 13.5px;
        font-weight: 700;
        color: var(--primary-text-color);
      }
      .room-lux-readout {
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
      }
      .room-card-controls {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 5px;
      }
      .room-pill-toggle {
        padding: 2px 9px;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.24));
        background: var(--card-background-color, rgba(128, 128, 128, 0.10));
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .room-pill-toggle.green {
        border-color: rgba(34, 197, 94, 0.40);
        background: rgba(34, 197, 94, 0.15);
        color: #16a34a;
      }
      .room-pill-toggle.sky {
        border-color: rgba(14, 165, 233, 0.40);
        background: rgba(14, 165, 233, 0.15);
        color: #0284c7;
      }
      .room-lights-list {
        display: flex;
        flex-direction: column;
        gap: 5px;
      }

      /* ENGINE TAB: KPI GRID & ACCORDIONS */
      .light-kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 7px;
      }
      .light-kpi-card {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 8px 9px;
        border-radius: 12px;
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        text-align: left;
        font-family: inherit;
      }
      .light-kpi-card.clickable {
        cursor: pointer;
      }
      .light-kpi-card.warn {
        border-color: rgba(245, 158, 11, 0.45);
        background: rgba(245, 158, 11, 0.10);
      }
      .kpi-label {
        font-size: 12px;
        font-weight: 700;
        color: var(--secondary-text-color);
      }
      .kpi-val {
        font-size: 16px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
      }
      .kpi-val.green { color: #16a34a; }
      .kpi-val.amber { color: #f59e0b; }
      .kpi-val.sky { color: #0284c7; }

      .engine-accordions-list {
        display: flex;
        flex-direction: column;
        gap: 7px;
      }
      .passable-accordion-card {
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.14));
        border-radius: 14px;
        overflow: hidden;
      }
      .passable-accordion-card.expanded {
        border-color: rgba(var(--rgb-primary-color, 3, 169, 244), 0.42);
      }
      .passable-accordion-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        padding: 9px 11px;
        cursor: pointer;
      }
      .accordion-room-left {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
        flex: 1;
      }
      .accordion-main-text {
        font-size: 13px;
        font-weight: 700;
        color: var(--primary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .accordion-mode-sub {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .accordion-room-controls {
        display: flex;
        align-items: center;
        gap: 5px;
        flex-shrink: 0;
      }
      .step-controller-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: var(--card-background-color, rgba(128, 128, 128, 0.14));
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        border-radius: 999px;
        padding: 2px 7px;
      }
      .pill-btn {
        background: none;
        border: none;
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        padding: 0 4px;
      }
      .pill-value {
        font-size: 12px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
      }

      .passable-accordion-body {
        padding: 10px 11px 12px;
        border-top: 1px solid var(--divider-color, rgba(128, 128, 128, 0.14));
        background: var(--card-background-color, rgba(128, 128, 128, 0.04));
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .engine-detail-meta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .detail-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }
      .yield-chart-box {
        border-radius: 10px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
        padding: 6px 8px;
      }
      .yield-svg {
        width: 100%;
        height: 76px;
        display: block;
      }
      .yield-fallback-note {
        font-size: 12px;
        color: var(--secondary-text-color);
        text-align: center;
        margin-top: 2px;
      }
      .engine-detail-actions {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .primary-action-btn {
        padding: 5px 12px;
        border-radius: 8px;
        border: none;
        background: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #ffffff);
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .primary-action-btn:disabled {
        opacity: 0.6;
        cursor: default;
      }
      .reset-controls-group {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .compact-select {
        padding: 4px 8px;
        border-radius: 8px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.12));
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 12px;
      }
      .danger-action-btn {
        padding: 5px 10px;
        border-radius: 8px;
        border: 1px solid rgba(239, 68, 68, 0.40);
        background: rgba(239, 68, 68, 0.12);
        color: #ef4444;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .danger-action-btn.confirming {
        background: #ef4444;
        color: #ffffff;
      }

      /* HOLIDAY & AWAY TABS */
      .subsystem-toggle-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 7px;
      }
      .subsystem-toggle-grid.two-col {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .subsystem-toggle-tile {
        padding: 8px 10px;
        border-radius: 12px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.18));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
        text-align: left;
        font-family: inherit;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .subsys-title {
        font-size: 12px;
        font-weight: 700;
        color: var(--primary-text-color);
      }
      .subsys-state {
        font-size: 12.5px;
        font-weight: 800;
        color: var(--secondary-text-color);
      }
      .subsystem-toggle-tile.sky { border-color: rgba(14, 165, 233, 0.42); background: rgba(14, 165, 233, 0.12); }
      .subsystem-toggle-tile.sky .subsys-state { color: #0284c7; }
      .subsystem-toggle-tile.amber { border-color: rgba(245, 158, 11, 0.45); background: rgba(245, 158, 11, 0.12); }
      .subsystem-toggle-tile.amber .subsys-state { color: #f59e0b; }
      .subsystem-toggle-tile.green { border-color: rgba(34, 197, 94, 0.42); background: rgba(34, 197, 94, 0.12); }
      .subsystem-toggle-tile.green .subsys-state { color: #16a34a; }

      .holiday-hero-card {
        border-radius: 14px;
        padding: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .holiday-hero-kicker { font-size: 12px; font-weight: 700; opacity: 0.9; }
      .holiday-hero-phrase { font-size: 15px; font-weight: 800; }
      .holiday-hero-meta { font-size: 12px; opacity: 0.9; }
      .holiday-hero-btn {
        padding: 5px 12px;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.5);
        background: rgba(255, 255, 255, 0.18);
        color: #ffffff;
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        flex-shrink: 0;
      }

      .holiday-catalog-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .holiday-catalog-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 7px 10px;
        border-radius: 12px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
      }
      .holiday-catalog-row.active {
        border-color: var(--primary-color, #03a9f4);
      }
      .holiday-cat-left {
        display: flex;
        align-items: center;
        gap: 9px;
        min-width: 0;
        flex: 1;
      }
      .holiday-swatch {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        flex-shrink: 0;
      }
      .holiday-cat-text { min-width: 0; flex: 1; }
      .holiday-cat-name { font-size: 12.5px; font-weight: 700; color: var(--primary-text-color); }
      .holiday-cat-dates { font-weight: 500; color: var(--secondary-text-color); }
      .holiday-cat-sub {
        font-size: 12px;
        color: var(--secondary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .holiday-cat-actions { display: flex; gap: 5px; flex-shrink: 0; }
      .catalog-btn {
        padding: 4px 8px;
        border-radius: 8px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.22));
        background: var(--card-background-color, rgba(128, 128, 128, 0.10));
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
      }
      .catalog-btn.primary {
        background: var(--primary-color, #3b82f6);
        border-color: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #ffffff);
      }

      .away-hero-card {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 10px 12px;
        border-radius: 14px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.18));
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.08));
      }
      .away-hero-card.active {
        border-color: rgba(245, 158, 11, 0.45);
        background: rgba(245, 158, 11, 0.12);
      }
      .away-hero-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
      .away-hero-title { font-size: 13.5px; font-weight: 700; text-transform: capitalize; }
      .away-hero-sub { font-size: 12px; color: var(--secondary-text-color); }
      .away-toggle-btn {
        padding: 6px 12px;
        border-radius: 999px;
        border: none;
        background: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #ffffff);
        font-family: inherit;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        flex-shrink: 0;
      }
      .away-toggle-btn.active {
        background: #f59e0b;
        color: #ffffff;
      }
      .away-meta-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
      }
      .away-lights-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 6px;
      }
      .away-light-chip {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 5px 8px;
        border-radius: 8px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        background: var(--card-background-color, rgba(128, 128, 128, 0.08));
        color: var(--secondary-text-color);
        font-family: inherit;
        font-size: 12px;
        cursor: pointer;
        text-align: left;
      }
      .away-light-chip.lit {
        border-color: rgba(245, 158, 11, 0.42);
        background: rgba(245, 158, 11, 0.14);
        color: var(--primary-text-color);
        font-weight: 600;
      }
      .away-light-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--disabled-text-color, #888);
        opacity: 0.45;
        flex-shrink: 0;
      }
      .away-light-dot.lit {
        background: #f59e0b;
        opacity: 1;
      }
      .away-light-name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      @media (max-width: 768px) {
        .popup-overlay {
          align-items: flex-end;
          padding: 0;
          overscroll-behavior: contain;
        }
        .popup-content {
          width: 100%;
          max-width: 100%;
          border-radius: var(--ha-dialog-border-radius, 24px) var(--ha-dialog-border-radius, 24px) 0 0;
          border-bottom: none;
          border-left: none;
          border-right: none;
          padding-bottom: max(24px, env(safe-area-inset-bottom, 24px));
          animation: ha-popup-sheet-in 280ms cubic-bezier(0.2, 0, 0, 1) forwards;
        }
        .popup-content.closing {
          animation: ha-popup-sheet-out 180ms cubic-bezier(0.2, 0, 0, 1) forwards;
        }
        .drag-handle {
          display: block;
          width: 36px;
          height: 5px;
          background-color: var(--secondary-text-color, #888);
          border-radius: 3px;
          margin: -4px auto 4px auto;
          flex-shrink: 0;
        }
        .light-kpi-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
      }

      @media (max-width: 420px) {
        .floor-tiles-grid {
          grid-template-columns: 1fr;
        }
        .light-zone-card.tile.span-2 {
          grid-column: span 1;
        }
        .popup-tabs {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
      }

      @media (prefers-reduced-motion: reduce) {
        .popup-overlay,
        .popup-content,
        .light-drawer {
          animation: none !important;
          transition: none !important;
        }
      }
    `;
  }
}

// ==========================================
// VISUAL CARD EDITOR
// ==========================================
class PassableLightingCardEditor extends LitElement {
  static get properties() {
    return {
      hass: {},
      config: {},
    };
  }

  setConfig(config) {
    this.config = config || {};
  }

  _updateConfig(newConfig) {
    this.config = newConfig;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this.config },
        bubbles: true,
        composed: true,
      })
    );
    this.requestUpdate();
  }

  _onFieldChange(ev, explicitKey = null) {
    if (!this.config) return;
    const target = ev.target;
    const key = explicitKey || target.configValue || target.getAttribute("configValue");
    if (!key) return;

    const val =
      ev.detail && ev.detail.value !== undefined
        ? ev.detail.value
        : target.checked !== undefined
          ? target.checked
          : target.value;

    const next = { ...this.config };
    if (val === "" || val === undefined || val === null) {
      delete next[key];
    } else {
      next[key] = val;
    }
    this._updateConfig(next);
  }

  _updateAlert(index, patch) {
    const alerts = Array.isArray(this.config?.alerts) ? [...this.config.alerts] : [];
    const cur = { ...(alerts[index] || {}) };
    Object.entries(patch).forEach(([k, v]) => {
      if (v === "" || v === undefined || v === null) {
        delete cur[k];
      } else {
        cur[k] = v;
      }
    });
    alerts[index] = cur;
    this._updateConfig({ ...this.config, alerts });
  }

  _updateAlertAction(index, actionType, serviceStr, targetEntity, navPath) {
    const alerts = Array.isArray(this.config?.alerts) ? [...this.config.alerts] : [];
    const cur = { ...(alerts[index] || {}) };
    const prevAction = { ...(cur.tap_action || {}) };

    if (!actionType || actionType === "more-info") {
      cur.tap_action = { action: "more-info" };
    } else if (actionType === "perform-action") {
      const nextAction = {
        ...prevAction,
        action: "perform-action",
        perform_action: serviceStr || prevAction.perform_action || prevAction.service || "",
      };
      delete nextAction.service;
      if (targetEntity) {
        nextAction.target = { ...(prevAction.target || {}), entity_id: targetEntity };
      } else if (nextAction.target) {
        const t = { ...nextAction.target };
        delete t.entity_id;
        if (Object.keys(t).length === 0) delete nextAction.target;
        else nextAction.target = t;
      }
      cur.tap_action = nextAction;
    } else if (actionType === "navigate") {
      cur.tap_action = {
        action: "navigate",
        navigation_path: navPath || prevAction.navigation_path || "",
      };
    } else {
      cur.tap_action = { action: actionType };
    }

    alerts[index] = cur;
    this._updateConfig({ ...this.config, alerts });
  }

  _addAlert() {
    const alerts = Array.isArray(this.config?.alerts) ? [...this.config.alerts] : [];
    alerts.push({
      entity: "",
      state: "on",
      label: "Alert",
      icon: "mdi:bell-ring-outline",
      color: "var(--info-color)",
      tap_action: { action: "more-info" },
    });
    this._updateConfig({ ...this.config, alerts });
  }

  _removeAlert(index) {
    const alerts = Array.isArray(this.config?.alerts) ? [...this.config.alerts] : [];
    alerts.splice(index, 1);
    this._updateConfig({ ...this.config, alerts });
  }

  render() {
    if (!this.hass || !this.config) return html``;
    const c = this.config;
    const alerts = Array.isArray(c.alerts) ? c.alerts : [];

    return html`
      <div class="editor-container">
        <div class="section-box">
          <h3>Appearance & Layout</h3>

          <ha-textfield
            label="Card Title"
            .value=${c.title || "Lighting"}
            @input=${(ev) => this._onFieldChange(ev, "title")}
          ></ha-textfield>

          <div class="switch-row">
            <label class="form-label">Show Card Header</label>
            <ha-switch
              .checked=${c.show_header === true}
              @change=${(ev) => this._onFieldChange(ev, "show_header")}
            ></ha-switch>
          </div>

          <div class="form-group">
            <label class="form-label">Floor Layout</label>
            <select
              class="custom-select"
              .value=${c.layout || "tiles"}
              @change=${(ev) => this._onFieldChange(ev, "layout")}
            >
              <option value="tiles">Compact Floor Tiles (Recommended)</option>
              <option value="rings">5-Across Progress Rings</option>
              <option value="rows">Stacked Floor Rows</option>
            </select>
          </div>

          <div class="switch-row">
            <label class="form-label">Show Top Summary Strip</label>
            <ha-switch
              .checked=${c.show_summary_strip !== false}
              @change=${(ev) => this._onFieldChange(ev, "show_summary_strip")}
            ></ha-switch>
          </div>

          <div class="switch-row">
            <label class="form-label">Show Active Holiday Banner</label>
            <ha-switch
              .checked=${c.show_holiday_banner !== false}
              @change=${(ev) => this._onFieldChange(ev, "show_holiday_banner")}
            ></ha-switch>
          </div>

          <div class="switch-row">
            <label class="form-label">Show Master Dimmer</label>
            <ha-switch
              .checked=${c.show_master_dimmer !== false}
              @change=${(ev) => this._onFieldChange(ev, "show_master_dimmer")}
            ></ha-switch>
          </div>

          <div class="switch-row">
            <label class="form-label">Show Subsystem Footer Strip</label>
            <ha-switch
              .checked=${c.show_engine_footer !== false}
              @change=${(ev) => this._onFieldChange(ev, "show_engine_footer")}
            ></ha-switch>
          </div>
        </div>

        <div class="section-box">
          <h3>Light Discovery & Shortcuts</h3>

          <ha-selector
            .hass=${this.hass}
            .selector=${{ entity: { domain: "light" } }}
            .value=${c.master_light || "light.all_lights"}
            .label=${"Master Light / Floor Group Root"}
            @value-changed=${(ev) => this._onFieldChange(ev, "master_light")}
          ></ha-selector>

          <ha-selector
            .hass=${this.hass}
            .selector=${{ entity: { domain: "light", multiple: true } }}
            .value=${Array.isArray(c.exclude_entities) ? c.exclude_entities : []}
            .label=${"Excluded Light Entities"}
            @value-changed=${(ev) => this._onFieldChange(ev, "exclude_entities")}
          ></ha-selector>

          <ha-textfield
            label="Default Expanded Drawer (floor entity_id or 'active')"
            .value=${c.default_expanded_floor || ""}
            @input=${(ev) => this._onFieldChange(ev, "default_expanded_floor")}
          ></ha-textfield>

          <ha-textfield
            label="Stats Shortcut Path (e.g. /dashboard-home/light-stats)"
            .value=${c.stats_navigation_path || ""}
            @input=${(ev) => this._onFieldChange(ev, "stats_navigation_path")}
          ></ha-textfield>
        </div>

        <div class="section-box">
          <div class="switch-row">
            <h3 style="margin:0;">Summary Strip Alert Pills</h3>
            <button type="button" class="add-btn" @click=${() => this._addAlert()}>+ Add Alert</button>
          </div>
          <p class="form-help">
            Render conditional labeled pills (such as Laundry Reset) in the summary strip when an entity matches a state.
          </p>

          ${alerts.map((alert, idx) => {
            const tapAction = alert.tap_action || { action: "more-info" };
            const actionType =
              tapAction.action === "call-service" ? "perform-action" : (tapAction.action || "more-info");
            const serviceStr = tapAction.perform_action || tapAction.service || "";
            const targetEnt = tapAction.target?.entity_id || "";
            const navPath = tapAction.navigation_path || "";

            return html`
              <div class="alert-editor-box">
                <div class="switch-row">
                  <strong style="font-size:13px;">Alert #${idx + 1}</strong>
                  <button type="button" class="remove-btn" @click=${() => this._removeAlert(idx)}>
                    Remove
                  </button>
                </div>

                <ha-selector
                  .hass=${this.hass}
                  .selector=${{ entity: {} }}
                  .value=${alert.entity || ""}
                  .label=${"Alert Trigger Entity"}
                  @value-changed=${(ev) => this._updateAlert(idx, { entity: ev.detail.value })}
                ></ha-selector>

                <div class="two-col-row">
                  <ha-textfield
                    label="Trigger State"
                    .value=${alert.state ?? "on"}
                    @input=${(ev) => this._updateAlert(idx, { state: ev.target.value })}
                  ></ha-textfield>
                  <ha-textfield
                    label="Pill Label"
                    .value=${alert.label || ""}
                    @input=${(ev) => this._updateAlert(idx, { label: ev.target.value })}
                  ></ha-textfield>
                </div>

                <div class="two-col-row">
                  <ha-textfield
                    label="Icon (e.g. phu:rooms-laundry-room)"
                    .value=${alert.icon || ""}
                    @input=${(ev) => this._updateAlert(idx, { icon: ev.target.value })}
                  ></ha-textfield>
                  <ha-textfield
                    label="Color (e.g. var(--info-color))"
                    .value=${alert.color || ""}
                    @input=${(ev) => this._updateAlert(idx, { color: ev.target.value })}
                  ></ha-textfield>
                </div>

                <div class="form-group">
                  <label class="form-label">Tap Action</label>
                  <select
                    class="custom-select"
                    .value=${actionType}
                    @change=${(ev) =>
                      this._updateAlertAction(idx, ev.target.value, serviceStr, targetEnt, navPath)}
                  >
                    <option value="more-info">More Info</option>
                    <option value="perform-action">Perform Action (Service)</option>
                    <option value="toggle">Toggle Entity</option>
                    <option value="navigate">Navigate</option>
                  </select>
                </div>

                ${actionType === "perform-action"
                  ? html`
                      <div class="two-col-row">
                        <ha-textfield
                          label="Action (e.g. input_button.press)"
                          .value=${serviceStr}
                          @input=${(ev) =>
                            this._updateAlertAction(idx, "perform-action", ev.target.value, targetEnt, navPath)}
                        ></ha-textfield>
                        <ha-textfield
                          label="Target Entity ID"
                          .value=${targetEnt}
                          @input=${(ev) =>
                            this._updateAlertAction(idx, "perform-action", serviceStr, ev.target.value, navPath)}
                        ></ha-textfield>
                      </div>
                    `
                  : actionType === "navigate"
                    ? html`
                        <ha-textfield
                          label="Navigation Path"
                          .value=${navPath}
                          @input=${(ev) =>
                            this._updateAlertAction(idx, "navigate", serviceStr, targetEnt, ev.target.value)}
                        ></ha-textfield>
                      `
                    : ""}
              </div>
            `;
          })}
        </div>
      </div>
    `;
  }

  static get styles() {
    return css`
      .editor-container {
        display: flex;
        flex-direction: column;
        gap: 14px;
        padding: 8px 0;
      }
      .section-box {
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.06));
        border-radius: 12px;
        padding: 12px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.16));
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .section-box h3 {
        margin: 0;
        font-size: 0.95rem;
        color: var(--primary-color, #3b82f6);
      }
      .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .form-label {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .form-help {
        margin: 0;
        font-size: 0.78rem;
        color: var(--secondary-text-color);
      }
      .switch-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .two-col-row {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }
      .custom-select {
        width: 100%;
        padding: 9px 11px;
        border-radius: 8px;
        background: var(--card-background-color, #1e1e1e);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.25));
        font-size: 0.9rem;
      }
      .alert-editor-box {
        padding: 10px;
        border-radius: 10px;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.2));
        background: var(--card-background-color, rgba(128, 128, 128, 0.05));
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .add-btn {
        padding: 4px 10px;
        border-radius: 8px;
        border: none;
        background: var(--primary-color, #3b82f6);
        color: var(--text-primary-color, #fff);
        font-weight: 600;
        cursor: pointer;
      }
      .remove-btn {
        padding: 3px 8px;
        border-radius: 6px;
        border: 1px solid rgba(239, 68, 68, 0.4);
        background: rgba(239, 68, 68, 0.12);
        color: #ef4444;
        font-weight: 600;
        cursor: pointer;
      }
      ha-textfield,
      ha-selector {
        width: 100%;
      }
    `;
  }
}

if (!customElements.get("passable-lighting-card")) {
  customElements.define("passable-lighting-card", PassableLightingCard);
}
if (!customElements.get("passable-lighting-card-editor")) {
  customElements.define("passable-lighting-card-editor", PassableLightingCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "passable-lighting-card")) {
  window.customCards.push({
    type: "passable-lighting-card",
    name: "Passable Lighting Card",
    preview: true,
    documentationURL: "https://github.com/GBear09/passable-smart-light-engine",
    description:
      "Whole-home lighting control with recursive floor drill-down and Passable Smart Light Engine Command Center.",
  });
}
