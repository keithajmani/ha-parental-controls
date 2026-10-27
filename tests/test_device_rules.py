"""v0.5: grouped device picking, Device blocking from the router's own rules, the block switch check, the Devices list,
picked devices as Home Assistant devices, and the router entry's reconfigure and re-authenticate flows.
The UniFi console is simulated as in test_devices.py."""
import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_devices import (DOMAIN, HOST, NET, OBJECTS, U, add_child, add_router, check, pick,  # noqa: F401
                           unifi, unifi_switches)

SAM = "Sam"
IPAD, LAPTOP, KOBO, SPEAKER, RILEY_KOBO = ("aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02", "bb:bb:bb:bb:bb:01",
                                           "cc:cc:cc:cc:cc:01", "ee:ee:ee:ee:ee:01")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def setup(hass):
    await add_router(hass)
    unifi_switches(hass)
    return await add_child(hass)


async def open_options(hass, entry, step):
    r = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": step})


def fields(r):
    return {str(k): k for k in r["data_schema"].schema}


def options_of(r, label):
    return [(o["value"], o["label"]) for o in r["data_schema"].schema[fields(r)[label]].config["options"]]


async def pick_all(hass, entry, macs):
    r = await pick(hass, entry, "*", macs)
    assert r["type"] == "create_entry"
    await hass.async_block_till_done()
    return r


# ---- 1. pick devices ------------------------------------------------------------------------------------
async def test_pick_lists_can_be_blocked_and_status_only_with_nothing_ticked(hass, unifi):
    entry = await setup(hass)
    r = await open_options(hass, entry, "add_devices")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": "*"})
    assert r["step_id"] == "pick"
    assert list(fields(r)) == ["Can be blocked", "Status & traffic only"]
    for key in fields(r).values():
        assert key.default() == []                       # nothing pre-selected
    assert options_of(r, "Can be blocked") == [         # the router's order: online first, then by name
        (IPAD, "Sam's iPad · online · Sam's group"),
        (SPEAKER, "Den speaker · offline · own block rule"),
        (LAPTOP, "Sam's laptop · offline · Sam's group")]
    # another child's group, and no group at all: neither can be blocked from Sam's screen
    assert sorted(options_of(r, "Status & traffic only")) == sorted([
        (KOBO, "kobo · offline"), (RILEY_KOBO, "Riley's Kobo · offline")])
    p = r["description_placeholders"]
    assert (p["count"], p["pattern"], p["child"]) == ("5", "*", SAM)


