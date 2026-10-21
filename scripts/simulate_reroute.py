#!/usr/bin/env python3
"""End-to-End Simulation of Adaptive Congestion-Aware Traffic Rerouting.

Simulates the complete feedback loop:
  1. Traffic generation on Diamond topology (s1, s2, s3).
  2. Byte counters accumulation and periodic OFPPortStatsReply events.
  3. Real-time congestion detection (EWMA adaptive threshold + persistence).
  4. Dynamic Dijkstra shortest path recalculation upon CONGESTION_CONFIRMED.
  5. OpenFlow FlowMod installation rerouting traffic over bypass switch s3.
  6. Recovery detection (hysteresis + exit persistence) and route restoration.

Outputs a detailed step-by-step log and saves execution metrics to JSON.
"""
from __future__ import annotations

import json
import os
import sys
import types
from collections import namedtuple
from typing import Dict, List

# Ensure sdn_congestion is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from congestion_detection import (
    AdaptiveRoutingController,
    Event,
)

St = namedtuple("St", "port_no tx_bytes rx_bytes")
CAP_10M = 10_000_000  # 10 Mbps


class SimulatedDatapath:
    def __init__(self, dpid: int):
        self.id = dpid
        self.sent_msgs = []
        self.ofproto = types.SimpleNamespace(
            OFP_NO_BUFFER=0xffffffff,
            OFPP_FLOOD=0xfffffffb,
            OFPIT_APPLY_ACTIONS=4
        )
        self.ofproto_parser = types.SimpleNamespace(
            OFPMatch=lambda **k: ("match", k),
            OFPActionOutput=lambda p, *a: ("action_out", p),
            OFPInstructionActions=lambda t, a: ("inst", a),
            OFPFlowMod=lambda **k: ("flow_mod", k),
            OFPPacketOut=lambda **k: ("packet_out", k),
            OFPPortStatsRequest=lambda *a: ("stats_req", a),
        )

    def send_msg(self, msg):
        self.sent_msgs.append(msg)


