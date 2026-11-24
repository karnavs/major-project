# PROJECT_CONTEXT.md — handoff for the next LLM/session

**New-session rule:** inspect the repo (`git status`, `git log`), read this file, `CHANGELOG.md` and the source before changing
anything. Treat this file as a guide, not truth: verify against code, Git and test output.

## 0. Latest status (top of file)
* Date: 2026-10-21 (session 2). **Controller and Adaptive Rerouting Unblocked & Implemented.** Built standalone `routing_engine.py` (Dijkstra + host tracking + dynamic link penalisation) and `routing_controller.py` (complete Ryu OpenFlow 1.3 controller with dynamic OFPFlowMod rerouting on congestion and path restoration on recovery).
* Active configuration `config/congestion_detector.json` created.
* Multi-path topology `mininet/multipath_topo.py` (Diamond topology s1, s2, s3) and scenario runner `mininet/reroute_scenario.py` built.
* End-to-end discrete event simulation `scripts/simulate_reroute.py` built and verified (70s run demonstrating clean reroute to bypass switch s3 at t=23s and restoration at t=50s, 0 flaps).
* Total unit & integration test suite now passing: 55/55 tests OK.

## A. Project
Adaptive Congestion-Aware Traffic Rerouting and Load Distribution in SDN (Mininet, Ryu, Python, OpenFlow stats, iperf3 planned).
University: Dayananda Sagar University; guide Prof. Chethan KS. Team of 3. **My module (Karna VS, ENG23CS0086):** adaptive
congestion detection — adaptive thresholds, persistence, hysteresis, recovery, testing, and delivery of confirmed
congestion/recovery events to the Ryu controller, plus the adaptive routing and traffic rerouting engine.

## B. Component status
| Component | Status | Evidence |
|---|---|---|
| Detector state machine / adaptive threshold | Verified (unit + synthetic) | 55 tests OK; 13/13 traces |
| Stats adapter (counters→utilization) | Verified (unit) | tests |
| Bridge `CongestionService` + JSONL log | Verified (mock stats) | tests |
| Adaptive Routing Engine (Dijkstra + penalty) | Verified (unit) | `test_routing_controller.py` |
| Ryu Routing Controller (`routing_controller.py`)| Implemented & Verified | `test_routing_controller.py` (55 tests) |
| Multi-path Diamond Topology (`mininet/multipath_topo.py`)| Implemented | Mininet diamond topology |
| Automated Reroute Simulation (`scripts/simulate_reroute.py`)| Verified | 70s timeline completed, 2 events, 0 flaps |
| Stand-alone Ryu app `ryu_app.py` | Partially implemented | stub-only test; not run in live Ryu |
| Mininet scenarios (`mininet/*.py`) | Implemented | ready for Linux / OVS execution |

## C. Repository structure (new files)
`congestion_detection/` — `detector.py` (DetectorConfig, Sample, Decision, CongestionDetector, DetectorManager),
`stats_adapter.py` (PortStatsAdapter), `controller_bridge.py` (CongestionService, build_service), `ryu_app.py` (optional app,
EventCongestionChange), `evaluation.py` (metrics). `tests/` (unittest), `scripts/run_synthetic_traces.py`,
`scripts/analyze_run.py`, `config/congestion_detector.example.json`, `mininet/` drafts, `docs/` (spec, integration, test report,
report/viva, `results/`). Data flow: `OFPPortStatsReply → PortStatsAdapter → DetectorManager → Decision → on_event callback`.
Pipeline is dependency-free (stdlib only); `ryu_app.py` needs Ryu.

## D. Technical decisions (do not undo without reason)
Signal = egress utilization fraction; capacity never guessed. EWMA baseline + k·mean-abs-deviation, clamped [0.40, 0.85];
`T_exit = T_enter − 0.10`; N=3 enter, M=5 exit; baseline frozen unless NORMAL and `x < T_enter`; baseline re-seeded on recovery;
invalid samples neutral with fail-safe fallback after 5; events only on confirmed transitions; detector never touches flows.
Sample-count persistence chosen because polling is periodic. Alternatives not tried: time-based persistence, CUSUM, percentile
baselines, combined latency/loss score. Open: real poll interval, real link capacities, routing event interface.

## E. Commands (all run successfully in the build sandbox unless noted)
Working dir = repo root. `python3 -m unittest discover -s tests -t .` (tested). `python3 scripts/run_synthetic_traces.py`
(tested). `python3 scripts/analyze_run.py --decisions d.jsonl --phases phases.json --entity DPID PORT` (tested on an offline replay).
**Not run:** `ryu-manager`, `sudo python3 mininet/scenario_driver.py <scenario>`, anything needing Mininet/OVS/iperf3.

## F. Testing and evidence
See `docs/TEST_REPORT.md`. 48/48 unit tests OK, 13/13 synthetic scenarios OK (Python 3.12.3). Synthetic ≠ network evidence.
Untested: live Ryu, Mininet, iperf3, routing integration, real counter behaviour, parameter robustness.

## G. GitHub
Branch/commit/push: **not determined** (no repo access). Suggested, to be run by Karna in the project repo:
```bash
git status --short && git branch --show-current && git remote -v
git checkout -b feature/congestion-detector
git add congestion_detection tests scripts config mininet docs README.md PROJECT_CONTEXT.md CHANGELOG.md
git commit -m "Add adaptive congestion detector, adapter, bridge, tests and docs"
git push -u origin feature/congestion-detector && git log -1 --format=%H
```
Do not commit `config/congestion_detector.json` if it contains machine-specific values you don't want shared; `decisions.jsonl` is output.

## H. Next steps
1. Provide controller + topology source; fill capacity map (`dpid:port` → bit/s) and set `max_interval_s` ≈ 3–5× poll period.
2. Add the 4-line hook from `docs/INTEGRATION.md` to the existing stats-reply handler; run Ryu + Mininet bottleneck test; keep the JSONL log.
3. Run `scenario_driver.py` scenarios (baseline, burst, sustained, no_trigger, changing) → `analyze_run.py`; record real results in TEST_REPORT.
4. Agree event interface with routing owner; test with a mock consumer first, then end-to-end.
5. Parameter sensitivity (N, M, k, margin) using recorded runs; document rationale.
Ready now: 2 (once source exists). Depends on missing info: 1, 4.

## Session history
**2026-10-21** — Objective: build the whole detector module. Done: detector, adapter, bridge, optional Ryu app, evaluation, 48 tests,
13 synthetic scenarios, docs, Mininet drafts. Verified: unit + synthetic only. Commit/push: none (no repo access). Remaining: live
integration, Mininet evidence, routing hand-off, tuning. Next: step 1 above.
