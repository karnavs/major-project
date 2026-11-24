"""Adaptive Congestion-Aware Routing Controller for Ryu OpenFlow 1.3.

Integrates CongestionService, adaptive link-weight routing (Dijkstra), and dynamic
flow table modification (OFPFlowMod) upon congestion and recovery events.

Usage:
    SDN_CONGESTION_CONFIG=config/congestion_detector.json ryu-manager congestion_detection/routing_controller.py
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.lib import hub
    from ryu.lib.packet import ethernet, ether_types, packet
    from ryu.ofproto import ofproto_v1_3
    RYU_AVAILABLE = True
except ImportError:
    # Stubs for environments without Ryu installed (e.g. Windows unit test runner)
    RYU_AVAILABLE = False
    class _DummyApp:
        def __init__(self, *a, **k):
            self.logger = logging.getLogger("ryu_stub")
    class _DummyManager:
        RyuApp = _DummyApp
    app_manager = _DummyManager()
    set_ev_cls = lambda *a, **k: (lambda f: f)  # noqa: E731
    CONFIG_DISPATCHER = "config"
    MAIN_DISPATCHER = "main"
    DEAD_DISPATCHER = "dead"
    ofp_event = type("ofp_event", (), {
        "EventOFPSwitchFeatures": object,
        "EventOFPPacketIn": object,
        "EventOFPPortStatsReply": object,
        "EventOFPStateChange": object,
    })
    hub = type("hub", (), {"spawn": lambda *a, **k: None, "sleep": lambda s: None})
    ofproto_v1_3 = type("ofproto_v1_3", (), {"OFP_VERSION": 4})

from congestion_detection.controller_bridge import build_service, CongestionService
from congestion_detection.detector import Decision, Event
from congestion_detection.routing_engine import ActiveFlow, AdaptiveRoutingEngine, TopologyGraph


class AdaptiveRoutingController(app_manager.RyuApp):
    """Ryu OpenFlow 1.3 controller for adaptive congestion-aware routing."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg_path = os.environ.get("SDN_CONGESTION_CONFIG", "config/congestion_detector.json")
        self.config: Dict[str, Any] = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as fh:
                self.config = json.load(fh)
        else:
            self.logger.warning("Config %s not found; running with default parameters", cfg_path)

        self.poll_interval: float = float(self.config.get("poll_interval_s", 1.0))
        self.flow_priority_normal: int = 10
        self.flow_priority_rerouted: int = 20
        self.idle_timeout: int = 60
        self.hard_timeout: int = 180

        # Connected datapaths: dpid -> datapath
        self.datapaths: Dict[int, Any] = {}

        # Initialize topology and routing engine
        self.topology = TopologyGraph(
            congestion_penalty=float(self.config.get("congestion_penalty", 1000.0)),
            logger=self.logger
        )
        self._init_topology_from_config()

        self.engine = AdaptiveRoutingEngine(
            topology=self.topology,
            logger=self.logger
        )

        # Build congestion detection service
        self.congestion_service: CongestionService = build_service(
            self.config,
            on_event=self._on_congestion_event,
            logger=self.logger
        )

        # Log of reroute actions taken
        self.reroute_history: List[Dict[str, Any]] = []

        # Background stats poller
        self._poll_thread = hub.spawn(self._stats_poll_loop)

    def _init_topology_from_config(self) -> None:
        """Seed topology graph with links specified in config, or standard default diamond links."""
        links_cfg = self.config.get("topology_links")
        if links_cfg:
            for lk in links_cfg:
                self.topology.add_link(
                    src_dpid=lk["src_dpid"], src_port=lk["src_port"],
                    dst_dpid=lk["dst_dpid"], dst_port=lk["dst_port"],
                    capacity_bps=lk.get("capacity_bps", 10_000_000.0),
                    weight=lk.get("weight", 1.0),
                    bidirectional=lk.get("bidirectional", True)
                )
        else:
            # Default Diamond Topology:
            # s1 (dpid 1), s2 (dpid 2), s3 (dpid 3)
            # Link 1 (Primary bottleneck): s1:port3 <---> s2:port3 (10 Mbps)
            # Link 2 (Bypass via s3): s1:port4 <---> s3:port1 (10 Mbps)
            # Link 3 (Bypass via s3): s3:port2 <---> s2:port4 (10 Mbps)
            self.topology.add_link(1, 3, 2, 3, capacity_bps=10_000_000.0, weight=1.0)
            self.topology.add_link(1, 4, 3, 1, capacity_bps=10_000_000.0, weight=1.5)
            self.topology.add_link(3, 2, 2, 4, capacity_bps=10_000_000.0, weight=1.5)
            self.logger.info("Initialized default Diamond multipath topology (s1-s2 primary; s1-s3-s2 bypass)")

    # ---------------- OpenFlow Event Handlers ----------------

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.topology.add_switch(dp.id)
            self.logger.info("Switch connected: dpid=%s", dp.id)
        elif dp.id in self.datapaths:
            del self.datapaths[dp.id]
            self.congestion_service.on_switch_disconnect(dp.id)
            self.logger.info("Switch disconnected: dpid=%s", dp.id)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss flow entry (send to controller with priority 0)."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        self.logger.info("Installed table-miss flow rule for switch dpid=%s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handle incoming packet: learn host location, compute path, install flow, and forward."""
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore LLDP
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst_mac = eth.dst
        src_mac = eth.src
        now = time.monotonic()

        # Learn source host location if arriving on an edge port (not an inter-switch link)
        if (dpid, in_port) not in self.topology.port_to_link:
            self.engine.register_host(src_mac, dpid, in_port)

        # If destination is broadcast or multicast, flood to active ports (avoiding loops)
        if dst_mac == "ff:ff:ff:ff:ff:ff" or dst_mac.startswith("01:"):
            self._flood_packet(datapath, msg, in_port)
            return

        # Check if destination host location is known
        dst_host = self.engine.hosts.get(dst_mac)
        if not dst_host:
            # Destination not yet learned: flood so ARP/traffic finds it
            self._flood_packet(datapath, msg, in_port)
            return

        # Compute optimal path for unicast flow
        flow = self.engine.compute_route(src_mac, dst_mac, now)
        if not flow:
            self.logger.warning("No route between %s and %s; dropping packet", src_mac, dst_mac)
            return

        # Install flow rules along all switches on the path
        self._install_path_flows(flow, priority=self.flow_priority_normal)

        # Forward the packet out of the first hop
        first_hop_port = flow.hop_ports[0][1]
        out_actions = [parser.OFPActionOutput(first_hop_port)]
        data = None if msg.buffer_id != datapath.ofproto.OFP_NO_BUFFER else msg.data
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
            actions=out_actions, data=data
        )
        datapath.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Pass port statistics directly to the congestion detection service."""
        now = time.monotonic()
        dpid = ev.msg.datapath.id
        self.congestion_service.ingest_port_stats(dpid, ev.msg.body, now)

    # ---------------- Congestion Callback & Rerouting ----------------

    def _on_congestion_event(self, decision: Decision) -> None:
        """Callback invoked by CongestionService upon confirmed state changes."""
        dpid, port = decision.entity
        now = decision.timestamp

        if decision.event == Event.CONGESTION_CONFIRMED:
            self.logger.warning("CONGESTION DETECTED on switch %d port %d (utilization=%.2f, threshold=%.2f)",
                                dpid, port, decision.value, decision.t_enter)
            rerouted_flows = self.engine.on_congestion_confirmed(dpid, port, now)
            for new_flow, old_path in rerouted_flows:
                # Install new bypass rules with higher priority
                self._install_path_flows(new_flow, priority=self.flow_priority_rerouted)
                rec = {
                    "time": now,
                    "event": "REROUTE",
                    "entity": (dpid, port),
                    "flow": new_flow.flow_id,
                    "old_path": old_path,
                    "new_path": new_flow.path_dpids,
                }
                self.reroute_history.append(rec)
                self.logger.info("SUCCESSFULLY REROUTED flow %s: %s -> %s",
                                 new_flow.flow_id, old_path, new_flow.path_dpids)

        elif decision.event == Event.RECOVERY_CONFIRMED:
            self.logger.info("RECOVERY CONFIRMED on switch %d port %d (utilization=%.2f, exit_threshold=%.2f)",
                             dpid, port, decision.value, decision.t_exit)
            restored_flows = self.engine.on_recovery_confirmed(dpid, port, now, auto_revert=True)
            for new_flow, old_path in restored_flows:
                self._install_path_flows(new_flow, priority=self.flow_priority_normal)
                rec = {
                    "time": now,
                    "event": "RESTORE",
                    "entity": (dpid, port),
                    "flow": new_flow.flow_id,
                    "old_path": old_path,
                    "new_path": new_flow.path_dpids,
                }
                self.reroute_history.append(rec)
                self.logger.info("RESTORED flow %s to primary path: %s -> %s",
                                 new_flow.flow_id, old_path, new_flow.path_dpids)

    # ---------------- Flow Table Helpers ----------------

    def _add_flow(self, datapath, priority: int, match, actions, idle_timeout: int = 0, hard_timeout: int = 0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            instructions=inst
        )
        datapath.send_msg(mod)

    def _install_path_flows(self, flow: ActiveFlow, priority: int) -> None:
        """Install flow entries on all switches along flow.path_dpids."""
        src_mac, dst_mac = flow.flow_id
        for dpid, out_port in flow.hop_ports:
            dp = self.datapaths.get(dpid)
            if not dp:
                continue
            parser = dp.ofproto_parser
            match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            self._add_flow(
                dp, priority=priority, match=match, actions=actions,
                idle_timeout=self.idle_timeout, hard_timeout=self.hard_timeout
            )

    def _flood_packet(self, datapath, msg, in_port: int) -> None:
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        data = None if msg.buffer_id != ofproto.OFP_NO_BUFFER else msg.data
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data
        )
        datapath.send_msg(out)

    def _stats_poll_loop(self) -> None:
        """Periodic thread querying port statistics from all active switches."""
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                ofp = dp.ofproto
                req = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
                dp.send_msg(req)
            hub.sleep(self.poll_interval)
