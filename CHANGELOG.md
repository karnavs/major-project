# Changelog

## [Unreleased] — 2026-10-21 (session 1)
Added (all verified only at the level stated):
- `congestion_detection/detector.py` — EWMA adaptive threshold, persistence, hysteresis, recovery, 4-state machine, per-entity manager. **Verified:** unit + synthetic tests.
- `congestion_detection/stats_adapter.py` — port counters → utilization with validity handling. **Verified:** unit tests.
- `congestion_detection/controller_bridge.py` — `CongestionService`, JSONL decision log, config builder. **Verified:** unit tests with mock stats.
- `congestion_detection/ryu_app.py` — optional stand-alone Ryu app. **Partially verified:** stubbed-Ryu test only; never run in live Ryu.
- `congestion_detection/evaluation.py`, `scripts/run_synthetic_traces.py`, `scripts/analyze_run.py` — metrics. **Verified:** unit tests, synthetic run, offline replay.
- `mininet/bottleneck_topo.py`, `mininet/scenario_driver.py` — **Unverified drafts** (Mininet/iperf3 not available in the build environment).
- Tests: 48 passing (`python3 -m unittest discover -s tests -t .`). Docs: spec, integration contract, test report, report/viva notes.

## [Unreleased] — 2026-10-21 (session 2)
Added & unblocked:
- `config/congestion_detector.json` — Active production configuration with monitored link capacities for single-bottleneck and diamond topologies.
- `congestion_detection/routing_engine.py` — `TopologyGraph` and `AdaptiveRoutingEngine` implementing Dijkstra shortest path, host tracking, dynamic link weight penalties upon congestion, and automatic flow rerouting. **Verified:** unit tests.
- `congestion_detection/routing_controller.py` — Full OpenFlow 1.3 Ryu controller integrating `CongestionService` with dynamic flow modification (`OFPFlowMod`). Installs bypass flow rules on confirmed congestion and restores primary paths on recovery. **Verified:** stubbed integration tests.
- `mininet/multipath_topo.py` — Diamond Multi-Path Topology (s1, s2, s3) providing an alternate bypass path for traffic rerouting and load distribution.
- `mininet/reroute_scenario.py` — Automated Mininet script executing phased load to evaluate traffic rerouting under congestion.
- `scripts/simulate_reroute.py` — End-to-end discrete event simulation verifying the full loop (traffic -> port stats -> detector -> Dijkstra -> flow mod -> reroute -> recovery). **Verified:** 70s simulation completed with zero flaps.
- `tests/test_routing_controller.py` — 7 new unit & integration tests (total 55 passing tests).
