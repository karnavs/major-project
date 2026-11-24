import unittest
from congestion_detection.evaluation import evaluate


def rec(ts, event=None, changed=False, valid=True):
    return {"ts": ts, "event": event, "state_changed": changed, "valid": valid}


class TestEvaluate(unittest.TestCase):
    def test_delay_false_trigger_flap_and_miss(self):
        recs = [rec(2, "CONGESTION_CONFIRMED"), rec(6, "RECOVERY_CONFIRMED"),
                rec(7, "CONGESTION_CONFIRMED"),          # 2nd confirm inside same interval -> flap
                rec(50, "CONGESTION_CONFIRMED"),         # outside any truth interval -> false trigger
                rec(9, valid=False)]
        m = evaluate(recs, [(0, 20), (30, 40)])
        self.assertEqual(m["detection_delays_s"], [2, None])
        self.assertEqual(m["missed_detections"], 1)
        self.assertEqual(m["false_triggers"], 1)
        self.assertEqual(m["flap_extra_congestion_events"], 1)
        self.assertEqual(m["recovery_delays_s"], [None, None])   # recovery at t=6 is before interval 1 ends (t=20)
        self.assertEqual(m["invalid_samples"], 1)

    def test_recovery_delay(self):
        m = evaluate([rec(2, "CONGESTION_CONFIRMED"), rec(14, "RECOVERY_CONFIRMED")], [(0, 10)])
        self.assertEqual(m["recovery_delays_s"], [4])
