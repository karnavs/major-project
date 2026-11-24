#!/usr/bin/env python3
"""Synthetic trace evaluation. Run from repo root:  python3 scripts/run_synthetic_traces.py
All inputs are SYNTHETIC utilization traces (1 sample/s, seeded RNG) - NOT Mininet measurements.
Writes docs/results/synthetic_trace_results.{json,md}. Exit code 1 if any scenario fails its criteria."""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from congestion_detection import DetectorConfig, DetectorManager, Sample  # noqa: E402
from congestion_detection.evaluation import evaluate  # noqa: E402

DT = 1.0
CFG = DetectorConfig()
ENT_A, ENT_B = ("s1", 1), ("s1", 2)


def noisy(rng, level, n, amp=0.02):
    return [max(0.0, level + rng.uniform(-amp, amp)) for _ in range(n)]


def ramp(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def scenarios():
    r = lambda s: random.Random(s)  # noqa: E731
    S = []
    # name, {entity: values}, {entity: truth intervals [start_idx,end_idx)}, checker(metrics_per_entity)->list of failures
    S.append(("stable_normal", {ENT_A: noisy(r(1), 0.12, 80)}, {ENT_A: []},
              lambda m: [] if m[ENT_A]["congestion_events"] == 0 else ["unexpected congestion event"]))
    v = noisy(r(2), 0.10, 20) + ramp(0.10, 0.95, 100)
    start = next(i for i, x in enumerate(v) if i >= 20 and x >= 0.85)
    S.append(("gradual_increase", {ENT_A: v + [0.95] * 20}, {ENT_A: [(start, len(v) + 20)]},
              lambda m: [] if (m[ENT_A]["congestion_events"] == 1 and m[ENT_A]["false_triggers"] == 0
                               and m[ENT_A]["missed_detections"] == 0) else ["expected exactly 1 timely detection, 0 false triggers"]))
    S.append(("single_burst", {ENT_A: noisy(r(3), 0.12, 20) + [0.95, 0.95] + noisy(r(4), 0.12, 20)}, {ENT_A: []},
              lambda m: [] if m[ENT_A]["congestion_events"] == 0 else ["short burst triggered congestion"]))
    bursts = noisy(r(5), 0.12, 20)
    for _ in range(6):
        bursts += [0.95, 0.95] + noisy(r(6), 0.12, 3)
    S.append(("repeated_short_bursts", {ENT_A: bursts}, {ENT_A: []},
              lambda m: [] if m[ENT_A]["congestion_events"] == 0 else ["repeated bursts triggered congestion"]))
    v = noisy(r(7), 0.12, 20) + noisy(r(8), 0.95, 30, 0.03) + noisy(r(9), 0.12, 20)
    S.append(("sustained_congestion", {ENT_A: v}, {ENT_A: [(20, 50)]},
              lambda m: [] if (m[ENT_A]["detection_delays_s"] == [2.0] and m[ENT_A]["recovery_delays_s"] == [4.0]
                               and m[ENT_A]["false_triggers"] == 0) else ["expected detection delay 2 s and recovery delay 4 s"]))
    dec = ramp(0.95, 0.12, 40)
    v = noisy(r(10), 0.12, 20) + [0.95] * 20 + dec + noisy(r(11), 0.12, 20)
    gt_end = 40 + next(i for i, x in enumerate(dec) if x < 0.60)   # truth: congested while offered load >= 0.60
    S.append(("gradual_recovery", {ENT_A: v}, {ENT_A: [(20, gt_end)]},
              lambda m: [] if (m[ENT_A]["congestion_events"] == 1 and m[ENT_A]["recovery_events"] == 1
                               and m[ENT_A]["false_triggers"] == 0) else ["expected 1 congestion + 1 recovery"]))
    v = noisy(r(12), 0.12, 20) + [0.95] * 15 + [0.10] * 3 + [0.95] * 15 + noisy(r(13), 0.12, 20)
    S.append(("brief_improvement_then_congestion", {ENT_A: v}, {ENT_A: [(20, 53)]},   # dip of 3 < exit_persistence is transient
              lambda m: [] if (m[ENT_A]["congestion_events"] == 1 and m[ENT_A]["recovery_events"] == 1
                               and m[ENT_A]["flap_extra_congestion_events"] == 0) else ["flapping on brief dip"]))
    rr = r(14)
    S.append(("highly_variable_noncongested", {ENT_A: [rr.uniform(0.1, 0.7) for _ in range(200)]}, {ENT_A: []},
              lambda m: [] if m[ENT_A]["congestion_events"] == 0 else ["variable traffic triggered congestion"]))
    v = noisy(r(15), 0.12, 20) + [0.95, 0.95, None, 0.95, None, 0.95, 0.95, 0.95, None, 0.95] * 3 + noisy(r(16), 0.12, 20)
    S.append(("congestion_with_dropped_samples", {ENT_A: v}, {ENT_A: [(20, 50)]},
              lambda m: [] if (m[ENT_A]["congestion_events"] == 1 and m[ENT_A]["missed_detections"] == 0) else ["dropouts blocked detection"]))
    v = noisy(r(17), 0.12, 20) + [0.95, 0.95] + [None] * 5 + [0.95] + noisy(r(18), 0.12, 20)
    S.append(("stale_gap_breaks_pending", {ENT_A: v}, {ENT_A: []},
              lambda m: [] if m[ENT_A]["congestion_events"] == 0 else ["stale gap counted as persistence"]))
    v = noisy(r(19), 0.12, 20) + [0.95] * 10 + [None] * 25
    S.append(("outage_never_infers_recovery", {ENT_A: v}, {ENT_A: [(20, 55)]},
              lambda m: [] if m[ENT_A]["recovery_events"] == 0 and m[ENT_A]["congestion_events"] == 1 else ["outage produced recovery"]))
    S.append(("two_links_independent",
              {ENT_A: noisy(r(20), 0.12, 20) + [0.95] * 30 + noisy(r(21), 0.12, 20),
               ENT_B: noisy(r(22), 0.12, 70)},
              {ENT_A: [(20, 50)], ENT_B: []},
              lambda m: [] if (m[ENT_A]["congestion_events"] == 1 and m[ENT_A]["recovery_events"] == 1
                               and m[ENT_B]["congestion_events"] == 0) else ["link state leaked between entities"]))
    S.append(("startup_already_congested", {ENT_A: [0.95] * 30 + noisy(r(23), 0.12, 20)}, {ENT_A: [(0, 30)]},
              lambda m: [] if (m[ENT_A]["detection_delays_s"] == [2.0] and m[ENT_A]["recovery_delays_s"] == [4.0]) else ["startup congestion mishandled"]))
    return S


def run():
    results, all_pass = [], True
    for name, traces, truth, check in scenarios():
        mgr = DetectorManager(CFG)
        recs = {e: [] for e in traces}
        n = max(len(t) for t in traces.values())
        for i in range(n):
            for e, vals in traces.items():
                if i < len(vals):
                    ts = i * DT
                    x = vals[i]
                    s = Sample(e, ts, x) if x is not None else Sample(e, ts, None, valid=False, reason="MISSING")
                    recs[e].append(mgr.update(s).to_dict())
        metrics = {e: evaluate(recs[e], [(a * DT, b * DT) for a, b in truth[e]]) for e in traces}
        fails = check(metrics)
        all_pass &= not fails
        results.append({"scenario": name, "samples": {str(e): len(v) for e, v in traces.items()},
                        "ground_truth_intervals_s": {str(e): [(a * DT, b * DT) for a, b in truth[e]] for e in traces},
                        "metrics": {str(e): m for e, m in metrics.items()},
                        "events": {str(e): [(x["ts"], x["event"]) for x in recs[e] if x["event"]] for e in traces},
                        "pass": not fails, "failures": fails})
    # processing overhead (measured on this machine, pure detector update, 1 entity)
    mgr, N = DetectorManager(CFG), 200_000
    rng = random.Random(99)
    vals = [rng.uniform(0, 1) for _ in range(N)]
    t0 = time.perf_counter()
    for i, x in enumerate(vals):
        mgr.update(Sample(ENT_A, float(i), x))
    us = (time.perf_counter() - t0) / N * 1e6
    return results, all_pass, us


def write(results, us):
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "results")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "synthetic_trace_results.json"), "w") as fh:
        json.dump({"config": CFG.__dict__, "dt_s": DT, "detector_update_us": us, "results": results}, fh, indent=2)
    L = ["# Synthetic trace results (generated by scripts/run_synthetic_traces.py)", "",
         "Inputs are SYNTHETIC utilization traces, 1 sample/s, seeded RNG. These are NOT Mininet measurements.",
         f"Config: `{CFG}`", "",
         "| Scenario | Entity | Congestion ev. | Recovery ev. | Detection delay (s) | Recovery delay (s) | False triggers | Missed det. | Extra (flap) ev. | Transitions | Invalid | Pass |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        for e, m in r["metrics"].items():
            L.append(f"| {r['scenario']} | {e} | {m['congestion_events']} | {m['recovery_events']} | "
                     f"{m['detection_delays_s']} | {m['recovery_delays_s']} | {m['false_triggers']} | "
                     f"{m['missed_detections']} | {m['flap_extra_congestion_events']} | {m['state_transitions']} | "
                     f"{m['invalid_samples']} | {'PASS' if r['pass'] else 'FAIL'} |")
    L += ["", f"Detector processing cost (measured, pure-Python `update()`, this machine): **{us:.2f} µs/sample**.", ""]
    with open(os.path.join(out, "synthetic_trace_results.md"), "w") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    res, ok, us = run()
    write(res, us)
    for r in res:
        print(("PASS " if r["pass"] else "FAIL ") + r["scenario"], r["failures"] or "")
    print(f"update cost: {us:.2f} us/sample; scenarios: {len(res)}; all_pass={ok}")
    sys.exit(0 if ok else 1)
