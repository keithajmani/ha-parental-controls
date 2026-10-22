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
const BT_ROWS = [
  ["bedtime_weeknight_start", "mdi:weather-night", "Sun\u2013Thu off at"],
  ["bedtime_weekend_start", "mdi:party-popper", "Fri & Sat off at"],
  ["bedtime_end", "mdi:weather-sunset-up", "Back on at"],
];

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
const hhmm = (v) => { if (!v) return "\u2013"; const [h, m] = v.split(":").map(Number); const d = new Date(); d.setHours(h, m, 0, 0); return clock(d); };
const speed = (b) => b == null ? "\u2013" : b < 999500 ? `${Math.round(b / 1e3)} kbps` : `${(b / 1e6) >= 10 ? (b / 1e6).toFixed(0) : (b / 1e6).toFixed(1)} Mbps`;
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
      ${ids.devices ? this._devicesHtml(ids) : ""}
      ${this._config.show_bedtime === true && ids.bedtime ? this._bedtimeHtml(a, ids) : ""}`;
    this._wire(st, a, ids);
    this._syncPopup(a, ids);
  }

  // The bedtime pop-up lives on document.body (like HA's own dialogs), not inside the card: dashboards that use CSS
  // containment (e.g. the sections view) would otherwise clip a fixed-position overlay to the card's own box.
  _syncPopup(a, ids) {
    if (!this._popup || !ids.bedtime) { this._closePopupEl(); return; }
    if (!this._popEl) {
      this._popEl = document.createElement("div");
      this._popEl.attachShadow({ mode: "open" });
      document.body.appendChild(this._popEl);
      this._onKey = (ev) => { if (ev.key === "Escape") this._closePopup(); };
      window.addEventListener("keydown", this._onKey);
    }
    const root = this._popEl.shadowRoot;
    root.innerHTML = `<style>${CSS}${POPUP_CSS}</style>${this._popupHtml(a, ids)}`;
    root.querySelector("#btclose")?.addEventListener("click", () => this._closePopup());
    root.querySelector("#scrim")?.addEventListener("click", (ev) => { if (ev.target.id === "scrim") this._closePopup(); });
    root.querySelector("#btsw2")?.addEventListener("click", () => this._call("switch", "toggle", { entity_id: ids.bedtime }));
    this._wireSteps(root);
    this._placePopup();
    if (!this._focused) { root.querySelector("#btclose")?.focus(); this._focused = true; }
  }

  // Centre the pop-up over this card rather than the whole window: on a desktop the sidebar shifts the dashboard
  // right, so a window-centred pop-up looks offset. On a phone the card spans the screen, so it stays centred.
  _placePopup() {
    const sheet = this._popEl?.shadowRoot.querySelector(".sheet");
    if (!sheet) return;
    const card = this.getBoundingClientRect(), vw = window.innerWidth, w = sheet.offsetWidth;
    const centre = card.width ? card.left + card.width / 2 : vw / 2;
    const left = Math.max(16, Math.min(vw - w - 16, centre - w / 2));
    sheet.style.marginLeft = `${Math.round(left)}px`;
    if (!this._onResize) { this._onResize = () => this._placePopup(); window.addEventListener("resize", this._onResize); }
  }
  _closePopup() { this._popup = false; this._closePopupEl(); }
  _closePopupEl() {
    if (this._popEl) { this._popEl.remove(); this._popEl = null; }
    if (this._onKey) { window.removeEventListener("keydown", this._onKey); this._onKey = null; }
    if (this._onResize) { window.removeEventListener("resize", this._onResize); this._onResize = null; }
    this._focused = false;
  }
  disconnectedCallback() { this._closePopupEl(); }

  _wireSteps(root) {
    const step = Number(this._config.bedtime_step || 15);
    root.querySelectorAll(".btrow .step").forEach((b) => b.addEventListener("click", () => {
      const ent = b.dataset.ent, cur = this._hass.states[ent]?.state;
      if (!ent || !cur || !cur.includes(":")) return;
      const [h, m] = cur.split(":").map(Number);
      const t = ((h * 60 + m + Number(b.dataset.d) * step) % 1440 + 1440) % 1440;
      this._call("time", "set_value", { entity_id: ent,
        time: `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}:00` });
    }));
  }

  _statusHtml(st, a, look) {
    let sub = "Internet is on";
    const end = a.ends_at ? new Date(a.ends_at) : null;
    if (st.state === "paused") sub = `Back on at ${clock(end)} \u00b7 ${a.minutes_left} min left`;
    else if (st.state === "allowed_for") sub = `${a.minutes_left} min left \u00b7 then ${a.then === "bedtime" ? "bedtime" : "blocked"}`;
    else if (st.state === "bedtime") sub = `Back on at ${hhmm(a.bedtime_end)}`;
    else if (st.state === "blocked") sub = "No time limit";
    const day = (() => { const n = new Date(); const d = n.getHours() >= 12 ? n.getDay() : (n.getDay() + 6) % 7; return d; })();
    const start = (day === 5 || day === 6) ? a.bedtime_weekend_start : a.bedtime_weeknight_start;
    const launch = this._ids().bedtime ? `<ha-icon class="launch" icon="mdi:open-in-new"></ha-icon>` : "";
    const chip = !a.bedtime_enabled ? `<button class="chip off" id="btchip" title="Bedtime settings"><ha-icon icon="mdi:weather-night"></ha-icon>Bedtime off${launch}</button>`
      : `<button class="chip on" id="btchip" title="Bedtime settings"><ha-icon icon="mdi:weather-night"></ha-icon>Bedtime ${hhmm(start)} \u2013 ${hhmm(a.bedtime_end)}${a.allowed_tonight ? " \u00b7 allowed tonight" : a.bedtime_now ? " \u00b7 active" : ""}${launch}</button>`;
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
      const net = r.ssid && r.ssid !== "wired" ? "" : r.ssid === "wired" ? " \u2022 wired" : "";
      const where = (r.ap ? ` \u2022 ${esc(r.ap.replace(/\s+U\d.*$/, ""))} AP` : "") + net;
      const label = r.blocked ? "Blocked" : "Online";
      const status = r.online ? `<span class="${r.blocked ? "red" : "green"}">${label}${where}</span>${bars}` : `Away \u2022 last seen ${seen(r.last_seen)}`;
      const g = !anyBlock ? "" : r.block_entity
        ? `<button class="dglobe ${r.blocked ? "allow" : "block"}" data-ent="${esc(r.block_entity)}" data-on="${r.blocked ? 1 : 0}" title="${r.blocked ? "Allow" : "Block"} ${esc(r.name)}"><ha-icon icon="${r.blocked ? "mdi:web" : "mdi:web-off"}"></ha-icon></button>`
        : "<span></span>";
      const bw = r.online ? `<span class="bw"><span class="dn">${speed(r.down_bps)}</span><span class="dn">\u2193</span><span class="up">${speed(r.up_bps)}</span><span class="up">\u2191</span></span>` : "<span></span>";
      return `<div class="drow${r.online ? "" : " away"}${anyBlock ? " withb" : ""}"><ha-icon class="kind" icon="${KIND_ICON[r.kind] || KIND_ICON.other}"></ha-icon>
        <div class="dtext"><div class="dn1">${esc(r.name)}</div><div class="dn2">${status}</div></div>${g}${bw}</div>`;
    }).join("");
    const foot = a.checked && !live ? `<div class="foot">Checked ${clock(new Date(a.checked))} \u2022 tap Check to refresh</div>` : "";
    return `<ha-card class="group">${head}${body}${foot}</ha-card>`;
  }

  _btRows(ids) {
    return BT_ROWS.map(([key, icon, label]) => `<div class="btrow">
        <ha-icon class="ricon" icon="${icon}"></ha-icon><span class="lbl">${label}</span>
        <button class="step" data-ent="${ids[key] || ""}" data-d="-1" aria-label="${label} earlier"><ha-icon icon="mdi:minus"></ha-icon></button>
        <span class="val">${hhmm(this._hass.states[ids[key]]?.state?.slice(0, 5))}</span>
        <button class="step" data-ent="${ids[key] || ""}" data-d="1" aria-label="${label} later"><ha-icon icon="mdi:plus"></ha-icon></button></div>`).join("");
  }

  _popupHtml(a, ids) {
    // the old Settings tab's design for this child, as a pop-up opened from the Bedtime pill
    const on = this._hass.states[ids.bedtime]?.state === "on";
    return `<div class="scrim" id="scrim"><div class="sheet" role="dialog" aria-label="Bedtime settings">
      <div class="shead"><span class="stitle">${esc(a.child || "")} \u00b7 Bedtime</span>
        <button class="close" id="btclose" aria-label="Close"><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="khead"><span>Bedtime</span><button class="tog${on ? " on" : ""}" id="btsw2" aria-pressed="${on}"><span>${on ? "On" : "Off"}</span><i class="sw"><i></i></i></button></div>
      ${this._btRows(ids)}</div></div>`;
  }

  _bedtimeHtml(a, ids) {
    // collapsible, like Devices: closed it shows a one-line summary; open it has the switch and the three times
    const on = this._hass.states[ids.bedtime]?.state === "on";
    const summary = on ? `${hhmm(a.bedtime_weeknight_start)} \u2013 ${hhmm(a.bedtime_end)}` : "Off";
    const head = `<div class="dhead" id="btoggle"><span class="h">Bedtime${this._btOpen ? ` <ha-icon class="chev" icon="mdi:chevron-up"></ha-icon>` : ""}</span>
      ${this._btOpen ? `<button class="tog${on ? " on" : ""}" id="btsw" aria-pressed="${on}"><span>${on ? "On" : "Off"}</span><i class="sw"><i></i></i></button>`
      : `<span class="hint">${summary} <ha-icon icon="mdi:chevron-down"></ha-icon></span>`}</div>`;
    if (!this._btOpen) return `<ha-card class="group">${head}</ha-card>`;
    return `<ha-card class="group">${head}${this._btRows(ids)}</ha-card>`;
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
    $("#btoggle")?.addEventListener("click", (ev) => {
      if (ev.target.closest("button")) return;
      this._btOpen = !this._btOpen; this._key = null; this._render();
    });
    $("#btsw")?.addEventListener("click", () => this._call("switch", "toggle", { entity_id: ids.bedtime }));
    $("#btchip")?.addEventListener("click", () => { if (!ids.bedtime) return; this._popup = true; this._syncPopup(a, ids); });
    this._wireSteps(this.shadowRoot);
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
.chiprow { margin: 8px 0 0 56px; }   /* the pill's left edge lines up with the status text above */
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; border-radius: 12px; padding: 4px 10px; --mdc-icon-size: 15px; }
.chip.off { color: #9e9e9e; background: rgba(127,127,127,0.12); }
button.chip { cursor: pointer; }
.chip .launch { --mdc-icon-size: 13px; opacity: .75; margin-left: 2px; }
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
.tog { display: inline-flex; gap: 10px; align-items: center; font-size: 13px; color: var(--secondary-text-color); }
.tog .sw { width: 40px; height: 22px; border-radius: 11px; background: rgba(127,127,127,0.35); position: relative; }
.tog .sw i { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #e0e0e0; transition: left .15s; }
.tog.on .sw { background: #7986cb; } .tog.on .sw i { left: 21px; background: #fff; }
.btrow { display: grid; grid-template-columns: 26px minmax(0, 1fr) 38px 86px 38px; gap: 6px; align-items: center; padding: 8px 0; border-top: 1px solid var(--divider-color); }
.btrow .ricon { color: #9fa8da; --mdc-icon-size: 22px; }
.btrow .lbl { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btrow .step { width: 38px; height: 34px; border-radius: 10px; background: rgba(121,134,203,0.2); color: #c5cae9; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 18px; }
.btrow .val { text-align: center; font-size: 16px; font-weight: 600; color: #9fa8da; font-variant-numeric: tabular-nums; white-space: nowrap; }
.foot { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; }
`;

