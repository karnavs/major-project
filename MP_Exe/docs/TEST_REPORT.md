# Test report (only observed results)

Environment of these runs: Linux container, Python 3.12.3, no Mininet, no Open vSwitch, **no importable Ryu**
(`pip install ryu` failed on Python 3.12). Everything below is therefore detector/adapter/bridge-level evidence.
Raw output: `docs/results/unit_test_output.txt`, `docs/results/synthetic_trace_results.{md,json}`.

## 1. Unit + bridge tests — `python3 -m unittest discover -s tests -t .`
**Observed: `Ran 48 tests ... OK`.** Coverage vs the 20-item plan:
| # | Item | Test(s) | Result |
|---|---|---|---|
| 1,2 | valid / invalid config | `TestConfig` | pass |
| 3,4,5 | baseline init, EWMA update, threshold + clamps | `TestBaselineAndThreshold` | pass |
| 6,7,8 | isolated spike, sustained trigger, repeated crossing | `TestPersistence` | pass |
| 9,10 | values at/near threshold, hysteresis band | `test_09`, `test_10` | pass |
| 11,12,13 | recovery not immediate / interrupted / completes | `TestHysteresisAndRecovery` | pass |
| 14,15 | missing, invalid values | `TestInvalidSamples` | pass |
| 16 | counter reset | `test_16_counter_reset_then_recovers` | pass |
| 17 | long/irregular intervals, duplicate timestamps | `test_17_*`, `test_irregular_*` | pass |
| 18 | startup without history / already congested | `test_startup_already_congested` | pass |
| 19 | per-entity independence | `test_19`, `test_per_port_isolation_and_event_once` | pass |
| 20 | event de-duplication | `test_20`, `test_recovery_event_once` | pass |
Also: service-level isolation, reserved-port skipping, consumer exception containment, late-poll handling, switch
disconnect, JSONL log content, evaluator math, and `ryu_app.py` against **stubbed** Ryu modules.

## 2. Synthetic traces — `python3 scripts/run_synthetic_traces.py`
**Observed: 13/13 scenarios met their pre-declared criteria.** Key measured values (1 sample/s, config in the results file):
* sustained congestion: detection delay 2.0 s (= (N−1)·Δt), recovery delay 4.0 s (= (M−1)·Δt), 0 false triggers.
* single burst, repeated bursts, highly variable (200 samples uniform 0.1–0.7): 0 congestion events.
* dropped samples: detected at 3.0 s instead of 2.0 s (neutral invalids delay confirmation); 5-sample gap cancels pending.
* outage after congestion: 0 recovery events (never infers recovery from missing data).
* two links: link B stayed NORMAL while A congested/recovered.
* brief 3-sample dip inside congestion: 1 congestion + 1 recovery, 0 flaps.
* **gradual_increase:** the ramp is tracked by the EWMA; congestion confirmed only once utilization reached the 0.85 ceiling.
  Ground truth for that scenario was *defined* as `x ≥ 0.85`, so the 2.0 s delay is partly by construction.
* **gradual_recovery:** recovery confirmed 18 s after offered load fell below 0.60 (my declared truth boundary), because
  5 consecutive samples below `T_exit = 0.30` are required. This is the hysteresis/recovery latency cost.
* Detector `update()` cost: 8.73 µs/sample (200 000 samples, this machine, single run).

## 3. NOT done (do not cite as results)
Live Ryu integration; Mininet/iperf3 experiments (`mininet/*.py` are untested drafts); routing-module integration;
parameter tuning/sensitivity study; real-traffic false-trigger rates; any throughput/latency/loss claim.

## 4. Limitations
Utilization is the only signal. Thresholds/persistence are untuned defaults. Slow ramps are only caught at the ceiling.
Synthetic ground truth is defined by me, so synthetic "accuracy" is not evidence of real-network accuracy.
Sample-count persistence couples detection latency to the poll period. Counter wrap-around is not modelled.