async def test_a_rule_without_a_switch_in_ha_says_so(hass, unifi):
    entry = await setup(hass)
    er.async_get(hass).async_update_entity("switch.unifi_speaker_block", disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    r = await open_options(hass, entry, "add_devices")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": "speaker"})
    assert options_of(r, "Status & traffic only") == [
        (SPEAKER, "Den speaker · offline · rule has no switch in HA")]


async def test_only_internet_off_rules_for_that_one_device_count(hass, unifi):
    """A speed-limit object, or a rule for another group, doesn't make a device blockable from this child's screen."""
    entry = await setup(hass)
    r = await open_options(hass, entry, "add_devices")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": "riley"})
    assert list(fields(r)) == ["Status & traffic only"]   # Riley's group has a block rule, but it's not Sam's


async def test_pick_needs_at_least_one_device(hass, unifi):
    entry = await setup(hass)
    r = await open_options(hass, entry, "add_devices")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": "kobo"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {})
    assert r["step_id"] == "pick" and r["errors"] == {"base": "none_picked"}


async def test_a_device_can_be_picked_by_two_children(hass, unifi):
    await add_router(hass)
    unifi_switches(hass)
    sam = await add_child(hass)
    riley = MockConfigEntry(domain=DOMAIN, title="Riley", unique_id="riley", data={
        "kind": "child", "child_name": "Riley", "block_entity": "input_boolean.speaker_block", "router_group": "Riley"})
    riley.add_to_hass(hass)
    assert await hass.config_entries.async_setup(riley.entry_id)
    await hass.async_block_till_done()
    await pick_all(hass, sam, [SPEAKER])
    await pick_all(hass, riley, [SPEAKER])
    devs = [d for d in dr.async_get(hass).devices.values() if d.name == "Den speaker"]
    assert len(devs) == 2


# ---- 3. device blocking (only for routers that can't read their rules) ------------------------------------
async def test_router_without_rule_lookup_gets_an_unconfirmed_picker(hass, aioclient_mock, unifi):
    entry = await setup(hass)
    aioclient_mock.clear_requests()
    from .test_devices import DEVICES, GROUPS, STA, USERS
    aioclient_mock.post(f"{U}/api/auth/login", json={}, headers={"X-CSRF-Token": "t"})
    aioclient_mock.get(f"{NET}/v2/api/site/default/network-members-groups", json=GROUPS)
    aioclient_mock.get(f"{NET}/api/s/default/rest/user", json={"data": USERS})
    aioclient_mock.get(f"{NET}/api/s/default/stat/device", json={"data": DEVICES})
    aioclient_mock.get(f"{NET}/api/s/default/stat/sta", json={"data": STA})
    aioclient_mock.get(f"{NET}/v2/api/site/default/object-oriented-network-configs", status=404)
    r = await pick(hass, entry, "kobo", [KOBO])
    assert r["step_id"] == "block"
    label = "kobo: block switch (not confirmed)"
    assert list(fields(r)) == [label]
    allowed = r["data_schema"].schema[fields(r)[label]].config["include_entities"]
    assert allowed == sorted(f"switch.{o}" for o in ("unifi_riley_block", "unifi_sam_block", "unifi_sam_speed_limit",
                                                    "unifi_speaker_block"))
    r = await hass.config_entries.options.async_configure(r["flow_id"], {label: "switch.unifi_speaker_block"})
    assert entry.options["devices"][KOBO] == {"name": "kobo", "block_entity": "switch.unifi_speaker_block",
                                              "confirmed": False}


# ---- 4. block switch check -------------------------------------------------------------------------------
async def test_settings_confirm_the_switch_blocks_the_group(hass, unifi):
    entry = await setup(hass)
    hass.config_entries.async_update_entry(entry, options={"block_entity": "switch.unifi_sam_block",
                                                          "router_group": "Sam"})
    await hass.async_block_till_done()
    r = await open_options(hass, entry, "settings")
    assert "Checked on your router: this switch blocks the group Sam." in r["description_placeholders"]["check"]
    assert 'alert-type="success"' in r["description_placeholders"]["check"]


async def test_settings_flag_a_switch_for_another_group(hass, unifi):
    entry = await setup(hass)
    r = await open_options(hass, entry, "settings")
    assert r["description_placeholders"]["check"] == ""      # a test toggle: nothing to check
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"block_entity": "switch.unifi_riley_block", "router_group": "Sam"})
    assert r["type"] == "form" and r["errors"] == {"base": "switch_mismatch"}
    check_html = r["description_placeholders"]["check"]
    assert 'alert-type="error"' in check_html
    assert ("This switch blocks the group Riley, not Sam. Pick the switch that blocks Sam. If there isn't one, your "
            "router needs a rule that turns off internet for the group Sam.") in check_html
    assert ("<b>On your UniFi router</b><br>Add a Policy Engine object for the group Sam, set to No Internet."
            in check_html)
    r = await hass.config_entries.options.async_configure(       # submitted again unchanged: kept anyway
        r["flow_id"], {"block_entity": "switch.unifi_riley_block", "router_group": "Sam"})
    assert r["type"] == "create_entry" and entry.options["block_entity"] == "switch.unifi_riley_block"


async def test_settings_flag_a_switch_that_isnt_a_block_rule(hass, unifi):
    entry = await setup(hass)
    r = await open_options(hass, entry, "settings")
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"block_entity": "switch.unifi_speaker_block", "router_group": "Sam"})
    assert "This switch blocks a single device, not the group Sam." in r["description_placeholders"]["check"]
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"block_entity": "switch.unifi_sam_speed_limit", "router_group": "Sam"})
    assert "This switch doesn't turn off internet on your router." in r["description_placeholders"]["check"]