const POPUP_CSS = `
.scrim { position: fixed; inset: 0; z-index: 9999; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: flex-start;
  padding: max(16px, env(safe-area-inset-top, 0px)) 0 max(16px, env(safe-area-inset-bottom, 0px)); }
.sheet { box-sizing: border-box; width: min(420px, calc(100vw - 32px)); flex: none; background: var(--ha-card-background, var(--card-background-color, #1c1c1c)); border-radius: 18px;
  padding: 8px 16px 6px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); color: var(--primary-text-color); }
.shead { display: flex; justify-content: space-between; align-items: center; min-height: 44px; }
.stitle { font-size: 18px; font-weight: 600; }
.close { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 22px; opacity: .8; }
.sheet .khead { display: flex; justify-content: space-between; align-items: center; min-height: 40px; border-top: 1px solid var(--divider-color); font-size: 15px; }
.scrim { font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); color: var(--primary-text-color, #e1e1e1); }
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

/* Parental Controls Settings card: bedtime for every child (or the ones listed), like the Settings tab it replaces.
 *
 *   type: custom:parental-controls-settings-card
 *   # entities: [sensor.riley_parental_controls_internet]   (optional; default: all children)
 *   # step: 15                                                  (optional; minutes per \u2212 / + press)
 */

class ParentalControlsSettingsCard extends HTMLElement {
  setConfig(config) { this._config = config || {}; if (!this.shadowRoot) this.attachShadow({ mode: "open" }); }
  getCardSize() { return 4 * this._children().length + 1; }
  static getStubConfig() { return {}; }
  static getConfigElement() { return document.createElement("parental-controls-settings-card-editor"); }

  set hass(hass) {
    this._hass = hass;
    const ids = this._children().flatMap((c) => Object.values(c.ids));
    const key = ids.map((e) => { const s = hass.states[e]; return s ? s.state + s.last_updated : ""; }).join("|");
    if (key !== this._key) { this._key = key; this._render(); }
  }

  _children() {
    const reg = this._hass?.entities || {};
    const wanted = this._config.entities;
    const sensors = wanted && wanted.length ? wanted : Object.keys(reg).filter((id) =>
      reg[id].platform === "parental_controls" && reg[id].translation_key === "internet").sort();
    return sensors.map((sensor) => {
      const dev = reg[sensor]?.device_id, ids = {};
      for (const [id, e] of Object.entries(reg)) {
        if (dev && e.device_id === dev && e.platform === "parental_controls"
            && ["bedtime", "bedtime_weeknight_start", "bedtime_weekend_start", "bedtime_end"].includes(e.translation_key)) ids[e.translation_key] = id;
      }
      const st = this._hass.states[sensor];
      return { sensor, ids, name: st?.attributes?.child || st?.attributes?.friendly_name || sensor };
    });
  }

  _render() {
    const kids = this._children();
    const title = this._config.title ?? "Bedtime";
    const body = kids.length ? kids.map((k) => {
      const on = this._hass.states[k.ids.bedtime]?.state === "on";
      const rows = BT_ROWS.map(([key, icon, label]) => `<div class="row">
          <ha-icon class="ricon" icon="${icon}"></ha-icon><span class="lbl">${label}</span>
          <button class="step" data-ent="${k.ids[key] || ""}" data-d="-1" aria-label="${label} earlier"><ha-icon icon="mdi:minus"></ha-icon></button>
          <span class="val">${hhmm(this._hass.states[k.ids[key]]?.state?.slice(0, 5))}</span>
          <button class="step" data-ent="${k.ids[key] || ""}" data-d="1" aria-label="${label} later"><ha-icon icon="mdi:plus"></ha-icon></button></div>`).join("");
      return `<ha-card class="kid"><div class="khead"><span class="kname">${esc(k.name)}</span>
          <button class="tog${on ? " on" : ""}" data-ent="${k.ids.bedtime || ""}" aria-pressed="${on}"><span>Bedtime</span><i class="sw"><i></i></i></button></div>${rows}</ha-card>`;
    }).join("") : `<ha-card class="kid"><div class="msg">No children set up yet. Add one: Settings \u2192 Devices &amp; services \u2192 Parental Controls.</div></ha-card>`;
    this.shadowRoot.innerHTML = `<style>${SETTINGS_CSS}</style>${title ? `<div class="title">${esc(title)}</div>` : ""}${body}`;
    this.shadowRoot.querySelectorAll(".tog").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.ent) this._hass.callService("switch", "toggle", { entity_id: b.dataset.ent });
    }));
    const step = Number(this._config.step || 15);
    this.shadowRoot.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
      const ent = b.dataset.ent, cur = this._hass.states[ent]?.state;
      if (!ent || !cur || !cur.includes(":")) return;
      const [h, m] = cur.split(":").map(Number);
      const t = ((h * 60 + m + Number(b.dataset.d) * step) % 1440 + 1440) % 1440;
      const v = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}:00`;
      this._hass.callService("time", "set_value", { entity_id: ent, time: v });
    }));
  }
}

