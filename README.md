# Adaptive Congestion Detection & Traffic Rerouting in SDN

Adaptive-threshold + persistence + hysteresis + recovery congestion detector, paired with a dynamic Dijkstra routing engine and Ryu OpenFlow 1.3 controller for congestion-aware traffic rerouting and load distribution.

## Quick Start (Dependency-free on any OS)
```bash
# Unified CLI runner (Interactive menu or direct flags)
python main.py

# Or run components directly:
python main.py --simulate     # End-to-end traffic rerouting & load distribution simulation
python main.py --test         # All 57 unit and integration tests
python main.py --synthetic    # 13 synthetic detector trace scenarios
python main.py --info         # Display network topology & active link capacities
```

## Running with Ryu Controller & Mininet (Linux / VM / WSL)
```bash
# Terminal 1: Launch Ryu Adaptive Routing Controller
SDN_CONGESTION_CONFIG=config/congestion_detector.json ryu-manager congestion_detection/routing_controller.py

# Terminal 2: Launch Diamond Multi-Path Mininet Topology
sudo python3 mininet/multipath_topo.py

# Or run the automated multi-phase rerouting scenario
sudo python3 mininet/reroute_scenario.py
```

## Documentation
- `docs/CONGESTION_DETECTOR_SPEC.md` — Algorithm specifications, state machine table, parameter definitions.
- `docs/INTEGRATION.md` — Integration contract between OpenFlow port stats and routing callbacks.
- `docs/TEST_REPORT.md` — Empirical test results, detector delay, hysteresis benchmarks.
- `docs/REPORT_AND_VIVA.md` — Project report summary and viva Q&A cheat-sheet.
- `PROJECT_CONTEXT.md` & `CHANGELOG.md` — Session handoffs, git state, and component verification.
