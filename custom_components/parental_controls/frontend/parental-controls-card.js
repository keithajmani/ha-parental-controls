/* Parental Controls card: one child's screen (status + Block/Allow, Pause / Allow for, Devices).
 *
 *   type: custom:parental-controls-card
 *   entity: sensor.riley_parental_controls_internet
 *
 * Plain custom element, no build step; served by the integration itself. It finds the child's other entities
 * (buttons, pause length, live switch, devices sensor) through the entity registry by device, so renamed entity
 * IDs keep working.
 */
const QUICK = [15, 30, 60];
const KIND_ICON = { phone: "mdi:cellphone", tablet: "mdi:tablet", laptop: "mdi:laptop", desktop: "mdi:desktop-tower-monitor",
  console: "mdi:gamepad-variant", speaker: "mdi:speaker-wireless", other: "mdi:devices" };
const LOOK = {
  online: { icon: "mdi:web", fg: "#66bb6a", bg: "rgba(76,175,80,0.16)", title: "Online" },
  allowed_for: { icon: "mdi:web-clock", fg: "#66bb6a", bg: "rgba(76,175,80,0.16)", title: "Online" },
  paused: { icon: "mdi:timer-sand", fg: "#ffca28", bg: "rgba(255,193,7,0.14)", title: "Paused" },
  bedtime: { icon: "mdi:weather-night", fg: "#9fa8da", bg: "rgba(121,134,203,0.16)", title: "Bedtime" },
  blocked: { icon: "mdi:web-off", fg: "#ef5350", bg: "rgba(244,67,54,0.16)", title: "Blocked" },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const clock = (d) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const hhmm = (v) => { if (!v) return "–"; const [h, m] = v.split(":").map(Number); const d = new Date(); d.setHours(h, m, 0, 0); return clock(d); };
const speed = (b) => b == null ? "–" : b < 999500 ? `${Math.round(b / 1e3)} kbps` : `${(b / 1e6) >= 10 ? (b / 1e6).toFixed(0) : (b / 1e6).toFixed(1)} Mbps`;
const seen = (t) => {
  if (!t) return "never"; const d = new Date(t * 1000), n = new Date();
  if (d.toDateString() === n.toDateString()) return clock(d);
  if ((n - d) / 864e5 < 6) return d.toLocaleDateString([], { weekday: "short" }) + " " + clock(d);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
};

class ParentalControlsCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error("Pick the child's Internet sensor (sensor.<child>_parental_controls_internet)");
    this._config = config;
    this._open = false;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    const key = this._watched().map((e) => { const s = hass.states[e]; return s ? s.last_updated + s.state : ""; }).join("|") + this._open;
    if (key !== this._key) { this._key = key; this._render(); }
  }

  getCardSize() { return 6; }
  static getStubConfig(hass) {
    const e = Object.keys(hass.states).find((id) => id.startsWith("sensor.") && hass.entities?.[id]?.platform === "parental_controls"
      && hass.entities[id].translation_key === "internet");
    return { entity: e || "" };
  }
  static getConfigElement() { return document.createElement("parental-controls-card-editor"); }

  // ---- entities ---------------------------------------------------------------------------------------
  _ids() {
    if (this._idsFor === this._config.entity && this._idMap) return this._idMap;
    const reg = this._hass.entities || {};
    const dev = reg[this._config.entity]?.device_id;
    const map = {};
    for (const [id, e] of Object.entries(reg)) {
      if (dev && e.device_id === dev && e.platform === "parental_controls" && e.translation_key) {
        if (e.translation_key === "device_blocked") continue;
        map[e.translation_key] = id;
      }
    }
    this._idsFor = this._config.entity; this._idMap = map;
    return map;
  }
  _watched() {
    const ids = this._ids(); const st = this._hass.states;
    const list = [this._config.entity, ...Object.values(ids)];
    const dev = st[ids.devices];
    for (const r of dev?.attributes?.devices || []) if (r.block_entity) list.push(r.block_entity);
    return list;
  }
  _call(domain, service, data) { return this._hass.callService(domain, service, data); }
  _press(key) { const id = this._ids()[key]; if (id) this._call("button", "press", { entity_id: id }); }

  // ---- render -----------------------------------------------------------------------------------------
  _render() {
    const hass = this._hass, st = hass.states[this._config.entity];
    if (!st) { this.shadowRoot.innerHTML = `<ha-card><div class="msg">Entity not found: ${esc(this._config.entity)}</div></ha-card>`; return; }
    const a = st.attributes, look = LOOK[st.state] || LOOK.online, ids = this._ids();
    const title = this._config.title ?? (a.child ? `${a.child}'s Internet` : "");
    this.shadowRoot.innerHTML = `<style>${CSS}</style>${title ? `<div class="title">${esc(title)}</div>` : ""}
      ${this._statusHtml(st, a, look)}
      ${this._pauseHtml(st, a, ids)}
      ${ids.devices ? this._devicesHtml(ids) : ""}`;
    this._wire(st, a, ids);
  }

  _statusHtml(st, a, look) {
    let sub = "Internet is on";
    const end = a.ends_at ? new Date(a.ends_at) : null;
    if (st.state === "paused") sub = `Back on at ${clock(end)} · ${a.minutes_left} min left`;
    else if (st.state === "allowed_for") sub = `${a.minutes_left} min left · then ${a.then === "bedtime" ? "bedtime" : "blocked"}`;
    else if (st.state === "bedtime") sub = `Back on at ${hhmm(a.bedtime_end)}`;
    else if (st.state === "blocked") sub = "No time limit";
    const day = (() => { const n = new Date(); const d = n.getHours() >= 12 ? n.getDay() : (n.getDay() + 6) % 7; return d; })();
    const start = (day === 5 || day === 6) ? a.bedtime_weekend_start : a.bedtime_weeknight_start;
    const chip = !a.bedtime_enabled ? `<span class="chip off"><ha-icon icon="mdi:weather-night"></ha-icon>Bedtime off</span>`
      : `<span class="chip on"><ha-icon icon="mdi:weather-night"></ha-icon>Bedtime ${hhmm(start)} – ${hhmm(a.bedtime_end)}${a.allowed_tonight ? " · allowed tonight" : a.bedtime_now ? " · active" : ""}</span>`;
    const blocking = a.router_blocked;
    const btn = blocking
      ? `<button class="globe allow" id="act" title="Allow"><ha-icon icon="mdi:web"></ha-icon></button>`
      : `<button class="globe block" id="act" title="Block"><ha-icon icon="mdi:web-off"></ha-icon></button>`;
    return `<ha-card class="status" style="background:${look.bg}">
      <div class="srow"><ha-icon class="sicon" icon="${look.icon}" style="color:${look.fg}"></ha-icon>
        <div class="stext"><div class="s1">${look.title}</div><div class="s2">${esc(sub)}</div></div>${btn}</div>
      <div class="chiprow">${chip}</div></ha-card>`;
  }

  _pauseHtml(st, a, ids) {
    // blocked or bedtime: the buttons let the child online for a while; during a pause they restart the pause
    const allowFor = ["blocked", "bedtime", "allowed_for"].includes(st.state);
    const minutes = Number(this._hass.states[ids.pause_minutes]?.state || 15);
    const at = (m) => clock(new Date(Date.now() + m * 6e4));
    const running = (st.state === "paused" || st.state === "allowed_for") && a.ends_at;
    const runMin = running ? Math.round((new Date(a.ends_at) - new Date(st.last_changed)) / 6e4) : null;
    const tiles = QUICK.map((m) => `<button class="tile${running && runMin === m ? " active" : ""}" data-min="${m}">
        <ha-icon icon="mdi:timer-sand"></ha-icon><b>${m} min</b><span>(${at(m)})</span></button>`).join("");
    return `<ha-card class="group"><div class="h">${allowFor ? "Allow for" : "Pause"}</div>
      <div class="tiles">${tiles}</div>
      <div class="custom"><ha-icon class="cicon" icon="mdi:timer-cog-outline"></ha-icon>
        <div class="ctext"><b>Custom</b><span>${minutes} min</span><span>(${at(minutes)})</span></div>
        <div class="slider" style="--pct:${((minutes - 1) / ((this._config.max_minutes || 60) - 1)) * 100}%"><div class="fill"><i class="handle"></i></div>
          <input type="range" id="slider" min="1" max="${this._config.max_minutes || 60}" step="1" value="${minutes}" aria-label="Custom length in minutes"></div>
        <button class="pbtn" id="go" title="${allowFor ? "Allow for" : "Pause"} ${minutes} min"><ha-icon icon="mdi:pause"></ha-icon></button></div></ha-card>`;
  }

  _devicesHtml(ids) {
    const ds = this._hass.states[ids.devices], live = this._hass.states[ids.devices_live]?.state === "on";
    const head = `<div class="dhead" id="dtoggle"><span class="h">Devices${this._open ? ` <ha-icon class="chev" icon="mdi:chevron-up"></ha-icon>` : ""}</span>
      ${this._open ? `<span class="dctl"><button class="check" id="check"><ha-icon icon="mdi:refresh"></ha-icon>Check</button>
        <button class="live${live ? " on" : ""}" id="live"><i class="dot"></i>Live<i class="sw"><i></i></i></button></span>`
      : `<span class="hint">Tap to show <ha-icon icon="mdi:chevron-down"></ha-icon></span>`}</div>`;
    if (!this._open) return `<ha-card class="group">${head}</ha-card>`;
    const a = ds?.attributes || {};
    const rows = a.devices || [];
    const anyBlock = rows.some((r) => r.block_entity);
    let body = a.error ? `<div class="msg err">${esc(a.error)}</div>` : !a.checked ? `<div class="msg">No data yet. Tap Check.</div>` : "";
    body += rows.map((r) => {
      const n = r.signal == null ? 0 : r.signal >= -67 ? 3 : r.signal >= -75 ? 2 : 1;
      const col = n === 3 ? "#66bb6a" : n === 2 ? "#ffca28" : "#ef5350";
      const bars = n ? `<span class="bars">${[3, 5, 8].map((h, i) => `<i style="height:${h}px;background:${i < n ? col : "rgba(127,127,127,0.35)"}"></i>`).join("")}</span>` : "";
      const net = r.ssid && r.ssid !== "wired" ? "" : r.ssid === "wired" ? " • wired" : "";
      const where = (r.ap ? ` • ${esc(r.ap.replace(/\s+U\d.*$/, ""))} AP` : "") + net;
      const label = r.blocked ? "Blocked" : "Online";
      const status = r.online ? `<span class="${r.blocked ? "red" : "green"}">${label}${where}</span>${bars}` : `Away • last seen ${seen(r.last_seen)}`;
      const g = !anyBlock ? "" : r.block_entity
        ? `<button class="dglobe ${r.blocked ? "allow" : "block"}" data-ent="${esc(r.block_entity)}" data-on="${r.blocked ? 1 : 0}" title="${r.blocked ? "Allow" : "Block"} ${esc(r.name)}"><ha-icon icon="${r.blocked ? "mdi:web" : "mdi:web-off"}"></ha-icon></button>`
        : "<span></span>";
      const bw = r.online ? `<span class="bw"><span class="dn">${speed(r.down_bps)}</span><span class="dn">↓</span><span class="up">${speed(r.up_bps)}</span><span class="up">↑</span></span>` : "<span></span>";
      return `<div class="drow${r.online ? "" : " away"}${anyBlock ? " withb" : ""}"><ha-icon class="kind" icon="${KIND_ICON[r.kind] || KIND_ICON.other}"></ha-icon>
        <div class="dtext"><div class="dn1">${esc(r.name)}</div><div class="dn2">${status}</div></div>${g}${bw}</div>`;
    }).join("");
    const foot = a.checked && !live ? `<div class="foot">Checked ${clock(new Date(a.checked))} • tap Check to refresh</div>` : "";
    return `<ha-card class="group">${head}${body}${foot}</ha-card>`;
  }

  _wire(st, a, ids) {
    const $ = (s) => this.shadowRoot.querySelector(s);
    $("#act")?.addEventListener("click", () => this._press(a.router_blocked ? "allow" : "block"));
    this.shadowRoot.querySelectorAll(".tile").forEach((t) => t.addEventListener("click", () =>
      this._call("parental_controls", "pause", { config_entry_id: a.config_entry_id, minutes: Number(t.dataset.min) })));
    const slider = $("#slider");
    slider?.addEventListener("input", () => {
      const m = Number(slider.value), c = this.shadowRoot.querySelector(".ctext");
      slider.parentElement.style.setProperty("--pct", `${((m - slider.min) / (slider.max - slider.min)) * 100}%`);
      c.children[1].textContent = `${m} min`; c.children[2].textContent = `(${clock(new Date(Date.now() + m * 6e4))})`;
    });
    slider?.addEventListener("change", () => this._call("number", "set_value", { entity_id: ids.pause_minutes, value: Number(slider.value) }));
    $("#go")?.addEventListener("click", () => this._call("parental_controls", "pause",
      { config_entry_id: a.config_entry_id, minutes: Number(slider?.value || 15) }));
    $("#dtoggle")?.addEventListener("click", (ev) => {
      if (ev.target.closest("button")) return;
      this._open = !this._open;
      if (this._open) this._press("check_devices");
      else if (this._hass.states[ids.devices_live]?.state === "on") this._call("switch", "turn_off", { entity_id: ids.devices_live });
      this._key = null; this._render();
    });
    $("#check")?.addEventListener("click", () => this._press("check_devices"));
    $("#live")?.addEventListener("click", () => this._call("switch", "toggle", { entity_id: ids.devices_live }));
    this.shadowRoot.querySelectorAll(".dglobe").forEach((b) => b.addEventListener("click", () => {
      const ent = b.dataset.ent;
      this._call(ent.split(".")[0], b.dataset.on === "1" ? "turn_off" : "turn_on", { entity_id: ent });
    }));
  }
}

