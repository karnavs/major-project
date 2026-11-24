"""Interactive SDN Simulation Engine for Real-Time UI and Sandboxing.

Provides step-by-step and continuous execution of:
- Diamond Topology (s1, s2, s3 + h1..h4)
- Port Byte Statistics accumulation & ingestion
- Adaptive EWMA Congestion Detection (Persistence N=3, Hysteresis M=5)
- Dynamic Dijkstra Shortest Path Rerouting
- Comparison metrics against Unmanaged/Static SDN (Packet Drops & Queuing Latency)
"""
from __future__ import annotations

import json
import math
import os
import sys
import types
from collections import namedtuple
from typing import Any, Dict, List, Optional

# Ensure repo root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from congestion_detection import (
    AdaptiveRoutingController,
    Event,
    State,
)

St = namedtuple("St", "port_no tx_bytes rx_bytes")
CAP_10M = 10_000_000  # 10 Mbps


class SimulatedDatapath:
    def __init__(self, dpid: int):
        self.id = dpid
        self.sent_msgs = []
        self.flow_table = []
        self.ofproto = types.SimpleNamespace(
            OFP_NO_BUFFER=0xffffffff,
            OFPP_FLOOD=0xfffffffb,
            OFPIT_APPLY_ACTIONS=4
        )
        self.ofproto_parser = types.SimpleNamespace(
            OFPMatch=lambda **k: ("match", k),
            OFPActionOutput=lambda p, *a: ("action_out", p),
            OFPInstructionActions=lambda t, a: ("inst", a),
            OFPFlowMod=self._mock_flow_mod,
            OFPPacketOut=lambda **k: ("packet_out", k),
            OFPPortStatsRequest=lambda *a: ("stats_req", a),
        )

    def _mock_flow_mod(self, **k):
        return ("flow_mod", k)

    def send_msg(self, msg):
        self.sent_msgs.append(msg)
        if isinstance(msg, tuple) and msg[0] == "flow_mod":
            mod_data = msg[1]
            match_data = mod_data.get("match", ("match", {}))[1]
            actions = []
            for inst in mod_data.get("instructions", []):
                if isinstance(inst, tuple) and inst[0] == "inst":
                    for act in inst[1]:
                        if isinstance(act, tuple) and act[0] == "action_out":
                            actions.append(f"OUTPUT:port_{act[1]}")
            self.flow_table.append({
                "priority": mod_data.get("priority", 0),
                "match": match_data,
                "actions": actions or ["OUTPUT:NORMAL"],
            })