async def test_adding_a_child_checks_the_switch_too(hass, unifi):
    await add_router(hass)
    unifi_switches(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "child"})
    data = {"child_name": "Riley", "block_entity": "switch.unifi_sam_block", "router_group": "Riley"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], data)
    assert r["errors"] == {"base": "switch_mismatch"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**data, "block_entity": "switch.unifi_riley_block"})
    assert r["type"] == "create_entry"


# ---- 5. card rows ---------------------------------------------------------------------------------------
async def test_rows_say_how_each_device_is_controlled(hass, unifi):
    entry = await setup(hass)
    await pick_all(hass, entry, [KOBO, SPEAKER])
    await hass.services.async_call(DOMAIN, "block", {"config_entry_id": entry.entry_id}, blocking=True)
    st = await check(hass)
    rows = {r["mac"]: r for r in st.attributes["devices"]}
    assert rows[IPAD]["control"] == "group" and rows[IPAD]["blocked"] is True
    assert rows[KOBO]["control"] == "stats" and rows[KOBO]["blocked"] is False
    assert rows[SPEAKER]["control"] == "own" and rows[SPEAKER]["blocked"] is False


def test_card_shows_offline_and_no_tags():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "custom_components/parental_controls/frontend/parental-controls-card.js").read_text()
    assert "Stats only" not in js and 'class="tag"' not in js   # the card shows status and traffic, no labels
    assert "Offline \\u2022 last seen" in js and "Away" not in js
    assert "/\\bAP$/i.test(ap)" in js                      # an AP already named "... AP" isn't shown as "AP AP"
    assert ".bw span:nth-child(odd) { text-align: right; }" in js   # speeds line up against their arrows
    # the Devices chevron sits beside the heading whether open or closed; no "Tap to show" where Live appears
    assert 'Devices <ha-icon class="chev" icon="mdi:chevron-${this._open ? "up" : "down"}">' in js
    assert "Tap to show" not in js
    assert 'Bedtime <ha-icon class="chev" icon="mdi:chevron-${this._btOpen ? "up" : "down"}">' in js


# ---- 6. options menu and the Devices list ----------------------------------------------------------------
async def test_options_menu_always_shows_devices(hass, unifi):
    entry = await setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["menu_options"] == ["settings", "add_devices", "devices"]
    assert r["description_placeholders"] == {"devices": "none"}
    hass.config_entries.options.async_abort(r["flow_id"])
    await pick_all(hass, entry, [KOBO, SPEAKER])
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["description_placeholders"] == {"devices": "2"}


async def test_devices_list_uses_the_same_headings_and_untick_removes(hass, unifi):
    entry = await setup(hass)
    await pick_all(hass, entry, [IPAD, KOBO, SPEAKER, RILEY_KOBO])
    r = await open_options(hass, entry, "devices")
    assert list(fields(r)) == ["Can be blocked", "Status & traffic only"]
    assert fields(r)["Can be blocked"].default() == [IPAD, SPEAKER]          # all ticked to start with
    assert options_of(r, "Can be blocked") == [(IPAD, "Sam's iPad · online · Sam's group"),
                                               (SPEAKER, "Den speaker · offline · own block rule")]
    assert options_of(r, "Status & traffic only") == [(KOBO, "kobo · offline"), (RILEY_KOBO, "Riley's Kobo · offline")]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "Can be blocked": [IPAD, SPEAKER], "Status & traffic only": [RILEY_KOBO]})
    assert r["type"] == "create_entry"
    await hass.async_block_till_done()
    assert set(entry.options["devices"]) == {IPAD, SPEAKER, RILEY_KOBO}
    assert entry.options["devices"][SPEAKER]["block_entity"] == "switch.unifi_speaker_block"
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_{KOBO}")}) is None


async def test_devices_list_picks_up_a_rule_removed_on_the_router(hass, unifi):
    entry = await setup(hass)
    await pick_all(hass, entry, [SPEAKER])
    er.async_get(hass).async_update_entity("switch.unifi_speaker_block", disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    r = await open_options(hass, entry, "devices")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"Can be blocked": [SPEAKER]})
    assert entry.options["devices"][SPEAKER]["block_entity"] is None       # its switch is gone: status only now


