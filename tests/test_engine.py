"""Rules engine tests. Each case is a behaviour of the HA setup built Oct 18-21, 2026 that the integration must keep.
Run: python3 -m unittest discover -s tests -v   (stdlib only; also runs under pytest)"""
import os
import sys
import unittest
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "parental_controls"))
from engine import Bedtime, Device, Kid, State, device_blocked  # noqa: E402

WED = datetime(2026, 10, 21)   # a Wednesday
FRI = datetime(2026, 10, 23)


def at(day, hh, mm=0):
    return day.replace(hour=hh, minute=mm)


def bedtime_kid():
    return Kid("riley", bedtime=Bedtime(enabled=True, weeknight_start=time(21, 15), weekend_start=time(22, 30), end=time(2, 0)))


class Pause(unittest.TestCase):
    def test_pause_when_online_blocks_then_comes_back(self):
        k = Kid("sam"); t = at(WED, 16)
        k.pause(t, 15)
        s = k.status(t)
        self.assertEqual((s.state, s.router_blocked, s.then), (State.PAUSED, True, State.ONLINE))
        k.tick(t + timedelta(minutes=15))
        self.assertEqual(k.status(t + timedelta(minutes=15)).state, State.ONLINE)

    def test_pause_again_restarts_the_pause(self):
        k = Kid("sam"); t = at(WED, 16)
        k.pause(t, 15); k.pause(t + timedelta(minutes=5), 30)
        s = k.status(t + timedelta(minutes=5))
        self.assertEqual(s.state, State.PAUSED)
        self.assertEqual(s.ends_at, t + timedelta(minutes=35))

    def test_block_and_allow_cancel_a_pause(self):
        k = Kid("sam"); t = at(WED, 16)
        k.pause(t, 15); k.block(t + timedelta(minutes=1))
        self.assertEqual(k.status(t + timedelta(minutes=20)).state, State.BLOCKED)   # the pause can't unblock later
        k.pause(t, 15); k.allow(t + timedelta(minutes=1))
        self.assertEqual(k.status(t + timedelta(minutes=2)).state, State.ONLINE)

    def test_zero_minutes_rejected(self):
        with self.assertRaises(ValueError):
            Kid("sam").pause(at(WED, 16), 0)


class AllowForWhileBlocked(unittest.TestCase):
    """A live test of the first build: block, allow for 1 minute, re-blocked."""

    def test_allow_for_then_reblocked(self):
        k = Kid("sam"); t = at(WED, 0, 56)
        k.block(t)
        self.assertEqual(k.status(t).state, State.BLOCKED)
        k.pause(t, 1)
        s = k.status(t)
        self.assertEqual((s.state, s.router_blocked, s.then), (State.ALLOWED_FOR, False, State.BLOCKED))
        k.tick(t + timedelta(minutes=1))
        self.assertEqual(k.status(t + timedelta(minutes=1)).state, State.BLOCKED)

    def test_pause_during_allow_for_restarts_it(self):
        k = Kid("sam"); t = at(WED, 10)
        k.block(t); k.pause(t, 15); k.pause(t + timedelta(minutes=5), 60)
        s = k.status(t + timedelta(minutes=5))
        self.assertEqual((s.state, s.ends_at), (State.ALLOWED_FOR, t + timedelta(minutes=65)))

    def test_allow_during_allow_for_ends_the_block(self):
        k = Kid("sam"); t = at(WED, 10)
        k.block(t); k.pause(t, 15); k.allow(t + timedelta(minutes=2))
        self.assertEqual(k.status(t + timedelta(minutes=30)).state, State.ONLINE)


