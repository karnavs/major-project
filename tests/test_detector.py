import math
import unittest

from congestion_detection import (CongestionDetector, DetectorConfig, DetectorManager, Event,
                                  Sample, State)
from tests.helpers import ENT, events, feed, warmed

CONG, REC = Event.CONGESTION_CONFIRMED, Event.RECOVERY_CONFIRMED


def congest(d, t0):
    """Drive a warmed detector to CONGESTED; returns next timestamp."""
    feed(d, [0.95] * 3, t0=t0)
    assert d.state is State.CONGESTED
    return t0 + 3


class TestConfig(unittest.TestCase):
    def test_01_valid_default_and_custom(self):
        DetectorConfig()
        DetectorConfig(alpha=1.0, k=0, enter_persistence=1, exit_persistence=1)

    def test_02_invalid_configs_rejected(self):
        bad = [dict(alpha=0), dict(alpha=1.5), dict(k=-1), dict(min_variation=0), dict(warmup_samples=0),
               dict(threshold_min=0.9, threshold_max=0.5), dict(threshold_max=5.0),
               dict(hysteresis_margin=0), dict(hysteresis_margin=0.5), dict(enter_persistence=0),
               dict(exit_persistence=0), dict(max_invalid_streak=0)]
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                DetectorConfig(**kw)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            DetectorConfig.from_dict({"alphaa": 0.2})


class TestBaselineAndThreshold(unittest.TestCase):
    def test_03_baseline_initialised_after_warmup(self):
        d = CongestionDetector(ENT)
        feed(d, [0.1] * 9)
        self.assertFalse(d.warmup_complete)
        self.assertEqual(d.thresholds()[0], 0.85)          # fixed ceiling during warm-up
        feed(d, [0.1], t0=9)
        self.assertTrue(d.warmup_complete)
        self.assertAlmostEqual(d.baseline, 0.1)
        self.assertAlmostEqual(d.variation, 0.02)            # floored by min_variation

    def test_04_baseline_ewma_update(self):
        d, t = warmed()
        feed(d, [0.2], t0=t)
        self.assertAlmostEqual(d.baseline, 0.1 * 0.2 + 0.9 * 0.1)

    def test_05_threshold_formula_and_clamps(self):
        d = CongestionDetector(ENT)
        feed(d, [0.55, 0.45] * 5)                              # baseline .5, mean abs dev .05
        self.assertAlmostEqual(d.baseline, 0.5)
        self.assertAlmostEqual(d.thresholds()[0], 0.5 + 3 * 0.05)
        self.assertAlmostEqual(d.thresholds()[1], 0.65 - 0.10)
        lo, _ = warmed(level=0.1)
        self.assertEqual(lo.thresholds()[0], 0.40)             # lower clamp
        hi, _ = warmed(level=0.8)
        self.assertEqual(hi.thresholds()[0], 0.85)             # upper clamp

    def test_baseline_frozen_while_not_normal(self):
        d, t = warmed()
        b0 = d.baseline
        feed(d, [0.95] * 50, t0=t)
        self.assertEqual(d.baseline, b0)                        # congestion can't raise the threshold
        self.assertEqual(d.thresholds()[0], 0.40)


class TestPersistence(unittest.TestCase):
    def test_06_isolated_spike_rejected(self):
        d, t = warmed()
        r = feed(d, [0.95, 0.95, 0.1], t0=t)
        self.assertEqual(events(r), [])
        self.assertIs(d.state, State.NORMAL)
        self.assertEqual(r[-1].reason, "SPIKE_REJECTED")

    def test_07_sustained_triggers_exactly_at_n(self):
        d, t = warmed()
        r = feed(d, [0.95] * 3, t0=t)
        self.assertEqual([x.event for x in r], [None, None, CONG])
        self.assertEqual([x.state for x in r], [State.CONGESTION_PENDING, State.CONGESTION_PENDING, State.CONGESTED])

    def test_08_repeated_boundary_crossing_no_event(self):
        d, t = warmed()
        r = feed(d, [0.95, 0.1] * 20, t0=t)
        self.assertEqual(events(r), [])
        self.assertIs(d.state, State.NORMAL)

    def test_09_values_near_threshold(self):
        d, t = warmed()
        self.assertEqual(d.thresholds()[0], 0.40)
        feed(d, [0.3999] * 10, t0=t)
        self.assertIs(d.state, State.NORMAL)                    # just below: no crossing
        d2, t2 = warmed()
        feed(d2, [0.40], t0=t2)
        self.assertIs(d2.state, State.CONGESTION_PENDING)       # exactly at: crossing (>=)

    def test_20_events_not_duplicated(self):
        d, t = warmed()
        r = feed(d, [0.95] * 40, t0=t)
        self.assertEqual(events(r), [CONG])
        self.assertEqual(sum(1 for x in r if x.state_changed), 2)   # NORMAL->PENDING->CONGESTED only

    def test_startup_already_congested(self):
        d = CongestionDetector(ENT)
        r = feed(d, [0.95] * 3)
        self.assertEqual(events(r), [CONG])                      # fixed ceiling used before baseline exists
        self.assertFalse(d.warmup_complete)                      # congested samples never poison warm-up
        self.assertIsNone(d.baseline)

    def test_enter_persistence_one(self):
        d, t = warmed(DetectorConfig(enter_persistence=1))
        r = feed(d, [0.95], t0=t)
        self.assertEqual(events(r), [CONG])