class SDNSimulationEngine:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(BASE_DIR, "config", "congestion_detector.json")
        self.config_path = config_path
        os.environ["SDN_CONGESTION_CONFIG"] = config_path

        self.reset()

    def reset(self):
        """Reset simulation state back to t=0."""
        self.time_s: float = 0.0
        self.is_running: bool = False
        self.speed: float = 1.0
        self.offered_util: float = 0.10
        self.mode: str = "sandbox"  # 'sandbox' or 'scenario_70s'

        # Initialize controller
        self.ctrl = AdaptiveRoutingController()
        self.switches = {1: SimulatedDatapath(1), 2: SimulatedDatapath(2), 3: SimulatedDatapath(3)}
        self.ctrl.datapaths = self.switches

        # Register hosts
        self.ctrl.engine.register_host("00:00:00:00:00:01", dpid=1, port=1)
        self.ctrl.engine.register_host("00:00:00:00:00:03", dpid=2, port=1)

        # Initial flow from h1 to h3
        self.initial_flow = self.ctrl.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=0.0)

        # Cumulative byte counters per switch port: (dpid, port) -> bytes
        self.counters: Dict[tuple, int] = {
            (1, 3): 0, (1, 4): 0,
            (2, 3): 0, (2, 4): 0,
            (3, 1): 0, (3, 2): 0
        }

        self.history: List[Dict[str, Any]] = []
        self.event_logs: List[Dict[str, Any]] = []

        # Latest step metrics cache
        self.latest_decision = None
        self._record_log("System initialized", "Diamond topology online. Primary route [s1, s2] active.")

    def _record_log(self, title: str, detail: str, level: str = "info"):
        self.event_logs.insert(0, {
            "time": round(self.time_s, 1),
            "title": title,
            "detail": detail,
            "level": level,  # 'info', 'warning', 'critical', 'success'
        })
        if len(self.event_logs) > 50:
            self.event_logs.pop()

    def set_load(self, util: float):
        """Manually set offered load (0.0 to 1.0)."""
        self.offered_util = max(0.01, min(1.0, float(util)))
        self.mode = "sandbox"

    def inject_congestion(self, util: float = 0.95):
        """Immediately trigger heavy traffic surge."""
        self.offered_util = util
        self.mode = "sandbox"
        self._record_log("Traffic Surge Injected", f"Offered load increased to {int(util*100)}% (9.5 Mbps)", "warning")

    def relieve_congestion(self, util: float = 0.10):
        """Relieve congestion to normal load."""
        self.offered_util = util
        self.mode = "sandbox"
        self._record_log("Traffic Normalized", f"Offered load reduced to {int(util*100)}% (1.0 Mbps)", "info")

    def step(self) -> Dict[str, Any]:
        """Advance simulation by 1 second."""
        self.time_s += 1.0
        t = self.time_s

        # In 70s scenario mode, determine load based on timeline
        if self.mode == "scenario_70s":
            if t <= 20:
                self.offered_util = 0.10
                phase = "BASELINE"
            elif 20 < t <= 45:
                self.offered_util = 0.95
                phase = "OVERLOAD"
            else:
                self.offered_util = 0.10
                phase = "RECOVERY"
        else:
            phase = "SANDBOX"

        # Advance bytes on primary link
        bytes_added = int(self.offered_util * CAP_10M / 8)
        self.counters[(1, 3)] += bytes_added

        # Ingest port stats into CongestionService
        body_s1 = [St(3, self.counters[(1, 3)], 0), St(4, self.counters[(1, 4)], 0)]
        decisions = self.ctrl.congestion_service.ingest_port_stats(1, body_s1, float(t))
        d3 = next((d for d in decisions if d.entity == (1, 3)), None)
        self.latest_decision = d3

        active_flow = self.ctrl.engine.active_flows.get(("00:00:00:00:00:01", "00:00:00:00:00:03"))
        current_path = list(active_flow.path_dpids) if active_flow else [1, 2]

        # Log events
        if d3 and d3.event == Event.CONGESTION_CONFIRMED:
            self._record_log(
                "Congestion Confirmed (Rerouted)",
                f"Switch 1 Port 3 exceeded threshold {d3.t_enter:.2f}. Traffic rerouted to bypass: {current_path}",
                "critical"
            )
        elif d3 and d3.event == Event.RECOVERY_CONFIRMED:
            self._record_log(
                "Recovery Confirmed (Restored)",
                f"Switch 1 Port 3 normalized below {d3.t_exit:.2f}. Flow restored to primary: {current_path}",
                "success"
            )
        elif d3 and d3.state == State.CONGESTION_PENDING:
            streak = getattr(d3, "streak", 1)
            self._record_log(
                "Congestion Pending",
                f"Surge detected on primary link. Persistence verifying ({streak}/3)...",
                "warning"
            )

        # Baseline Comparison Metrics (Static SDN vs Adaptive SDN)
        is_adaptive_rerouted = (current_path == [1, 3, 2])
        
        # Adaptive SDN performance
        if is_adaptive_rerouted:
            adaptive_throughput = round(self.offered_util * 10.0, 2)
            adaptive_loss_pct = 0.0
            adaptive_latency_ms = round(3.8 + (self.offered_util * 0.4), 1)  # Extra hop through s3
            adaptive_status = "BYPASS [s1 -> s3 -> s2]"
        elif self.offered_util > 0.85 and not is_adaptive_rerouted:
            # During the 3-sample pending phase
            adaptive_throughput = round(min(8.5, self.offered_util * 10.0), 2)
            adaptive_loss_pct = round(max(0.0, (self.offered_util - 0.85) / self.offered_util * 15.0), 1)
            adaptive_latency_ms = round(12.0 + (self.offered_util * 8.0), 1)
            adaptive_status = "PENDING REROUTE"
        else:
            adaptive_throughput = round(self.offered_util * 10.0, 2)
            adaptive_loss_pct = 0.0
            adaptive_latency_ms = round(2.1 + (self.offered_util * 0.8), 1)
            adaptive_status = "PRIMARY [s1 -> s2]"

        # Static SDN performance (Never reroutes, drops packets when congested)
        if self.offered_util > 0.75:
            # Bottleneck buffer overflow
            overflow = self.offered_util - 0.75
            static_loss_pct = round(min(52.0, (overflow / self.offered_util) * 100.0), 1)
            static_throughput = round(7.5 + (0.5 * (1.0 - static_loss_pct / 100.0)), 2)
            static_latency_ms = round(22.0 + (self.offered_util * 68.0), 1)  # Severe bufferbloat
            static_status = "BOTTLENECK OVERFLOW"
        else:
            static_loss_pct = 0.0
            static_throughput = round(self.offered_util * 10.0, 2)
            static_latency_ms = round(2.1 + (self.offered_util * 0.8), 1)
            static_status = "NORMAL [s1 -> s2]"

        step_record = {
            "time_s": t,
            "phase": phase,
            "offered_util": round(self.offered_util, 3),
            "offered_mbps": round(self.offered_util * 10.0, 2),
            "detector_state": d3.state.value if d3 else "UNKNOWN",
            "detector_event": d3.event.value if d3 and d3.event else None,
            "t_enter": round(d3.t_enter, 3) if d3 else 0.40,
            "t_exit": round(d3.t_exit, 3) if d3 else 0.30,
            "baseline": round(d3.baseline, 3) if d3 and d3.baseline is not None else 0.10,
            "active_path": current_path,
            "is_rerouted": is_adaptive_rerouted,
            "adaptive": {
                "throughput_mbps": adaptive_throughput,
                "loss_pct": adaptive_loss_pct,
                "latency_ms": adaptive_latency_ms,
                "status": adaptive_status,
                "path": current_path,
            },
            "static": {
                "throughput_mbps": static_throughput,
                "loss_pct": static_loss_pct,
                "latency_ms": static_latency_ms,
                "status": static_status,
                "path": [1, 2],
            }
        }

        self.history.append(step_record)
        if len(self.history) > 120:
            self.history.pop(0)

        return step_record

    def get_state(self) -> Dict[str, Any]:
        """Return comprehensive state for UI rendering."""
        d3 = self.latest_decision
        active_flow = self.ctrl.engine.active_flows.get(("00:00:00:00:00:01", "00:00:00:00:00:03"))
        current_path = list(active_flow.path_dpids) if active_flow else [1, 2]
        is_rerouted = (current_path == [1, 3, 2])

        # Link utilization dictionary
        # Link 1: s1 -> s2 (port 3)
        # Link 2: s1 -> s3 (port 4)
        # Link 3: s3 -> s2 (port 2)
        if is_rerouted:
            link_s1_s2_util = 0.02
            link_s1_s3_util = self.offered_util
            link_s3_s2_util = self.offered_util
        else:
            link_s1_s2_util = self.offered_util
            link_s1_s3_util = 0.01
            link_s3_s2_util = 0.01

        # Current comparison snapshot
        latest = self.history[-1] if self.history else None

        return {
            "time_s": self.time_s,
            "is_running": self.is_running,
            "speed": self.speed,
            "mode": self.mode,
            "offered_util": round(self.offered_util, 3),
            "offered_mbps": round(self.offered_util * 10.0, 2),
            "detector": {
                "state": d3.state.value if d3 else "NORMAL",
                "event": d3.event.value if d3 and d3.event else None,
                "t_enter": round(d3.t_enter, 3) if d3 else 0.40,
                "t_exit": round(d3.t_exit, 3) if d3 else 0.30,
                "baseline": round(d3.baseline, 3) if d3 and d3.baseline is not None else 0.10,
                "entity": [1, 3],
            },
            "topology": {
                "switches": [
                    {"dpid": 1, "name": "s1 (Ingress)", "role": "ingress", "x": 180, "y": 180},
                    {"dpid": 2, "name": "s2 (Egress)", "role": "egress", "x": 620, "y": 180},
                    {"dpid": 3, "name": "s3 (Bypass)", "role": "bypass", "x": 400, "y": 340},
                ],
                "hosts": [
                    {"mac": "00:00:00:00:00:01", "name": "h1 (Sender)", "dpid": 1, "port": 1, "x": 60, "y": 140},
                    {"mac": "00:00:00:00:00:02", "name": "h2", "dpid": 1, "port": 2, "x": 60, "y": 220},
                    {"mac": "00:00:00:00:00:03", "name": "h3 (Receiver)", "dpid": 2, "port": 1, "x": 740, "y": 140},
                    {"mac": "00:00:00:00:00:04", "name": "h4", "dpid": 2, "port": 2, "x": 740, "y": 220},
                ],
                "links": [
                    {
                        "id": "link-s1-s2",
                        "src": 1, "dst": 2, "src_port": 3, "dst_port": 3,
                        "type": "primary",
                        "util": round(link_s1_s2_util, 3),
                        "mbps": round(link_s1_s2_util * 10.0, 2),
                        "capacity_mbps": 10.0,
                        "active": not is_rerouted,
                        "congested": (link_s1_s2_util > 0.80),
                    },
                    {
                        "id": "link-s1-s3",
                        "src": 1, "dst": 3, "src_port": 4, "dst_port": 1,
                        "type": "bypass_a",
                        "util": round(link_s1_s3_util, 3),
                        "mbps": round(link_s1_s3_util * 10.0, 2),
                        "capacity_mbps": 10.0,
                        "active": is_rerouted,
                        "congested": False,
                    },
                    {
                        "id": "link-s3-s2",
                        "src": 3, "dst": 2, "src_port": 2, "dst_port": 4,
                        "type": "bypass_b",
                        "util": round(link_s3_s2_util, 3),
                        "mbps": round(link_s3_s2_util * 10.0, 2),
                        "capacity_mbps": 10.0,
                        "active": is_rerouted,
                        "congested": False,
                    },
                ],
                "active_path": current_path,
                "is_rerouted": is_rerouted,
            },
            "comparison": {
                "adaptive": latest["adaptive"] if latest else {
                    "throughput_mbps": 1.0, "loss_pct": 0.0, "latency_ms": 2.2, "status": "PRIMARY [s1 -> s2]", "path": [1, 2]
                },
                "static": latest["static"] if latest else {
                    "throughput_mbps": 1.0, "loss_pct": 0.0, "latency_ms": 2.2, "status": "NORMAL [s1 -> s2]", "path": [1, 2]
                }
            },
            "flow_tables": {
                "s1": self.switches[1].flow_table[-4:],
                "s2": self.switches[2].flow_table[-4:],
                "s3": self.switches[3].flow_table[-4:],
            },
            "recent_events": self.event_logs[:12],
            "history": self.history[-40:],
        }
