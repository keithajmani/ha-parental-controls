"""Runs the integration inside a real Home Assistant test instance, with an input_boolean standing in for the
router's block switch. Needs: pip install -r requirements_test.txt (Python 3.13)."""
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "parental_controls"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


SW = "input_boolean.sam_block"
SENSOR = "sensor.sam_parental_controls_internet"


async def setup_child(hass: HomeAssistant, name="Sam", switch=SW) -> MockConfigEntry:
    obj = switch.split(".")[1]
    if not hass.states.get(switch):
        assert await async_setup_component(hass, "input_boolean", {"input_boolean": {obj: {"name": obj}}})
    entry = MockConfigEntry(domain=DOMAIN, title=name, unique_id=name.lower(),
                            data={"child_name": name, "block_entity": switch})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def start_child_flow(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "menu"
    return await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "child"})


async def call(hass, service, entry, **data):
    await hass.services.async_call(DOMAIN, service, {"config_entry_id": entry.entry_id, **data}, blocking=True)
    await hass.async_block_till_done()


async def test_entities_are_named_after_the_child(hass):
    await setup_child(hass)
    for eid in (SENSOR, "button.sam_parental_controls_block", "button.sam_parental_controls_allow",
                "number.sam_parental_controls_pause_length", "switch.sam_parental_controls_bedtime"):
        assert hass.states.get(eid) is not None, eid
    assert hass.states.get(SENSOR).state == "online"


async def test_block_and_allow_drive_the_switch(hass):
    entry = await setup_child(hass)
    await call(hass, "block", entry)
    assert hass.states.get(SW).state == "on"
    assert hass.states.get(SENSOR).state == "blocked"
    await call(hass, "allow", entry)
    assert hass.states.get(SW).state == "off"
    assert hass.states.get(SENSOR).state == "online"


async def test_allow_for_while_blocked_then_reblocks(hass, freezer):
    entry = await setup_child(hass)
    await call(hass, "block", entry)
    await call(hass, "pause", entry, minutes=1)
    assert hass.states.get(SW).state == "off"
    st = hass.states.get(SENSOR)
    assert st.state == "allowed_for" and st.attributes["then"] == "blocked"
    freezer.tick(timedelta(seconds=61)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SW).state == "on"
    assert hass.states.get(SENSOR).state == "blocked"


async def test_pause_when_online_then_back_on(hass, freezer):
    entry = await setup_child(hass)
    await call(hass, "pause", entry, minutes=15)
    assert hass.states.get(SW).state == "on"
    assert hass.states.get(SENSOR).state == "paused"
    freezer.tick(timedelta(minutes=15, seconds=1)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SW).state == "off"


async def test_switch_changed_elsewhere_counts_as_allow(hass):
    entry = await setup_child(hass)
    await call(hass, "pause", entry, minutes=30)
    await hass.services.async_call("input_boolean", "turn_off", {"entity_id": SW}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "online"   # the pause was cancelled, not re-applied


async def test_state_survives_a_reload(hass):
    entry = await setup_child(hass)
    await call(hass, "block", entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "blocked"


async def test_pause_button_uses_the_pause_length(hass):
    await setup_child(hass)
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": "number.sam_parental_controls_pause_length", "value": 20}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.sam_parental_controls_pause"}, blocking=True)
    await hass.async_block_till_done()
    st = hass.states.get(SENSOR)
    assert st.state == "paused" and st.attributes["minutes_left"] == 20


async def test_two_children_are_independent(hass):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}, "riley_block": {}}})
    a = await setup_child(hass)
    f = await setup_child(hass, "Riley", "input_boolean.riley_block")
    await call(hass, "block", a)
    assert hass.states.get("sensor.riley_parental_controls_internet").state == "online"
    assert hass.states.get("input_boolean.riley_block").state == "off"


async def test_config_flow_creates_a_child_and_rejects_duplicates(hass):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"x": {}, "y": {}}})
    r = await start_child_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"child_name": "Jordan", "block_entity": "input_boolean.x"})
    assert r["type"] == "create_entry" and r["title"] == "Jordan"
    r = await start_child_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"child_name": "Jordan", "block_entity": "input_boolean.y"})
    assert r["type"] == "abort" and r["reason"] == "already_configured"
    r = await start_child_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"child_name": "Zoe", "block_entity": "input_boolean.x"})
    assert r["type"] == "form" and r["errors"] == {"block_entity": "switch_in_use"}


async def test_bedtime_blocks_at_its_start_and_allow_lasts_the_night(hass, freezer):
    from homeassistant.util import dt as dt_util
    freezer.move_to(dt_util.now().replace(hour=20, minute=58, second=0, microsecond=0))
    await setup_child(hass)
    for key in ("weeknight_start", "weekend_start"):
        await hass.services.async_call("time", "set_value", {"entity_id": f"time.sam_parental_controls_bedtime_start_{'sun_thu' if key == 'weeknight_start' else 'fri_sat'}",
                                                             "time": "21:00:00"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.sam_parental_controls_bedtime"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "online"
    freezer.tick(timedelta(minutes=2, seconds=31)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "bedtime"
    assert hass.states.get(SW).state == "on"
    await hass.services.async_call("button", "press", {"entity_id": "button.sam_parental_controls_allow"}, blocking=True)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "online"
    assert hass.states.get(SENSOR).attributes["allowed_tonight"] is True


async def test_new_child_adopts_a_blocked_switch(hass):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {"initial": True}}})
    assert hass.states.get(SW).state == "on"
    await setup_child(hass)
    assert hass.states.get(SW).state == "on"           # not unblocked by adding the child
    assert hass.states.get(SENSOR).state == "blocked"