# ---- 7. picked devices in Home Assistant -----------------------------------------------------------------
async def test_picked_devices_are_sub_devices_of_the_child(hass, unifi):
    entry = await setup(hass)
    await pick_all(hass, entry, [IPAD, KOBO, SPEAKER])
    reg = dr.async_get(hass)
    child = reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    speaker = reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_{SPEAKER}")})
    assert speaker.via_device_id == child.id and speaker.model == "Picked device"
    assert speaker.serial_number == SPEAKER and not speaker.connections
    await hass.async_block_till_done()
    assert hass.states.get("sensor.den_speaker_blocking").state == "Own block rule"
    assert hass.states.get("sensor.sam_s_ipad_blocking").state == "Follows Sam"
    assert hass.states.get("sensor.kobo_blocking").state == "Status & traffic only"
    assert hass.states.get("binary_sensor.den_speaker_blocked").state == "off"
    assert hass.states.get("binary_sensor.kobo_blocked") is None             # only with its own rule
    assert hass.states.get("binary_sensor.sam_s_ipad_online").state == "unknown"   # until a device check
    await check(hass)
    assert hass.states.get("binary_sensor.sam_s_ipad_online").state == "on"
    assert hass.states.get("binary_sensor.kobo_online").state == "off"
    ents = er.async_entries_for_device(er.async_get(hass), speaker.id)
    assert sorted(e.entity_id.split(".")[0] for e in ents) == ["binary_sensor", "binary_sensor", "sensor"]  # no speeds


async def test_deleting_a_picked_device_removes_it_from_the_child(hass, unifi):
    from custom_components.parental_controls import async_remove_config_entry_device
    entry = await setup(hass)
    await pick_all(hass, entry, [KOBO, SPEAKER])
    reg = dr.async_get(hass)
    kobo = reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_{KOBO}")})
    child = reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert await async_remove_config_entry_device(hass, entry, child) is False      # the child itself stays
    assert await async_remove_config_entry_device(hass, entry, kobo) is True
    await hass.async_block_till_done()
    assert list(entry.options["devices"]) == [SPEAKER]
    assert reg.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_{KOBO}")}) is None


async def test_old_per_device_switches_are_removed(hass, unifi):
    await add_router(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=SAM, unique_id="sam", data={
        "kind": "child", "child_name": SAM, "block_entity": "input_boolean.sam_block"})
    entry.add_to_hass(hass)
    old = er.async_get(hass).async_get_or_create("switch", DOMAIN, f"{entry.entry_id}_device_cccccccccc01",
                                                 config_entry=entry)
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}}})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(old.entity_id) is None


# ---- 8. router entry: reconfigure and re-authenticate ----------------------------------------------------
async def reconfigure(hass, entry):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure",
                                                                      "entry_id": entry.entry_id})


async def test_reconfigure_router_keeps_the_password_when_left_empty(hass, unifi):
    router = await add_router(hass)
    r = await reconfigure(hass, router)
    assert r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"})
    assert r["step_id"] == "reconfigure_connection"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": "10.0.0.1", "username": "ro2"})
    assert r["type"] == "abort" and r["reason"] == "reconfigure_successful"
    assert router.data["username"] == "ro2" and router.data["password"] == "pw" and router.data["site"] == "default"


async def test_reconfigure_tests_the_login_before_saving(hass, aioclient_mock, unifi):
    router = await add_router(hass)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{U}/api/auth/login", status=401)
    r = await reconfigure(hass, router)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": HOST, "username": "x", "password": "y"})
    assert r["type"] == "form" and r["errors"] == {"base": "invalid_auth"}
    assert router.data["username"] == "ro"


async def test_reconfigure_on_a_child_points_to_configure(hass, unifi):
    entry = await setup(hass)
    r = await reconfigure(hass, entry)
    assert r["type"] == "abort" and r["reason"] == "child_use_configure"