def run_simulation(out_json="docs/results/reroute_simulation_results.json"):
    print("=" * 72)
    print("  SDN ADAPTIVE CONGESTION-AWARE TRAFFIC REROUTING SIMULATION")
    print("=" * 72)

    cfg = {
        "poll_interval_s": 1.0,
        "detector": {
            "alpha": 0.1, "k": 3.0, "min_variation": 0.02, "warmup_samples": 10,
            "threshold_min": 0.40, "threshold_max": 0.85, "hysteresis_margin": 0.10,
            "enter_persistence": 3, "exit_persistence": 5, "max_invalid_streak": 5
        },
        "adapter": {
            "capacity_bps": {
                "1:3": CAP_10M, "1:4": CAP_10M,
                "2:3": CAP_10M, "2:4": CAP_10M,
                "3:1": CAP_10M, "3:2": CAP_10M
            },
            "max_interval_s": 5.0,
            "direction": "tx"
        },
        "monitored_ports": {"1": [3, 4], "2": [3, 4], "3": [1, 2]},
        "congestion_penalty": 1000.0
    }

    # Initialize controller
    cfg_path = os.path.join(BASE_DIR, "config", "congestion_detector.json")
    os.environ["SDN_CONGESTION_CONFIG"] = cfg_path
    ctrl = AdaptiveRoutingController()

    # Attach simulated switches s1, s2, s3
    switches = {1: SimulatedDatapath(1), 2: SimulatedDatapath(2), 3: SimulatedDatapath(3)}
    ctrl.datapaths = switches

    # Register hosts h1 on s1:port1 and h3 on s2:port1
    ctrl.engine.register_host("00:00:00:00:00:01", dpid=1, port=1)
    ctrl.engine.register_host("00:00:00:00:00:03", dpid=2, port=1)

    # Initial flow from h1 to h3
    initial_flow = ctrl.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=0.0)
    print(f"[*] Initial Active Flow h1 -> h3 Path: {initial_flow.path_dpids} (Primary direct link s1 -> s2)")

    # Cumulative byte counters per switch port: (dpid, port) -> bytes
    counters: Dict[tuple, int] = {
        (1, 3): 0, (1, 4): 0,
        (2, 3): 0, (2, 4): 0,
        (3, 1): 0, (3, 2): 0
    }

    timeline = []
    # 70 seconds total:
    # 0 - 20s: Warmup & baseline (10% utilization = 1 Mbps)
    # 20 - 45s: Overload / Congestion (95% utilization = 9.5 Mbps on s1:port3)
    # 45 - 70s: Load drops back to 10% (Recovery phase)
    total_seconds = 70

    print("\n--- Starting 70-second timeline simulation ---")
    for t in range(1, total_seconds + 1):
        # Determine offered utilization on s1:port3
        if t <= 20:
            offered_util = 0.10
            phase = "BASELINE"
        elif 20 < t <= 45:
            offered_util = 0.95
            phase = "OVERLOAD"
        else:
            offered_util = 0.10
            phase = "RECOVERY"

        # Advance bytes
        bytes_added = int(offered_util * CAP_10M / 8)
        counters[(1, 3)] += bytes_added

        # Generate OFPPortStatsReply for switch 1
        body_s1 = [St(3, counters[(1, 3)], 0), St(4, counters[(1, 4)], 0)]
        ev = types.SimpleNamespace(msg=types.SimpleNamespace(datapath=switches[1], body=body_s1))

        # Ingest stats
        decisions = ctrl.congestion_service.ingest_port_stats(1, body_s1, float(t))
        d3 = next((d for d in decisions if d.entity == (1, 3)), None)

        active_flow = ctrl.engine.active_flows.get(("00:00:00:00:00:01", "00:00:00:00:00:03"))
        current_path = active_flow.path_dpids if active_flow else []

        step_record = {
            "time_s": t,
            "phase": phase,
            "offered_util": offered_util,
            "detector_state": d3.state.value if d3 else "UNKNOWN",
            "detector_event": d3.event.value if d3 and d3.event else None,
            "t_enter": round(d3.t_enter, 3) if d3 else 0.0,
            "t_exit": round(d3.t_exit, 3) if d3 else 0.0,
            "active_path": list(current_path)
        }
        timeline.append(step_record)

        # Print milestones
        if d3 and d3.event == Event.CONGESTION_CONFIRMED:
            print(f"[t={t:02d}s] !!! CONGESTION_CONFIRMED on (1, 3) | Detector: {d3.state.value} | Flow Rerouted to: {current_path}")
        elif d3 and d3.event == Event.RECOVERY_CONFIRMED:
            print(f"[t={t:02d}s] *** RECOVERY_CONFIRMED on (1, 3) | Detector: {d3.state.value} | Flow Restored to: {current_path}")
        elif t in (1, 10, 20, 21, 22, 23, 24, 45, 46, 50, 51, 60, 70):
            event_str = f"-> EVENT: {d3.event.value}" if d3 and d3.event else ""
            print(f"[t={t:02d}s] Phase: {phase:8s} | Util: {offered_util:.2f} | State: {d3.state.value:18s} | Path: {current_path} {event_str}")

    print("\n--- Simulation Summary ---")
    print(f"Total Reroute History Events: {len(ctrl.reroute_history)}")
    for h in ctrl.reroute_history:
        print(f"  - At t={h['time']:.1f}s: {h['event']} {h['flow']} from {h['old_path']} -> {h['new_path']}")

    # Save output
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump({
            "simulation": "adaptive_traffic_reroute",
            "reroute_events": ctrl.reroute_history,
            "timeline": timeline
        }, fh, indent=2)

    print(f"\n[OK] Simulation complete. Results saved to {out_json}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "docs/results/reroute_simulation_results.json"
    run_simulation(out)