class BedtimeRules(unittest.TestCase):
    def test_weeknight_window_crosses_midnight(self):
        k = bedtime_kid()
        for t, want in [(at(WED, 21, 14), State.ONLINE), (at(WED, 21, 15), State.BEDTIME),
                        (at(WED + timedelta(days=1), 1, 59), State.BEDTIME), (at(WED + timedelta(days=1), 2), State.ONLINE)]:
            k.tick(t)
            self.assertEqual(k.status(t).state, want, t)

    def test_friday_and_saturday_use_the_weekend_start(self):
        k = bedtime_kid()
        self.assertEqual(k.status(at(FRI, 22)).state, State.ONLINE)
        self.assertEqual(k.status(at(FRI, 22, 30)).state, State.BEDTIME)
        sun = FRI + timedelta(days=2)
        self.assertEqual(k.status(at(sun, 21, 20)).state, State.BEDTIME)   # Sunday is a school night

    def test_disabled_bedtime_never_blocks(self):
        k = bedtime_kid(); k.bedtime.enabled = False
        self.assertEqual(k.status(at(WED, 23)).state, State.ONLINE)

    def test_pause_during_bedtime_is_allow_for_then_bedtime_again(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.pause(t, 30)
        s = k.status(t)
        self.assertEqual((s.state, s.router_blocked, s.then), (State.ALLOWED_FOR, False, State.BEDTIME))
        k.tick(t + timedelta(minutes=30))
        self.assertEqual(k.status(t + timedelta(minutes=30)).state, State.BEDTIME)

    def test_allow_during_bedtime_lasts_the_night_only(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.allow(t)
        for m in range(0, 240, 5):    # the 5-minute checks must not re-block
            k.tick(t + timedelta(minutes=m))
            self.assertEqual(k.status(t + timedelta(minutes=m)).state, State.ONLINE)
        nxt = at(WED + timedelta(days=1), 21, 15)
        k.tick(nxt)
        self.assertEqual(k.status(nxt).state, State.BEDTIME)

    def test_pause_when_allowed_tonight_is_a_normal_pause(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.allow(t); k.pause(t + timedelta(minutes=10), 15)
        s = k.status(t + timedelta(minutes=10))
        self.assertEqual((s.state, s.then), (State.PAUSED, State.ONLINE))

    def test_manual_block_survives_the_end_of_bedtime(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.block(t)
        two_am = at(WED + timedelta(days=1), 2, 1)
        k.tick(two_am)
        self.assertEqual(k.status(two_am).state, State.BLOCKED)

    def test_bedtime_starting_during_a_manual_allow_for_ends_blocked(self):
        k = bedtime_kid(); t = at(WED, 21)
        k.block(t); k.pause(t, 60)               # allow-for until 10 PM
        start = at(WED, 21, 15); k.tick(start)   # bedtime starts: allow-for cancelled
        self.assertEqual(k.status(start).state, State.BEDTIME)
        two_am = at(WED + timedelta(days=1), 2, 1); k.tick(two_am)
        self.assertEqual(k.status(two_am).state, State.BLOCKED)   # the manual block is still there

    def test_bedtime_starting_during_a_pause_ends_online_after_bedtime(self):
        k = bedtime_kid(); t = at(WED, 21)
        k.pause(t, 60)
        k.tick(at(WED, 21, 15))
        self.assertIsNone(k.override)
        two_am = at(WED + timedelta(days=1), 2, 1); k.tick(two_am)
        self.assertEqual(k.status(two_am).state, State.ONLINE)


class Restarts(unittest.TestCase):
    def test_override_that_ended_while_down_is_cleared_on_start(self):
        k = Kid("sam"); t = at(WED, 10)
        k.block(t); k.pause(t, 15)
        saved = k.to_dict()
        k2 = Kid.from_dict(saved)
        later = t + timedelta(hours=1)
        k2.tick(later)
        self.assertIsNone(k2.override)
        self.assertEqual(k2.status(later).state, State.BLOCKED)

    def test_round_trip_keeps_everything(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.pause(t, 30)
        k2 = Kid.from_dict(k.to_dict())
        self.assertEqual(k2.status(t), k.status(t))


class RestartDuringBedtime(unittest.TestCase):
    def test_allowed_tonight_survives_a_restart(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.allow(t)
        k2 = Kid.from_dict(k.to_dict()); later = t + timedelta(minutes=10)
        k2.tick(later)
        self.assertTrue(k2.allowed_tonight)
        self.assertEqual(k2.status(later).state, State.ONLINE)

    def test_bedtime_allow_for_survives_a_restart(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.pause(t, 30)
        k2 = Kid.from_dict(k.to_dict()); later = t + timedelta(minutes=5)
        k2.tick(later)
        self.assertEqual(k2.status(later).state, State.ALLOWED_FOR)

    def test_bedtime_that_started_while_down_still_starts(self):
        k = bedtime_kid(); t = at(WED, 20)
        k.tick(t); k.pause(t, 120)                   # a pause running past bedtime start
        k2 = Kid.from_dict(k.to_dict()); later = at(WED, 21, 30)
        k2.tick(later)
        self.assertIsNone(k2.override)
        self.assertEqual(k2.status(later).state, State.BEDTIME)


class ExternalChanges(unittest.TestCase):
    def test_unblocked_in_the_router_app_counts_as_allow(self):
        k = bedtime_kid(); t = at(WED, 22)
        k.tick(t); k.external_change(t, router_blocked=False)
        self.assertTrue(k.allowed_tonight)
        self.assertEqual(k.status(t + timedelta(minutes=30)).state, State.ONLINE)

    def test_unblock_cancels_a_running_pause(self):
        k = Kid("sam"); t = at(WED, 16)
        k.pause(t, 30); k.external_change(t + timedelta(minutes=1), router_blocked=False)
        self.assertIsNone(k.override)

    def test_blocked_in_the_router_app_counts_as_block(self):
        k = Kid("sam"); t = at(WED, 16)
        k.external_change(t, router_blocked=True)
        self.assertEqual(k.status(t).state, State.BLOCKED)

    def test_our_own_change_is_not_external(self):
        k = Kid("sam"); t = at(WED, 16)
        k.block(t); k.pause(t, 15)     # allow-for: router unblocked by us
        k.external_change(t, router_blocked=False)
        self.assertEqual(k.status(t).state, State.ALLOWED_FOR)


class Devices(unittest.TestCase):
    def setUp(self):
        self.online = Kid("riley").status(at(WED, 16))
        b = Kid("riley"); b.block(at(WED, 16)); self.blocked = b.status(at(WED, 16))

    def test_group_member_follows_the_kid(self):
        mac = Device("aa", "MacBook", "riley", in_group=True)
        self.assertFalse(device_blocked(mac, self.online))
        self.assertTrue(device_blocked(mac, self.blocked))

    def test_group_member_can_be_blocked_on_its_own(self):
        mac = Device("aa", "MacBook", "riley", in_group=True, controllable=True, blocked=True)
        self.assertTrue(device_blocked(mac, self.online))

    def test_group_member_cannot_be_allowed_through_the_kid_block(self):
        mac = Device("aa", "MacBook", "riley", in_group=True, controllable=True, blocked=False)
        self.assertTrue(device_blocked(mac, self.blocked))

    def test_extra_device_ignores_the_kid_block(self):
        echo = Device("bb", "Echo Show", "riley", in_group=False, controllable=True, blocked=False)
        self.assertFalse(device_blocked(echo, self.blocked))
        echo.blocked = True
        self.assertTrue(device_blocked(echo, self.online))


class ManyKids(unittest.TestCase):
    def test_kids_are_independent(self):
        kids = {n: Kid(n) for n in ("sam", "riley", "jordan")}
        t = at(WED, 16)
        kids["sam"].block(t); kids["riley"].pause(t, 15)
        self.assertEqual([kids[n].status(t).state for n in ("sam", "riley", "jordan")],
                         [State.BLOCKED, State.PAUSED, State.ONLINE])


if __name__ == "__main__":
    unittest.main()