async def test_changing_router_type_reports_children_that_no_longer_match(hass, unifi, monkeypatch):
    from custom_components.parental_controls import provider
    test_type = provider.RouterType(key="test", label="Test router", name="Test", integration="unifi")
    monkeypatch.setitem(provider.ROUTER_TYPES, "test", test_type)
    router = await add_router(hass)
    unifi_switches(hass)
    entry = await add_child(hass)
    hass.config_entries.async_update_entry(entry, options={"block_entity": "switch.unifi_riley_block",
                                                          "router_group": "Sam"})
    await hass.async_block_till_done()
    r = await reconfigure(hass, router)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "test"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": HOST, "username": "ro"})
    assert r["reason"] == "reconfigure_mismatch"
    assert r["description_placeholders"]["problems"] == "- Sam: the block switch doesn't block the group Sam"
    assert router.data["vendor"] == "test"


async def test_router_entries_without_a_type_count_as_unifi(hass, unifi):
    from custom_components.parental_controls.rules import type_of
    router = MockConfigEntry(domain=DOMAIN, title="UniFi", unique_id="router", data={
        "kind": "router", "host": HOST, "username": "ro", "password": "pw", "site": "default"})
    router.add_to_hass(hass)
    assert type_of(router).key == "unifi"
    assert await hass.config_entries.async_setup(router.entry_id)
    r = await reconfigure(hass, router)
    assert fields(r)["vendor"].default() == "unifi"


async def test_reauth_updates_the_login(hass, unifi):
    router = await add_router(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "reauth", "entry_id": router.entry_id},
                                                  data=router.data)
    assert r["step_id"] == "reauth_confirm" and r["description_placeholders"]["host"] == HOST
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"username": "ro", "password": "new"})
    assert r["type"] == "abort" and r["reason"] == "reauth_successful"
    assert router.data["password"] == "new"


async def test_a_rejected_login_during_a_check_asks_to_sign_in_again(hass, aioclient_mock, unifi):
    await add_router(hass)
    await add_child(hass)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{U}/api/auth/login", status=401)
    aioclient_mock.get(f"{NET}/api/s/default/stat/sta", status=401)
    client = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    client._cache.at = 0                       # force a fresh fetch
    client._logged_in = False
    await check(hass)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)


# ---- the UniFi rule reader ------------------------------------------------------------------------------
async def test_unifi_reads_only_internet_off_objects(hass, unifi):
    router = await add_router(hass)
    rules = await router.runtime_data.block_rules()
    assert set(rules) == {f"object_oriented_network_config-o{i}" for i in (1, 2, 3)}   # the speed limit is left out
    assert rules["object_oriented_network_config-o1"].groups == ["Sam"]
    assert rules["object_oriented_network_config-o3"].macs == [SPEAKER] and not rules[
        "object_oriented_network_config-o3"].groups


def test_a_mac_is_shown_only_to_tell_same_named_devices_apart():
    from custom_components.parental_controls.config_flow import _duplicate_names
    assert _duplicate_names({"a": "Kobo", "b": "kobo ", "c": "iPad"}) == {"a", "b"}


# ---- every screen supplies the placeholders its text uses -----------------------------------------------
def _needed(section: str, step: str, key: str = "description") -> set[str]:
    import json
    import re
    from pathlib import Path
    strings = json.loads((Path(__file__).parent.parent / "custom_components/parental_controls/strings.json").read_text())
    text = strings[section]["step"][step].get(key, "")
    if isinstance(text, dict):
        text = " ".join(text.values())
    return set(re.findall(r"{(\w+)}", text))


def _supplied(r) -> set[str]:
    return set(r.get("description_placeholders") or {})


