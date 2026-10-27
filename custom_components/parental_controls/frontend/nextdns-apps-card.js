/* Parental Controls NextDNS apps card: block or allow apps on one NextDNS profile, with the switches that Home
 * Assistant's built-in NextDNS integration already makes. Nothing of its own runs in Home Assistant.
 *
 *   type: custom:parental-controls-apps-card
 *   profile: <device id of the NextDNS profile>      (the editor lists them)
 *   # title: Kids' apps                                 (optional; default: the profile's name)
 *   # apps: [instagram, youtube, minecraft]             (optional; default every app switch turned on in HA)
 *   # icons: { roblox: mdi:cube-outline }               (optional; per-app icon)
 *
 * The NextDNS integration makes one switch per app and category, all turned off (disabled) in Home Assistant at
 * first. Only the ones turned on in HA show here. On = blocked. See docs/nextdns-card.md.
 *
 * Its own file, served and registered like parental-controls-card.js; it shares nothing with the router cards.
 */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const APP_GROUPS = ["Social", "Messaging", "Streaming", "Games", "More", "Categories"];
// NextDNS id (the switch's translation key without "block_") -> [name, icon, group]; order within a group is the
// order shown. Apps without a brand icon in Material Design Icons get a plain one.
const APPS = {
  instagram: ["Instagram", "mdi:instagram", "Social"], snapchat: ["Snapchat", "mdi:snapchat", "Social"],
  facebook: ["Facebook", "mdi:facebook", "Social"], reddit: ["Reddit", "mdi:reddit", "Social"],
  tiktok: ["TikTok", "mdi:music-note", "Social"], twitter: ["X", "mdi:alpha-x-box-outline", "Social"],
  pinterest: ["Pinterest", "mdi:pinterest", "Social"], tumblr: ["Tumblr", "mdi:alpha-t-box-outline", "Social"],
  bereal: ["BeReal", "mdi:camera-front", "Social"], mastodon: ["Mastodon", "mdi:mastodon", "Social"],
  vk: ["VK", "mdi:alpha-v-box-outline", "Social"], "9gag": ["9GAG", "mdi:emoticon-lol", "Social"],
  imgur: ["Imgur", "mdi:image-multiple", "Social"],
  whatsapp: ["WhatsApp", "mdi:whatsapp", "Messaging"], messenger: ["Messenger", "mdi:facebook-messenger", "Messaging"],
  telegram: ["Telegram", "mdi:send", "Messaging"], signal: ["Signal", "mdi:message-lock-outline", "Messaging"],
  discord: ["Discord", "mdi:forum", "Messaging"], skype: ["Skype", "mdi:skype", "Messaging"],
  zoom: ["Zoom", "mdi:video-outline", "Messaging"], google_chat: ["Google Chat", "mdi:google-hangouts", "Messaging"],
  youtube: ["YouTube", "mdi:youtube", "Streaming"], netflix: ["Netflix", "mdi:netflix", "Streaming"],
  disneyplus: ["Disney+", "mdi:castle", "Streaming"], primevideo: ["Prime Video", "mdi:filmstrip-box", "Streaming"],
  hbomax: ["HBO Max", "mdi:television-classic", "Streaming"], hulu: ["Hulu", "mdi:hulu", "Streaming"],
  twitch: ["Twitch", "mdi:twitch", "Streaming"], vimeo: ["Vimeo", "mdi:vimeo", "Streaming"],
  dailymotion: ["Dailymotion", "mdi:play-circle-outline", "Streaming"], spotify: ["Spotify", "mdi:spotify", "Streaming"],
  xboxlive: ["Xbox", "mdi:microsoft-xbox", "Games"], steam: ["Steam", "mdi:steam", "Games"],
  roblox: ["Roblox", "mdi:gamepad-variant", "Games"], fortnite: ["Fortnite", "mdi:pickaxe", "Games"],
  minecraft: ["Minecraft", "mdi:minecraft", "Games"],
  playstation_network: ["PlayStation", "mdi:sony-playstation", "Games"],
  leagueoflegends: ["League of Legends", "mdi:sword", "Games"], blizzard: ["Blizzard", "mdi:snowflake", "Games"],
  chatgpt: ["ChatGPT", "mdi:robot-outline", "More"], amazon: ["Amazon", "mdi:cart", "More"],
  ebay: ["eBay", "mdi:shopping", "More"], tinder: ["Tinder", "mdi:fire", "More"],
  porn: ["Porn", "mdi:eye-off", "Categories"], gambling: ["Gambling", "mdi:dice-multiple", "Categories"],
  dating: ["Dating", "mdi:heart-multiple", "Categories"], piracy: ["Piracy", "mdi:skull-crossbones", "Categories"],
  social_networks: ["Social networks", "mdi:account-group", "Categories"],
  online_gaming: ["Online gaming", "mdi:gamepad-variant-outline", "Categories"],
  video_streaming: ["Video streaming", "mdi:play-box-multiple", "Categories"],
};