const CSS = `
:host { display: grid; gap: 10px; }
.title { font-size: 20px; margin: 4px 6px 2px; color: var(--primary-text-color); }
ha-card { padding: 12px 14px; border-radius: 16px; }
button { font: inherit; border: none; cursor: pointer; color: inherit; background: none; padding: 0; }
button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.status { border: none; padding: 14px 14px 12px 16px; }
.srow { display: grid; grid-template-columns: 44px 1fr 40px; gap: 12px; align-items: center; min-height: 52px; }
.sicon { --mdc-icon-size: 40px; }
.s1 { font-size: 21px; font-weight: 600; line-height: 26px; }
.s2 { font-size: 14px; opacity: .85; }
.globe { width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 24px; }
.globe.block, .dglobe.block { background: rgba(244,67,54,0.24); color: #ef9a9a; }
.globe.allow, .dglobe.allow { background: rgba(76,175,80,0.26); color: #a5d6a7; }
.chiprow { margin: 8px 0 0 56px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; border-radius: 12px; padding: 4px 10px; --mdc-icon-size: 15px; }
.chip.off { color: #9e9e9e; background: rgba(127,127,127,0.12); }
.chip.on { color: #c5cae9; background: rgba(121,134,203,0.18); }
.h { font-size: 16px; font-weight: 600; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
.tile { background: rgba(127,127,127,0.10); border-radius: 12px; padding: 12px 4px; display: grid; justify-items: center; gap: 2px; color: #ffca28; }
.tile b { font-size: 15px; } .tile span { font-size: 12.5px; }
.tile.active { box-shadow: inset 0 0 0 2px #ffca28; background: rgba(255,193,7,0.18); }
.custom { display: flex; align-items: center; gap: 10px; margin-top: 8px; background: rgba(127,127,127,0.10); border-radius: 12px; padding: 8px 12px; }
.cicon { color: #ffca28; --mdc-icon-size: 26px; flex: none; }
.ctext { display: grid; justify-items: center; min-width: 4.6em; font-size: 12.5px; flex: none; font-variant-numeric: tabular-nums; }
.ctext b { font-size: 14px; }
/* the same look as HA's tile slider (ha-control-slider) on today's dashboard: a 36px dim-amber track, an amber
   rounded fill that never shrinks below the handle, and a white handle bar inside the fill's right end.
   A transparent native range input on top does the dragging, keyboard and accessibility. */
.slider { position: relative; flex: 1; min-width: 80px; height: 36px; border-radius: 12px; background: rgba(255,193,7,0.15); overflow: hidden; }
.slider .fill { position: absolute; inset: 0 auto 0 0; width: max(20px, var(--pct, 0%)); background: #ffca28; border-radius: 12px; }
.slider .handle { position: absolute; right: 8px; top: 8px; bottom: 8px; width: 4px; border-radius: 2px; background: #fff; }
.slider input[type=range] { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; }
.slider:focus-within { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.pbtn { width: 36px; height: 36px; border-radius: 12px; background: rgba(255,193,7,0.14); color: #ffca28; display: flex; align-items: center; justify-content: center; flex: none; }
.dhead { display: flex; justify-content: space-between; align-items: center; min-height: 32px; cursor: pointer; }
.chev { --mdc-icon-size: 18px; opacity: .7; }
.hint { font-size: 12.5px; opacity: .7; display: inline-flex; align-items: center; gap: 4px; }
.dctl { display: flex; gap: 10px; align-items: center; }
.check { display: inline-flex; gap: 5px; align-items: center; height: 30px; padding: 0 10px; border-radius: 9px; background: rgba(121,134,203,0.2); color: #c5cae9; font-size: 12.5px; --mdc-icon-size: 16px; }
.live { display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; opacity: .85; }
.live .dot { width: 7px; height: 7px; border-radius: 50%; background: #ef5350; opacity: .3; }
.live.on .dot { opacity: 1; animation: pulse 2.6s ease-in-out infinite; }
.live .sw { width: 32px; height: 18px; border-radius: 9px; background: rgba(127,127,127,0.35); position: relative; }
.live .sw i { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: #ccc; transition: left .15s; }
.live.on .sw { background: #7986cb; } .live.on .sw i { left: 16px; background: #fff; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .45; transform: scale(.85); } }
@media (prefers-reduced-motion: reduce) { .live.on .dot { animation: none; } }
.drow { display: grid; grid-template-columns: 28px 1fr auto; gap: 8px; align-items: center; padding: 9px 0; border-top: 1px solid var(--divider-color); }
.drow.withb { grid-template-columns: 28px 1fr 34px 88px; }
.drow.away { opacity: .65; }
.kind { --mdc-icon-size: 20px; color: #9fa8da; }
.dtext { min-width: 0; } .dn1 { font-size: 14px; } .dn2 { font-size: 12px; color: var(--secondary-text-color); }
.green { color: #81c784; } .red { color: #ef9a9a; }
.bars { display: inline-flex; margin-left: 8px; align-items: flex-end; gap: 2px; height: 8px; }
.bars i { display: block; width: 3px; border-radius: 1px; }
.dglobe { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 20px; }
.bw { display: grid; grid-template-columns: auto 12px; column-gap: 4px; justify-content: end; font-size: 12.5px; line-height: 1.35; font-variant-numeric: tabular-nums; white-space: nowrap; }
.bw .dn { color: #90caf9; } .bw .up { color: #ce93d8; } .bw span:nth-child(even) { text-align: center; }
.msg { font-size: 13px; color: var(--secondary-text-color); padding: 8px 0; } .msg.err { color: #ef9a9a; }
.foot { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; }
`;

class ParentalControlsCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({ entity: "Child (their Internet sensor)", title: "Title (optional)", max_minutes: "Slider maximum (minutes)" })[s.name];
      this._form.schema = [
        { name: "entity", required: true, selector: { entity: { integration: "parental_controls", domain: "sensor" } } },
        { name: "title", selector: { text: {} } },
        { name: "max_minutes", selector: { number: { min: 10, max: 240, step: 5, mode: "box" } } },
      ];
      this._form.addEventListener("value-changed", (ev) => this.dispatchEvent(new CustomEvent("config-changed",
        { detail: { config: ev.detail.value }, bubbles: true, composed: true })));
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

if (!customElements.get("parental-controls-card")) customElements.define("parental-controls-card", ParentalControlsCard);
if (!customElements.get("parental-controls-card-editor")) customElements.define("parental-controls-card-editor", ParentalControlsCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "parental-controls-card")) {
  window.customCards.push({ type: "parental-controls-card", name: "Parental Controls", preview: false,
    description: "One child's internet: status with Block / Allow, Pause or Allow for, and Devices." });
}