const SETTINGS_CSS = `
:host { display: grid; gap: 10px; }
.title { font-size: 20px; margin: 4px 6px 2px; color: var(--primary-text-color); }
ha-card.kid { padding: 10px 16px 4px; border-radius: 16px; }
button { font: inherit; border: none; cursor: pointer; color: inherit; background: none; padding: 0; }
button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.khead { display: flex; justify-content: space-between; align-items: center; min-height: 44px; border-bottom: 1px solid var(--divider-color); }
.kname { font-size: 20px; font-weight: 600; }
.tog { display: inline-flex; gap: 10px; align-items: center; font-size: 14px; color: var(--secondary-text-color); }
.tog .sw { width: 44px; height: 24px; border-radius: 12px; background: rgba(127,127,127,0.35); position: relative; }
.tog .sw i { position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: #e0e0e0; transition: left .15s; }
.tog.on .sw { background: #7986cb; } .tog.on .sw i { left: 23px; background: #fff; }
.row { display: grid; grid-template-columns: 26px minmax(0, 1fr) 38px 86px 38px; gap: 6px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
.row:last-child { border-bottom: none; }
.ricon { color: #9fa8da; --mdc-icon-size: 22px; }
.lbl { font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step { width: 38px; height: 34px; border-radius: 10px; background: rgba(121,134,203,0.2); color: #c5cae9; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 18px; }
.val { text-align: center; font-size: 17px; font-weight: 600; color: #9fa8da; font-variant-numeric: tabular-nums; white-space: nowrap; }
.msg { font-size: 13px; color: var(--secondary-text-color); padding: 8px 0 12px; }
`;

class ParentalControlsSettingsCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({ entities: "Children (leave empty for all)", title: "Title (optional)", step: "Minutes per \u2212 / + press" })[s.name];
      this._form.schema = [
        { name: "entities", selector: { entity: { integration: "parental_controls", domain: "sensor", multiple: true } } },
        { name: "title", selector: { text: {} } },
        { name: "step", selector: { number: { min: 1, max: 60, step: 1, mode: "box" } } },
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
if (!customElements.get("parental-controls-settings-card")) customElements.define("parental-controls-settings-card", ParentalControlsSettingsCard);
if (!customElements.get("parental-controls-settings-card-editor")) customElements.define("parental-controls-settings-card-editor", ParentalControlsSettingsCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "parental-controls-card")) {
  window.customCards.push({ type: "parental-controls-card", name: "Parental Controls", preview: false,
    description: "One child's internet: status with Block / Allow, Pause or Allow for, and Devices." });
}
if (!window.customCards.some((c) => c.type === "parental-controls-settings-card")) {
  window.customCards.push({ type: "parental-controls-settings-card", name: "Parental Controls Settings", preview: false,
    description: "Bedtime for each child: on/off and the off / back-on times." });
}
