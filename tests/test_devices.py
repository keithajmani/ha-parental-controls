"""Stage 2: router connection, device search and pick, the Devices list, Live, and per-device blocks.
The UniFi console is simulated with Home Assistant's aiohttp test mocker."""
import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "parental_controls"
HOST = "10.0.0.1"
U = f"https://{HOST}"
NET = f"{U}/proxy/network"
GROUPS = [{"id": "g1", "name": "Sam", "members": ["aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02"]},
          {"id": "g2", "name": "Riley", "members": ["ee:ee:ee:ee:ee:01"]}]
USERS = [
    {"mac": "aa:aa:aa:aa:aa:01", "name": "Sam's iPad", "last_seen": 1790000000},
    {"mac": "aa:aa:aa:aa:aa:02", "name": "Sam's laptop", "last_seen": 1790000000},
    {"mac": "bb:bb:bb:bb:bb:01", "hostname": "kobo", "last_seen": 1789000000},
    {"mac": "cc:cc:cc:cc:cc:01", "name": "Den speaker", "last_seen": 1790000000},
    {"mac": "ee:ee:ee:ee:ee:01", "name": "Riley's Kobo", "last_seen": 1790000000},
]
TURN_OFF = {"enabled": True, "internet": {"mode": "TURN_OFF_INTERNET", "schedule": {"mode": "ALWAYS"}}}
OBJECTS = [   # UniFi Policy Engine objects; HA's UniFi integration shows each as a switch
    {"id": "o1", "name": "Sam Block", "enabled": False, "target_type": "GROUPS",
     "targets": [{"type": "NETWORK_GROUP_ID", "value": "g1"}], "secure": TURN_OFF},
    {"id": "o2", "name": "Riley Block", "enabled": False, "target_type": "GROUPS",
     "targets": [{"type": "NETWORK_GROUP_ID", "value": "g2"}], "secure": TURN_OFF},
    {"id": "o3", "name": "Den speaker block", "enabled": False, "target_type": "CLIENTS",
     "targets": [{"type": "MAC", "value": "CC:CC:CC:CC:CC:01"}], "secure": TURN_OFF},
    {"id": "o4", "name": "Sam speed limit", "enabled": True, "target_type": "GROUPS",
     "targets": [{"type": "NETWORK_GROUP_ID", "value": "g1"}],
     "secure": {"enabled": False, "internet": {"everything": True, "mode": "BLOCKLIST"}}},
]
UNIFI_SWITCHES = {"o1": "unifi_sam_block", "o2": "unifi_riley_block", "o3": "unifi_speaker_block",
                  "o4": "unifi_sam_speed_limit"}


def unifi_switches(hass):
    """Stand-ins for the UniFi Network integration's Policy Engine switches (registry entries plus states)."""
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    for oid, obj in UNIFI_SWITCHES.items():
        reg.async_get_or_create("switch", "unifi", f"object_oriented_network_config-{oid}", suggested_object_id=obj)
        hass.states.async_set(f"switch.{obj}", "off")
STA = [{"mac": "aa:aa:aa:aa:aa:01", "name": "Sam's iPad", "essid": "home", "ap_mac": "dd:dd:dd:dd:dd:01",
        "signal": -60, "tx_bytes": 1000, "rx_bytes": 500, "tx_bytes-r": 125000, "rx_bytes-r": 1250}]
DEVICES = [{"mac": "dd:dd:dd:dd:dd:01", "type": "uap", "name": "Loft AP"}]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def unifi(aioclient_mock):
    aioclient_mock.post(f"{U}/api/auth/login", json={}, headers={"X-CSRF-Token": "t"})
    aioclient_mock.get(f"{NET}/api/self/sites", json={"data": [{"name": "default", "desc": "Default"}]})
    aioclient_mock.get(f"{NET}/v2/api/site/default/network-members-groups", json=GROUPS)
    aioclient_mock.get(f"{NET}/api/s/default/rest/user", json={"data": USERS})
    aioclient_mock.get(f"{NET}/api/s/default/stat/device", json={"data": DEVICES})
    aioclient_mock.get(f"{NET}/api/s/default/stat/sta", json={"data": STA})
    aioclient_mock.get(f"{NET}/v2/api/site/default/object-oriented-network-configs", json=OBJECTS)
    return aioclient_mock


async def add_router(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "router"})
    assert r["step_id"] == "router"                       # pick the router vendor first
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": HOST, "username": "ro", "password": "pw"})
    assert r["type"] == "create_entry", r                 # one site: picked automatically, no Site question
    assert r["result"].data["site"] == "default" and r["result"].data["vendor"] == "unifi"
    await hass.async_block_till_done()
    return r["result"]


async def add_child(hass, group="Sam"):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {
        "sam_block": {}, "speaker_block": {}}})
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "child"})
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {"child_name": "Sam", "block_entity": "input_boolean.sam_block", "router_group": group})
    assert r["type"] == "create_entry", r
    await hass.async_block_till_done()
    return r["result"]


async def check(hass):
    await hass.services.async_call("button", "press", {"entity_id": "button.sam_parental_controls_check_devices"},
                                   blocking=True)
    await hass.async_block_till_done()
    return hass.states.get("sensor.sam_parental_controls_devices")


async def test_router_flow_rejects_a_bad_login(hass, aioclient_mock):
    aioclient_mock.post(f"{U}/api/auth/login", status=401)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "router"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": HOST, "username": "ro", "password": "bad"})
    assert r["type"] == "form" and r["errors"] == {"base": "invalid_auth"}