async def test_card_is_served(hass, hass_client):
    await setup_child(hass)
    client = await hass_client()
    r = await client.get("/parental_controls/parental-controls-card.js")
    assert r.status == 200
    assert "customElements.define(\"parental-controls-card\"" in await r.text()



async def test_card_is_added_as_a_dashboard_resource_once(hass):
    assert await async_setup_component(hass, "lovelace", {})
    await setup_child(hass)
    res = hass.data["lovelace"].resources
    urls = [i["url"] for i in res.async_items()]
    assert any(u.startswith("/parental_controls/parental-controls-card.js?v=") for u in urls)
    # reloading the integration must not add it twice
    await hass.config_entries.async_reload(hass.config_entries.async_entries("parental_controls")[0].entry_id)
    await hass.async_block_till_done()
    assert sum(u.startswith("/parental_controls/") for u in [i["url"] for i in res.async_items()]) == 1


def test_brand_icons_ship_inside_the_integration():
    """HA 2026.x serves a custom integration's icon from <integration>/brand/ (no brands-repo PR needed)."""
    from pathlib import Path
    import struct
    import zlib
    brand = Path(__file__).parent.parent / "custom_components" / "parental_controls" / "brand"
    for name, size in (("icon.png", 256), ("icon@2x.png", 512), ("dark_icon.png", 256), ("dark_icon@2x.png", 512)):
        data = (brand / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == (size, size), name
        assert data[24:26] == bytes([8, 6]), name            # 8-bit RGBA
        # transparent background: the top-left pixel (row 0 needs no unfiltering for its first pixel) has alpha 0
        idat, i = b"", 8
        while i < len(data):
            n, kind = struct.unpack(">I4s", data[i:i + 8])
            if kind == b"IDAT":
                idat += data[i + 8:i + 8 + n]
            i += 12 + n
        assert zlib.decompress(idat)[1 + 3] == 0, name
    # one drawing, two pause-ring colours: shield purple for light backgrounds, white for dark ones
    light, dark = (brand / "icon.svg").read_text(), (brand / "dark_icon.svg").read_text()
    assert 'stroke="#9FA8DA" stroke-width="8"' in light and 'stroke="#FFFFFF" stroke-width="8"' in dark


def test_card_file_is_ascii_and_defines_both_cards():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "custom_components/parental_controls/frontend/parental-controls-card.js").read_text()
    assert js.isascii()                       # reads the same whatever charset it is served with
    assert 'define("parental-controls-card"' in js and 'define("parental-controls-settings-card"' in js


async def test_missing_block_switch_raises_a_repair_and_clears_it(hass, freezer):
    from homeassistant.helpers import issue_registry as ir
    entry = MockConfigEntry(domain=DOMAIN, title="Sam", unique_id="sam",
                            data={"kind": "child", "child_name": "Sam", "block_entity": "input_boolean.sam_block"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)       # switch doesn't exist yet
    await hass.async_block_till_done()
    issue_id = f"{entry.entry_id}_block_switch"
    freezer.tick(timedelta(minutes=1)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None    # still within the grace period
    for _ in range(11):
        freezer.tick(timedelta(seconds=30)); async_fire_time_changed(hass); await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders["reason"] == "missing"
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}}})
    freezer.tick(timedelta(seconds=31)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None    # cleared once the switch is back


async def test_a_switch_that_appears_after_a_restart_is_not_taken_as_allow(hass, freezer):
    """Restart order: the child is blocked, the router integration loads after us, so the switch is missing at
    setup and then appears as off. The child must stay blocked (switch turned back on), not be allowed."""
    from homeassistant.helpers.storage import Store
    entry = MockConfigEntry(domain=DOMAIN, title="Sam", unique_id="sam",
                            data={"kind": "child", "child_name": "Sam", "block_entity": SW})
    entry.add_to_hass(hass)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save(
        {"kid": {"name": "Sam", "manual_blocked": True}, "pause_minutes": 15})
    assert await hass.config_entries.async_setup(entry.entry_id)     # switch doesn't exist yet
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "blocked"
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sam_block": {}}})   # appears, off
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "blocked"
    assert hass.states.get(SW).state == "on"


async def test_a_switch_back_from_unavailable_gets_the_childs_status(hass, freezer):
    entry = await setup_child(hass)
    await call(hass, "block", entry)
    hass.states.async_set(SW, "unavailable"); await hass.async_block_till_done()
    hass.states.async_set(SW, "off"); await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3)); async_fire_time_changed(hass); await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "blocked"
    assert hass.states.get(SW).state == "on"