async def test_every_screen_supplies_the_placeholders_its_text_uses(hass, aioclient_mock, unifi):
    """A text that uses {x} which the screen doesn't send shows as a translation error in the browser."""
    entry = await setup(hass)
    seen = []

    def check(r, section):
        if r.get("type") in ("form", "menu"):
            key = "menu_options" if r["type"] == "menu" else "description"
            missing = _needed(section, r["step_id"], key) - _supplied(r)
            assert not missing, f"{section}.{r['step_id']} doesn't supply {missing}"
            seen.append(r["step_id"])

    r = await hass.config_entries.options.async_init(entry.entry_id); check(r, "options")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "settings"}); check(r, "options")
    r = await open_options(hass, entry, "add_devices"); check(r, "options")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": "*"}); check(r, "options")
    r = await open_options(hass, entry, "devices"); check(r, "options")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"}); check(r, "config")
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "child"}); check(r, "config")
    router = hass.config_entries.async_entries(DOMAIN)[0]
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure", "entry_id": router.entry_id})
    check(r, "config")
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"}); check(r, "config")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "reauth", "entry_id": router.entry_id},
                                                  data=router.data)
    check(r, "config")
    # the Device blocking step: only for a router that can't read its rules
    from .test_devices import DEVICES, GROUPS, STA, USERS
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{U}/api/auth/login", json={}, headers={"X-CSRF-Token": "t"})
    aioclient_mock.get(f"{NET}/v2/api/site/default/network-members-groups", json=GROUPS)
    aioclient_mock.get(f"{NET}/api/s/default/rest/user", json={"data": USERS})
    aioclient_mock.get(f"{NET}/api/s/default/stat/device", json={"data": DEVICES})
    aioclient_mock.get(f"{NET}/api/s/default/stat/sta", json={"data": STA})
    aioclient_mock.get(f"{NET}/v2/api/site/default/object-oriented-network-configs", status=404)
    router.runtime_data._rules = (0.0, {})
    r = await pick(hass, entry, "kobo", [KOBO]); check(r, "options")
    assert {"init", "settings", "add_devices", "pick", "devices", "user", "child", "reconfigure",
            "reconfigure_connection", "reauth_confirm", "block"} <= set(seen)


# ---- auto-detect: router switches appearing, disappearing or being disabled ----------------------------
async def _quiet(hass, freezer, seconds=11):
    from datetime import timedelta
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    freezer.tick(timedelta(seconds=seconds)); async_fire_time_changed(hass); await hass.async_block_till_done()


async def test_a_new_switch_for_a_device_rule_is_attached_by_itself(hass, unifi, freezer):
    await add_router(hass)
    entry = await add_child(hass)                       # no UniFi switches in HA yet
    await pick_all(hass, entry, [SPEAKER])
    assert entry.options["devices"][SPEAKER]["block_entity"] is None          # status & traffic only
    unifi_switches(hass)                                # the UniFi integration adds its switches
    await hass.async_block_till_done()
    assert entry.options["devices"][SPEAKER]["block_entity"] is None          # waits for things to settle
    await _quiet(hass, freezer)
    assert entry.options["devices"][SPEAKER] == {"name": "Den speaker", "block_entity": "switch.unifi_speaker_block",
                                                 "confirmed": True}
    assert hass.states.get("binary_sensor.den_speaker_blocked") is not None   # reloaded with its Blocked sensor
    assert hass.states.get("switch.unifi_speaker_block").state == "off"       # the switch itself untouched


async def test_a_removed_or_disabled_switch_is_detached_by_itself(hass, unifi, freezer):
    from homeassistant.helpers import issue_registry as ir
    entry = await setup(hass)
    await pick_all(hass, entry, [SPEAKER])
    assert entry.options["devices"][SPEAKER]["block_entity"] == "switch.unifi_speaker_block"
    ir.async_create_issue(hass, DOMAIN, f"{entry.entry_id}_device_cccccccccc01", is_fixable=False,
                          severity=ir.IssueSeverity.WARNING, translation_key="device_block_switch_missing")
    er.async_get(hass).async_update_entity("switch.unifi_speaker_block", disabled_by=er.RegistryEntryDisabler.USER)
    await _quiet(hass, freezer)
    assert entry.options["devices"][SPEAKER]["block_entity"] is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_device_cccccccccc01") is None
    er.async_get(hass).async_update_entity("switch.unifi_speaker_block", disabled_by=None)       # enabled again
    await _quiet(hass, freezer)
    assert entry.options["devices"][SPEAKER]["block_entity"] == "switch.unifi_speaker_block"
    er.async_get(hass).async_remove("switch.unifi_speaker_block")                               # gone
    await _quiet(hass, freezer)
    assert entry.options["devices"][SPEAKER]["block_entity"] is None


