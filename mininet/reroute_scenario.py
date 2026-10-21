#!/usr/bin/env python3
"""Automated Mininet test runner demonstrating dynamic traffic rerouting upon congestion.

Scenario:
1. Initialize Diamond Multipath topology (s1, s2, s3).
2. Start background iperf3 server on h3.
3. Phase 1 (Baseline): h1 sends 2 Mbit/s to h3 (takes primary path s1 -> s2 -> h3).
4. Phase 2 (Congestion Trigger): h2 launches 9.5 Mbit/s to h3 over the 10 Mbit/s bottleneck.
   Detector triggers CONGESTION_CONFIRMED on (1, 3).
   Controller dynamically reroutes flow to bypass path s1 -> s3 -> s2 -> h3.
5. Phase 3 (Recovery): h2 stops; traffic returns to 2 Mbit/s.
   Detector triggers RECOVERY_CONFIRMED; controller restores or stabilizes path.

Usage (Linux with Mininet, OVS, and Ryu running):
    sudo python3 mininet/reroute_scenario.py
"""
import json
import sys
import time

from mininet.log import setLogLevel
from mininet.net import Mininet

from multipath_topo import CONTROLLER, DiamondMultipathTopo


def run_reroute_test(output_file="reroute_phases.json"):
    setLogLevel("info")
    print("[TEST] Starting Diamond Multipath Mininet network...")
    net = Mininet(topo=DiamondMultipathTopo(), build=False, **CONTROLLER)
    net.build()
    net.start()

    h1, h2, h3 = net.get("h1"), net.get("h2"), net.get("h3")
    print("[TEST] Verifying initial ping connectivity...")
    net.pingAll()

    print("[TEST] Starting iperf3 server on h3 (10.0.0.3)...")
    h3.cmd("iperf3 -s -D")
    time.sleep(1)

    phases = []

    # Phase 1: Baseline (2 Mbps for 20s)
    print("\n--- PHASE 1: Baseline Traffic (2 Mbps h1 -> h3) ---")
    p1_start = time.monotonic()
    h1.cmd(f"iperf3 -u -b 2M -t 20 -c {h3.IP()} > /dev/null &")
    time.sleep(20)
    phases.append({"phase": 1, "name": "baseline", "start": p1_start, "end": time.monotonic(),
                   "congested": False, "offered_mbps": 2.0})

    # Phase 2: Overload & Reroute (9.5 Mbps h2 -> h3 while h1 continues)
    print("\n--- PHASE 2: Inducing Congestion on s1:port3 (9.5 Mbps h2 -> h3) ---")
    p2_start = time.monotonic()
    h2.cmd(f"iperf3 -u -b 9.5M -t 35 -c {h3.IP()} > /dev/null &")
    time.sleep(35)
    phases.append({"phase": 2, "name": "congestion_and_reroute", "start": p2_start, "end": time.monotonic(),
                   "congested": True, "offered_mbps": 11.5})

    # Phase 3: Recovery
    print("\n--- PHASE 3: Congestion Cleared, Monitoring Recovery ---")
    p3_start = time.monotonic()
    time.sleep(25)
    phases.append({"phase": 3, "name": "recovery", "start": p3_start, "end": time.monotonic(),
                   "congested": False, "offered_mbps": 2.0})

    h3.cmd("pkill iperf3")
    net.stop()

    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump({"scenario": "diamond_reroute", "phases": phases}, fh, indent=2)

    print(f"\n[TEST COMPLETE] Phase timeline saved to {output_file}.")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "reroute_phases.json"
    run_reroute_test(out)