async def test_group_members_are_listed_with_status_and_speed(hass, unifi):
    await add_router(hass)
    await add_child(hass)
    st = await check(hass)
    rows = {r["mac"]: r for r in st.attributes["devices"]}
    assert st.state == "1"                                  # one of the two group devices is online
    ipad = rows["aa:aa:aa:aa:aa:01"]
    assert ipad["online"] and ipad["in_group"] and ipad["ap"] == "Loft AP" and ipad["kind"] == "tablet"
    assert ipad["down_bps"] == 1_000_000 and ipad["up_bps"] == 10_000   # first sample: the router's own rate
    assert rows["aa:aa:aa:aa:aa:02"]["online"] is False


async def test_devices_follow_the_childs_block(hass, unifi):
    await add_router(hass)
    entry = await add_child(hass)
    await hass.services.async_call(DOMAIN, "block", {"config_entry_id": entry.entry_id}, blocking=True)
    st = await check(hass)
    assert all(r["blocked"] for r in st.attributes["devices"] if r["in_group"])


async def pick(hass, entry, pattern, macs):
    """Options → Add devices → search → tick these MACs (wherever they are listed). Returns the result: the entry is
    saved straight away, or the Device blocking step when the router can't read its rules."""
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] == "menu"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "add_devices"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"pattern": pattern})
    assert r["step_id"] == "pick", r
    ticks = {}
    for key in r["data_schema"].schema:
        values = [o["value"] for o in r["data_schema"].schema[key].config["options"]]
        ticks[str(key)] = [m for m in macs if m in values]
    return await hass.config_entries.options.async_configure(r["flow_id"], ticks)


async def test_search_pick_and_block_a_device_outside_the_group(hass, unifi):
    await add_router(hass)
    unifi_switches(hass)
    entry = await add_child(hass)
    r = await pick(hass, entry, "speaker", ["cc:cc:cc:cc:cc:01"])
    assert r["type"] == "create_entry"                   # its own switch was found: saved with it, nothing to choose
    await hass.async_block_till_done()   # options change reloads the entry
    assert entry.options["devices"]["cc:cc:cc:cc:cc:01"] == {
        "name": "Den speaker", "block_entity": "switch.unifi_speaker_block", "confirmed": True}
    hass.states.async_set("switch.unifi_speaker_block", "on")    # blocked on the router
    st = await check(hass)
    speaker = next(r for r in st.attributes["devices"] if r["mac"] == "cc:cc:cc:cc:cc:01")
    assert speaker["blocked"] and not speaker["in_group"] and speaker["control"] == "own"
    assert hass.states.get("input_boolean.sam_block").state == "off"   # the child is still online
    assert hass.states.get("binary_sensor.den_speaker_blocked").state == "on"


async def test_a_group_member_follows_the_child(hass, unifi):
    await add_router(hass)
    unifi_switches(hass)
    entry = await add_child(hass)
    r = await pick(hass, entry, "*ipad*", ["aa:aa:aa:aa:aa:01"])
    assert r["type"] == "create_entry"
    await hass.async_block_till_done()
    st = await check(hass)
    ipad = next(r for r in st.attributes["devices"] if r["mac"] == "aa:aa:aa:aa:aa:01")
    assert ipad["in_group"] and ipad["block_entity"] is None and ipad["control"] == "group"


async def test_without_a_router_the_devices_list_says_so(hass):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}}})
    entry = MockConfigEntry(domain=DOMAIN, title="Sam", unique_id="sam",
                            data={"kind": "child", "child_name": "Sam", "block_entity": "input_boolean.sam_block"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    st = await check(hass)
    assert "No router connected" in st.attributes["error"]
    assert st.state == "unknown"


async def test_live_turns_on_and_off(hass, unifi):
    await add_router(hass)
    await add_child(hass)
    sw = "switch.sam_parental_controls_live_devices"
    await hass.services.async_call("switch", "turn_on", {"entity_id": sw}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sw).state == "on"
    assert hass.states.get("sensor.sam_parental_controls_devices").state == "1"
    await hass.services.async_call("switch", "turn_off", {"entity_id": sw}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sw).state == "off"


async def test_device_list_is_not_recorded(hass, unifi):
    await add_router(hass)
    await add_child(hass)
    from custom_components.parental_controls.sensor import DevicesSensor
    assert "devices" in DevicesSensor._unrecorded_attributes


async def test_a_console_with_several_sites_asks_which(hass, aioclient_mock):
    aioclient_mock.post(f"{U}/api/auth/login", json={}, headers={"X-CSRF-Token": "t"})
    aioclient_mock.get(f"{NET}/api/self/sites", json={"data": [{"name": "default", "desc": "Home"}, {"name": "x1", "desc": "Cottage"}]})
    aioclient_mock.get(f"{U}/proxy/network/v2/api/site/x1/network-members-groups", json=GROUPS)
    aioclient_mock.get(f"{U}/proxy/network/api/s/x1/rest/user", json={"data": USERS})
    aioclient_mock.get(f"{U}/proxy/network/api/s/x1/stat/device", json={"data": DEVICES})
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "router"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"vendor": "unifi"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"host": HOST, "username": "ro", "password": "pw"})
    assert r["step_id"] == "site"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"site": "x1"})
    assert r["type"] == "create_entry" and r["result"].data["site"] == "x1"


async def test_missing_device_block_switch_raises_a_repair(hass, unifi, freezer):
    from datetime import timedelta
    from homeassistant.helpers import issue_registry as ir
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    await add_router(hass)
    entry = await add_child(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "devices": {
        "cc:cc:cc:cc:cc:01": {"name": "Den speaker", "block_entity": "switch.gone", "confirmed": True}}})
    await hass.async_block_till_done()
    for _ in range(12):
        freezer.tick(timedelta(seconds=30)); async_fire_time_changed(hass); await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_device_cccccccccc01")
    assert issue is not None and issue.translation_placeholders["device"] == "Den speaker"