// the profile's app and category switches that Home Assistant has turned on: {app id: entity id}
const nextdnsSwitches = (hass, profile) => {
  const out = {};
  for (const [id, e] of Object.entries(hass?.entities || {})) {
    if (e.platform !== "nextdns" || e.device_id !== profile || !e.translation_key?.startsWith("block_")) continue;
    const app = e.translation_key.slice(6);
    if (APPS[app] && hass.states[id]) out[app] = id;
  }
  return out;
};
const nextdnsProfiles = (hass) => {
  const devs = new Set();
  for (const e of Object.values(hass?.entities || {})) {
    if (e.platform === "nextdns" && e.device_id && e.translation_key?.startsWith("block_")) devs.add(e.device_id);
  }
  return [...devs];
};
const deviceName = (hass, id) => { const d = hass?.devices?.[id]; return d?.name_by_user || d?.name || ""; };
const navigate = (path) => {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

class ParentalControlsAppsCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._pending = {};   // entity -> {want, name, timer}: a block/allow sent, not yet confirmed
    this._err = null;
    this._key = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }
  getCardSize() { return 2 + Object.keys(this._shown()).length; }
  static getStubConfig(hass) { return { profile: nextdnsProfiles(hass)[0] || "" }; }
  static getConfigElement() { return document.createElement("parental-controls-apps-card-editor"); }

  set hass(hass) {
    this._hass = hass;
    const shown = this._shown();
    for (const [id, p] of Object.entries(this._pending)) {
      if ((hass.states[id]?.state === "on") === p.want) { clearTimeout(p.timer); delete this._pending[id]; }
    }
    const key = Object.values(shown).map((id) => (hass.states[id]?.state || "") + id).join("|")
      + Object.keys(this._pending).join() + (this._err || "");
    if (key !== this._key) { this._key = key; this._render(); }
  }

  // apps to show: the ones picked (or all), whose switch is turned on in HA
  _shown() {
    const found = nextdnsSwitches(this._hass, this._config.profile);
    const picked = Array.isArray(this._config.apps) ? new Set(this._config.apps.map(String)) : null;
    return Object.fromEntries(Object.entries(found).filter(([app]) => !picked || picked.has(app)));
  }

  _tap(id, app) {
    if (this._pending[id]) return;
    const st = this._hass.states[id]?.state;
    if (st !== "on" && st !== "off") return;
    const want = st !== "on", name = APPS[app][0];
    const timer = setTimeout(() => this._fail(id), 10000);
    this._pending[id] = { want, name, timer };
    this._key = null; this._render();
    this._hass.callService("switch", want ? "turn_on" : "turn_off", { entity_id: id }).catch((err) => this._fail(id, err));
  }
  _fail(id, err) {
    const p = this._pending[id];
    if (!p) return;
    clearTimeout(p.timer); delete this._pending[id];
    const why = err ? `: ${err.message || err}` : ": no answer from NextDNS";
    const now = this._hass.states[id]?.state === "on" ? "still blocked" : "still allowed";
    this._err = `Couldn't ${p.want ? "block" : "allow"} ${p.name}${why}. It's ${now}.`;
    clearTimeout(this._errTimer);
    this._errTimer = setTimeout(() => { this._err = null; this._key = null; this._render(); }, 8000);
    this._key = null; this._render();
  }

  _render() {
    const hass = this._hass, profile = this._config.profile;
    const name = deviceName(hass, profile);
    const title = this._config.title ?? (name || "Apps");
    const head = `<style>${APPS_CSS}</style>${title ? `<div class="title">${esc(title)}</div>` : ""}`;
    if (!profile || !name) {
      this.shadowRoot.innerHTML = `${head}<ha-card class="grp"><div class="msg">Pick a NextDNS profile in this card's settings. The NextDNS integration has to be set up first.</div></ha-card>`;
      return;
    }
    const shown = this._shown();
    if (!Object.keys(shown).length) {
      this.shadowRoot.innerHTML = `${head}<ha-card class="grp"><div class="msg">No apps to show yet. Home Assistant
        keeps the NextDNS app switches turned off until you turn them on.
        <a href="/config/devices/device/${esc(profile)}" class="open">Open ${esc(name)}</a>, show its hidden
        entities and turn on the apps you want. Turning one on doesn't block it.</div></ha-card>`;
      this._wireLinks();
      return;
    }
    const icons = this._config.icons || {};
    const groups = APP_GROUPS.map((g) => {
      const rows = Object.keys(APPS).filter((app) => APPS[app][2] === g && shown[app]).map((app) => {
        const id = shown[app], st = hass.states[id]?.state, p = this._pending[id];
        const look = p ? (p.want ? "on" : "off") : st === "on" ? "on" : st === "off" ? "off" : "na";
        const text = p ? (p.want ? "Blocking\u2026" : "Allowing\u2026") : look === "on" ? "Blocked" : look === "off" ? "Allowed" : "Unavailable";
        return `<button class="app ${look}${p ? " wait" : ""}" data-id="${id}" data-app="${app}" ${look === "na" ? "disabled" : ""}
            aria-label="${esc(APPS[app][0])}: ${text}"><span class="ic"><ha-icon icon="${esc(icons[app] || APPS[app][1])}"></ha-icon></span>
            <span class="txt"><span class="nm">${esc(APPS[app][0])}</span><span class="st">${text}</span></span></button>`;
      });
      return rows.length ? `<ha-card class="grp"><div class="gh">${g}</div><div class="rows">${rows.join("")}</div></ha-card>` : "";
    }).join("");
    this.shadowRoot.innerHTML = `${head}${this._err ? `<div class="err">${esc(this._err)}</div>` : ""}${groups}`;
    this.shadowRoot.querySelectorAll("button.app").forEach((b) => b.addEventListener("click", () => this._tap(b.dataset.id, b.dataset.app)));
  }
  _wireLinks() {
    this.shadowRoot.querySelectorAll("a.open").forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault(); navigate(a.getAttribute("href"));
    }));
  }
}