async def test_a_burst_of_switch_changes_reads_the_rules_once(hass, aioclient_mock, unifi, freezer):
    await add_router(hass)
    entry = await add_child(hass)
    await pick_all(hass, entry, [SPEAKER])
    url = f"{NET}/v2/api/site/default/object-oriented-network-configs"
    before = sum(1 for call in aioclient_mock.mock_calls if str(call[1]) == url)
    reg = er.async_get(hass)
    for i in range(20):                                 # e.g. the UniFi integration reloading
        reg.async_get_or_create("switch", "unifi", f"something-{i}", suggested_object_id=f"unifi_x{i}")
        await _quiet(hass, freezer, seconds=1)
    unifi_switches(hass)
    await _quiet(hass, freezer)
    after = sum(1 for call in aioclient_mock.mock_calls if str(call[1]) == url)
    assert after - before == 1
    assert entry.options["devices"][SPEAKER]["block_entity"] == "switch.unifi_speaker_block"


async def test_a_hand_picked_switch_is_left_alone(hass, unifi, freezer):
    entry = await setup(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "devices": {
        KOBO: {"name": "kobo", "block_entity": "input_boolean.speaker_block", "confirmed": False}}})
    await hass.async_block_till_done()
    er.async_get(hass).async_get_or_create("switch", "unifi", "new-thing", suggested_object_id="unifi_new")
    await _quiet(hass, freezer)
    assert entry.options["devices"][KOBO]["block_entity"] == "input_boolean.speaker_block"


async def test_a_switch_made_before_this_version_is_matched_once_after_loading(hass, unifi, freezer):
    """A rule and its switch that already existed (e.g. made while on an older version) are picked up after a restart,
    without any switch change to trigger it."""
    await add_router(hass)
    unifi_switches(hass)
    entry = MockConfigEntry(domain=DOMAIN, title=SAM, unique_id="sam", data={
        "kind": "child", "child_name": SAM, "block_entity": "input_boolean.sam_block", "router_group": "Sam"},
        options={"devices": {SPEAKER: {"name": "Den speaker", "block_entity": None, "confirmed": False}}})
    entry.add_to_hass(hass)
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}}})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _quiet(hass, freezer, seconds=30)
    assert entry.options["devices"][SPEAKER]["block_entity"] is None          # not yet
    await _quiet(hass, freezer, seconds=31)
    assert entry.options["devices"][SPEAKER]["block_entity"] == "switch.unifi_speaker_block"


def test_picked_devices_are_linked_by_device_id_where_home_assistant_supports_it(monkeypatch):
    """HA 2026.10 deprecates via_device; the child device's id is used where async_get_or_create takes via_device_id,
    and the identifier only on older versions (the minimum in hacs.json)."""
    from types import SimpleNamespace
    from homeassistant.helpers import device_registry
    from custom_components.parental_controls import _via
    from custom_components.parental_controls.entity import picked_device_info
    child = SimpleNamespace(id="child-device-id")

    def new_style(self, *, config_entry_id, via_device_id=None, **kw):
        pass
    monkeypatch.setattr(device_registry.DeviceRegistry, "async_get_or_create", new_style)
    assert _via(child, "entry1") == {"via_device_id": "child-device-id"}

    def old_style(self, *, config_entry_id, via_device=None, **kw):
        pass
    monkeypatch.setattr(device_registry.DeviceRegistry, "async_get_or_create", old_style)
    assert _via(child, "entry1") == {"via_device": (DOMAIN, "entry1")}
    info = picked_device_info(SimpleNamespace(entry_id="entry1"), SPEAKER, {"name": "Den speaker"})
    assert "via_device" not in info                    # entities never link with the deprecated parameter


def test_card_reads_a_device_switch_directly_and_shows_a_pending_tap():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "custom_components/parental_controls/frontend/parental-controls-card.js").read_text()
    # blocked comes from the device's own switch (the Devices list only as a fallback when the switch is missing)
    assert 'const blocked = sw && (sw.state === "on" || sw.state === "off") ? sw.state === "on" : !!r.blocked;' in js
    # a tap dims the button with a spinner until the switch (or the child's status) confirms, else an error after 10 s
    assert "setTimeout(() => this._fail(key), 10000)" in js and 'class="spin"' in js and "Couldn't ${p.want" in js
    assert '"still blocked" : "still online"' in js         # the message says what is still true
    assert 'this._send("child"' in js and "this._send(ent, want" in js