class TestHysteresisAndRecovery(unittest.TestCase):
    def test_10_between_thresholds_holds_congested(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.35] * 30, t0=t)                           # T_exit=.30 <= .35 < T_enter=.40
        self.assertEqual(events(r), [])
        self.assertTrue(all(x.state is State.CONGESTED for x in r))
        self.assertEqual(r[0].reason, "IN_HYSTERESIS_BAND")

    def test_11_recovery_not_immediate(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.1] * 4, t0=t)
        self.assertEqual(events(r), [])
        self.assertIs(d.state, State.RECOVERY_PENDING)
        r2 = feed(d, [0.1], t0=t + 4)
        self.assertEqual(events(r2), [REC])
        self.assertIs(d.state, State.NORMAL)

    def test_12_spike_during_recovery_resets(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.1] * 3 + [0.95] + [0.1] * 4, t0=t)
        self.assertEqual(events(r), [])                          # 4 lows after reset < 5
        self.assertEqual(r[3].reason, "RECOVERY_INTERRUPTED")
        self.assertIs(d.state, State.RECOVERY_PENDING)
        r2 = feed(d, [0.1], t0=t + 8)
        self.assertEqual(events(r2), [REC])

    def test_band_value_during_recovery_interrupts(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.1, 0.1, 0.35], t0=t)
        self.assertIs(d.state, State.CONGESTED)
        self.assertEqual(r[-1].exit_count, 0)

    def test_13_sustained_recovery_reseeds_baseline(self):
        d, t = warmed()
        t = congest(d, t)
        feed(d, [0.2] * 5, t0=t)
        self.assertIs(d.state, State.NORMAL)
        self.assertAlmostEqual(d.baseline, 0.2)

    def test_recovery_event_once(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.1] * 30, t0=t)
        self.assertEqual(events(r), [REC])


class TestInvalidSamples(unittest.TestCase):
    def test_14_missing_sample_is_neutral(self):
        d, t = warmed()
        r = feed(d, [0.95, 0.95, None, 0.95], t0=t)
        self.assertEqual([x.event for x in r], [None, None, None, CONG])   # invalid didn't count, didn't reset
        self.assertFalse(r[2].valid)

    def test_14b_long_gap_resets_pending(self):
        d, t = warmed()
        r = feed(d, [0.95, 0.95] + [None] * 5 + [0.95], t0=t)
        self.assertEqual(events(r), [])
        self.assertIn("STALE_PENDING_RESET", r[6].reason)
        self.assertIs(d.state, State.CONGESTION_PENDING)          # restarted count at 1

    def test_15_invalid_values_rejected(self):
        d, t = warmed()
        for i, bad in enumerate([-0.1, float("nan"), float("inf"), 9.9, "x", True]):
            r = d.update(Sample(ENT, t + i, bad))
            with self.subTest(bad=bad):
                self.assertFalse(r.valid)
                self.assertIs(r.state, State.NORMAL)
        self.assertFalse(d.update(Sample(ENT, float("nan"), 0.1)).valid)

    def test_invalid_never_creates_recovery(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [0.1, 0.1] + [None] * 20, t0=t)
        self.assertEqual(events(r), [])
        self.assertIs(d.state, State.CONGESTED)                   # fail-safe fallback

    def test_invalid_in_congested_keeps_congested(self):
        d, t = warmed()
        t = congest(d, t)
        r = feed(d, [None] * 50, t0=t)
        self.assertIs(d.state, State.CONGESTED)
        self.assertEqual(events(r), [])

    def test_17_out_of_order_and_duplicate_timestamps(self):
        d, t = warmed()
        ok = d.update(Sample(ENT, t, 0.1))
        dup = d.update(Sample(ENT, t, 0.9))
        old = d.update(Sample(ENT, t - 5, 0.9))
        self.assertTrue(ok.valid)
        self.assertEqual((dup.reason, old.reason), ("OUT_OF_ORDER_OR_DUPLICATE",) * 2)

    def test_irregular_intervals_are_sample_based(self):
        d, t = warmed()
        r = []
        for ts in (t + 1, t + 1.1, t + 9.0):                     # irregular spacing, still 3 samples
            r.append(d.update(Sample(ENT, ts, 0.95)))
        self.assertEqual(events(r), [CONG])


class TestMultiEntityAndDeterminism(unittest.TestCase):
    def test_19_independent_entities(self):
        m = DetectorManager()
        a, b = ("s1", 1), ("s1", 2)
        for i in range(10):
            m.update(Sample(a, i, 0.1)); m.update(Sample(b, i, 0.1))
        evs = []
        for i in range(10, 13):
            evs.append(m.update(Sample(a, i, 0.95)).event)
            m.update(Sample(b, i, 0.1))
        self.assertEqual(evs[-1], CONG)
        self.assertEqual(m.detector(a).state, State.CONGESTED)
        self.assertEqual(m.detector(b).state, State.NORMAL)
        self.assertEqual(m.detector(b).baseline, 0.1)

    def test_deterministic(self):
        vals = [0.1, 0.12, 0.9, 0.95, 0.99, 0.2, 0.1, None, 0.1, 0.1, 0.1, 0.1, 0.1] * 3
        a = [x.to_dict() for x in feed(CongestionDetector(ENT), vals)]
        b = [x.to_dict() for x in feed(CongestionDetector(ENT), vals)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
