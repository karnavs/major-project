import json
import os
import tempfile
import unittest
from collections import namedtuple

from congestion_detection import (CongestionService, DetectorConfig, DetectorManager, Event,
                                  PortStatsAdapter, build_service)

St = namedtuple("St", "port_no tx_bytes rx_bytes")
CAP = 10_000_000  # 10 Mbit/s
BYTES_PER_S_AT_50PCT = 625_000


class TestAdapter(unittest.TestCase):
    def setUp(self):
        self.a = PortStatsAdapter({(1, 2): CAP}, max_interval_s=10)

    def test_first_sample_invalid(self):
        s = self.a.process(1, 2, 0, 0, 0.0)
        self.assertFalse(s.valid); self.assertEqual(s.reason, "FIRST_SAMPLE")

    def test_utilization_math(self):
        self.a.process(1, 2, 0, 0, 0.0)
        s = self.a.process(1, 2, BYTES_PER_S_AT_50PCT * 2, 0, 2.0)   # 625 kB/s for 2 s
        self.assertTrue(s.valid); self.assertAlmostEqual(s.value, 0.5)
        self.assertAlmostEqual(s.meta["rate_bps"], 5_000_000)

    def test_rx_direction(self):
        a = PortStatsAdapter({(1, 2): CAP}, direction="rx")
        a.process(1, 2, 0, 0, 0.0)
        self.assertAlmostEqual(a.process(1, 2, 999, BYTES_PER_S_AT_50PCT, 1.0).value, 0.5)

    def test_16_counter_reset_then_recovers(self):
        self.a.process(1, 2, 1000, 0, 0.0)
        s = self.a.process(1, 2, 10, 0, 1.0)
        self.assertEqual(s.reason, "COUNTER_RESET")
        s2 = self.a.process(1, 2, 10 + BYTES_PER_S_AT_50PCT, 0, 2.0)  # re-baselined at reset sample
        self.assertTrue(s2.valid); self.assertAlmostEqual(s2.value, 0.5)

    def test_zero_and_negative_interval(self):
        self.a.process(1, 2, 0, 0, 5.0)
        self.assertEqual(self.a.process(1, 2, 10, 0, 5.0).reason, "NON_POSITIVE_INTERVAL")
        self.assertEqual(self.a.process(1, 2, 10, 0, 4.0).reason, "NON_POSITIVE_INTERVAL")

    def test_17_stale_interval(self):
        self.a.process(1, 2, 0, 0, 0.0)
        self.assertEqual(self.a.process(1, 2, 10**9, 0, 60.0).reason, "STALE_INTERVAL")
        self.assertTrue(self.a.process(1, 2, 10**9 + BYTES_PER_S_AT_50PCT, 0, 61.0).valid)

    def test_unknown_capacity_not_guessed(self):
        self.a.process(1, 9, 0, 0, 0.0)
        s = self.a.process(1, 9, 10**6, 0, 1.0)
        self.assertFalse(s.valid); self.assertEqual(s.reason, "UNKNOWN_CAPACITY")

    def test_forget_switch(self):
        self.a.process(1, 2, 0, 0, 0.0)
        self.a.forget_switch(1)
        self.assertEqual(self.a.process(1, 2, 5, 0, 1.0).reason, "FIRST_SAMPLE")

    def test_bad_args(self):
        with self.assertRaises(ValueError): PortStatsAdapter({(1, 2): 0})
        with self.assertRaises(ValueError): PortStatsAdapter(direction="both")
        with self.assertRaises(ValueError): PortStatsAdapter(max_interval_s=0)


class Replay:
    """Simulates cumulative port counters from per-second utilization profiles (SYNTHETIC)."""
    def __init__(self, svc, ports):
        self.svc, self.cum, self.t = svc, {p: 0 for p in ports}, 0.0

    def step(self, utils, dpid=1, dt=1.0):
        self.t += dt
        body = []
        for p, u in utils.items():
            self.cum[p] += int(u * CAP / 8 * dt)
            body.append(St(p, self.cum[p], 0))
        return self.svc.ingest_port_stats(dpid, body, self.t)


class TestService(unittest.TestCase):
    def make(self, **kw):
        self.events = []
        cfg = {"detector": {}, "adapter": {"capacity_bps": {"1:1": CAP, "1:2": CAP}}, **kw}
        return build_service(cfg, on_event=self.events.append)

    def test_per_port_isolation_and_event_once(self):
        svc = self.make(); r = Replay(svc, [1, 2])
        for _ in range(15): r.step({1: 0.1, 2: 0.1})
        for _ in range(30): r.step({1: 0.95, 2: 0.1})
        self.assertEqual([(e.entity, e.event) for e in self.events], [((1, 1), Event.CONGESTION_CONFIRMED)])
        for _ in range(10): r.step({1: 0.1, 2: 0.1})
        self.assertEqual([e.event for e in self.events], [Event.CONGESTION_CONFIRMED, Event.RECOVERY_CONFIRMED])
        self.assertTrue(all(e.entity == (1, 1) for e in self.events))

    def test_reserved_and_unmonitored_ports_skipped(self):
        svc = self.make(monitored_ports={"1": [1]})
        out = svc.ingest_port_stats(1, [St(1, 0, 0), St(2, 0, 0), St(0xfffffffe, 0, 0)], 1.0)
        self.assertEqual([d.entity for d in out], [(1, 1)])

    def test_consumer_exception_does_not_break_pipeline(self):
        def boom(_): raise RuntimeError("consumer bug")
        svc = build_service({"adapter": {"capacity_bps": {"1:1": CAP}}}, on_event=boom)
        r = Replay(svc, [1])
        for _ in range(12): r.step({1: 0.1})
        for _ in range(5): r.step({1: 0.95})      # raises inside callback; must be swallowed
        self.assertEqual(len(svc.manager.states()), 1)

    def test_delayed_poll_and_missing_reply_safe(self):
        svc = self.make(); r = Replay(svc, [1])
        for _ in range(12): r.step({1: 0.1})
        d = r.step({1: 0.95}, dt=45.0)            # one reply 45 s late -> stale, not evidence
        self.assertEqual(d[0].reason, "STALE_INTERVAL")
        self.assertEqual(svc.ingest_port_stats(1, [], r.t + 1), [])   # empty reply: no crash

    def test_switch_disconnect_resets_state(self):
        svc = self.make(); r = Replay(svc, [1])
        for _ in range(12): r.step({1: 0.1})
        svc.on_switch_disconnect(1)
        self.assertEqual(svc.manager.states(), {})
        self.assertEqual(svc.ingest_port_stats(1, [St(1, 5, 0)], 99.0)[0].reason, "FIRST_SAMPLE")

    def test_decision_log_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "d.jsonl")
            svc = self.make(decision_log_path=p); r = Replay(svc, [1])
            for _ in range(12): r.step({1: 0.1})
            for _ in range(3): r.step({1: 0.95})
            with open(p) as fh:
                recs = [json.loads(l) for l in fh]
            self.assertTrue(any(x["event"] == "CONGESTION_CONFIRMED" for x in recs))
            self.assertTrue(any(x["reason"] == "FIRST_SAMPLE" for x in recs))
            ev = [x for x in recs if x["event"]][0]
            for k in ("ts", "entity", "value", "baseline", "t_enter", "t_exit", "state", "reason", "meta"):
                self.assertIn(k, ev)
            self.assertLess(len(recs), 12 + 3)    # routine samples are NOT all logged

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            build_service({"detector": {"hysteresis_margin": 0}})


if __name__ == "__main__":
    unittest.main()