const APPS_CSS = `
:host { display: grid; gap: 12px; }
.title { font-size: 24px; margin: 4px 4px 0; color: var(--primary-text-color); }
ha-card.grp { padding: 12px 14px 14px; border-radius: 16px; }
.gh { font-size: 16px; font-weight: 600; margin: 0 2px 8px; }
.rows { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
button { font: inherit; border: none; cursor: pointer; color: inherit; background: none; padding: 0; text-align: left; }
button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.app { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 8px 10px; border-radius: 14px; }
.app .ic { width: 36px; height: 36px; flex: none; border-radius: 50%; display: flex; align-items: center; justify-content: center; --mdc-icon-size: 20px; }
.app .txt { display: grid; min-width: 0; }
.app .nm { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.app .st { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; }
.app.on { background: rgba(244,67,54,0.14); } .app.on .ic { background: rgba(244,67,54,0.2); color: #f44336; }
.app.off { background: rgba(76,175,80,0.12); } .app.off .ic { background: rgba(76,175,80,0.2); color: #4caf50; }
.app.na { background: rgba(127,127,127,0.1); cursor: default; } .app.na .ic { background: rgba(127,127,127,0.18); color: var(--disabled-text-color, #8a8a8a); }
.app.wait { opacity: .7; cursor: progress; }
.msg { font-size: 14px; color: var(--secondary-text-color); line-height: 1.45; }
.msg a { color: var(--primary-color); }
.err { font-size: 13px; color: var(--error-color, #ef5350); margin: 0 4px; }
`;

class ParentalControlsAppsCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({ profile: "NextDNS profile", title: "Title (optional; default: the profile's name)" })[s.name] || s.label || s.name;
      this._form.addEventListener("value-changed", (ev) => this._changed(ev.detail.value));
      this._hint = document.createElement("div");
      this._hint.style.cssText = "font-size:13px;color:var(--secondary-text-color);line-height:1.45;margin-top:12px";
      this.append(this._form, this._hint);
    }
    const profile = this._config.profile, found = nextdnsSwitches(this._hass, profile);
    const sig = profile + Object.keys(found).join();
    if (sig !== this._sig) {   // the app lists only change with the profile or the switches turned on in HA
      this._sig = sig;
      const schema = [
        { name: "profile", required: true, selector: { device: { integration: "nextdns" } } },
        { name: "title", selector: { text: {} } },
      ];
      for (const g of APP_GROUPS) {
        const opts = Object.keys(APPS).filter((a) => APPS[a][2] === g && found[a]).map((a) => ({ value: a, label: APPS[a][0] }));
        if (opts.length) schema.push({ name: `g_${g}`, label: g, selector: { select: { multiple: true, mode: "list", options: opts } } });
      }
      this._form.schema = schema;
      this._groupsShown = schema.slice(2).map((s) => s.name);
      this._countHidden(profile);
    }
    const data = { profile, title: this._config.title };
    const picked = Array.isArray(this._config.apps) ? new Set(this._config.apps) : null;
    for (const g of APP_GROUPS) data[`g_${g}`] = Object.keys(found).filter((a) => APPS[a][2] === g && (!picked || picked.has(a)));
    this._form.hass = this._hass;
    this._form.data = data;
  }
  _changed(v) {
    const found = nextdnsSwitches(this._hass, v.profile);
    const config = { ...this._config, profile: v.profile };
    if (v.title) config.title = v.title; else delete config.title;
    if (v.profile !== this._config.profile) delete config.apps;   // a new profile starts with all its apps
    else {
      const picked = this._groupsShown.flatMap((k) => v[k] || []);
      // every app ticked: leave "apps" out, so apps turned on in HA later show up by themselves
      if (picked.length === Object.keys(found).length) delete config.apps; else config.apps = picked;
    }
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
  // how many of the profile's app switches are still turned off in HA (the full registry needs an admin)
  async _countHidden(profile) {
    let hidden = null;
    try {
      const all = await this._hass.callWS({ type: "config/entity_registry/list" });
      hidden = all.filter((e) => e.platform === "nextdns" && e.device_id === profile && e.disabled_by
        && e.translation_key?.startsWith("block_") && APPS[e.translation_key.slice(6)]).length;
    } catch (err) { /* not an admin: say it without a number */ }
    if (!profile) { this._hint.innerHTML = ""; return; }
    const what = hidden === null ? "Apps you don't see here are" : hidden ? `${hidden} more apps and categories are` : "";
    this._hint.innerHTML = what ? `${what} turned off in Home Assistant.
      <a href="/config/devices/device/${esc(profile)}" style="color:var(--primary-color)">Open the profile</a>, show its
      hidden entities and turn on the ones you want. They appear here as Allowed; turning one on doesn't block it.` : "";
    this._hint.querySelectorAll("a").forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault(); navigate(a.getAttribute("href"));
    }));
  }
}

window.customCards = window.customCards || [];
if (!customElements.get("parental-controls-apps-card")) customElements.define("parental-controls-apps-card", ParentalControlsAppsCard);
if (!customElements.get("parental-controls-apps-card-editor")) customElements.define("parental-controls-apps-card-editor", ParentalControlsAppsCardEditor);
if (!window.customCards.some((c) => c.type === "parental-controls-apps-card")) {
  window.customCards.push({ type: "parental-controls-apps-card", name: "Parental Controls NextDNS apps", preview: false,
    description: "Block or allow apps on a NextDNS profile, using the NextDNS integration's switches." });
}
