"""Unit and integration tests for the adaptive routing engine and controller."""
import json
import os
import tempfile
import types
import unittest

from congestion_detection import (
    ActiveFlow,
    AdaptiveRoutingController,
    AdaptiveRoutingEngine,
    Decision,
    Event,
    State,
    TopologyGraph,
)


class TestTopologyAndRoutingEngine(unittest.TestCase):
    def setUp(self):
        # Build standard Diamond Topology:
        # s1: port 3 -> s2: port 3 (primary link, weight 1.0)
        # s1: port 4 -> s3: port 1 (bypass hop 1, weight 1.5)
        # s3: port 2 -> s2: port 4 (bypass hop 2, weight 1.5)
        self.topo = TopologyGraph(congestion_penalty=1000.0)
        self.topo.add_link(1, 3, 2, 3, capacity_bps=10_000_000.0, weight=1.0)
        self.topo.add_link(1, 4, 3, 1, capacity_bps=10_000_000.0, weight=1.5)
        self.topo.add_link(3, 2, 2, 4, capacity_bps=10_000_000.0, weight=1.5)

        self.engine = AdaptiveRoutingEngine(topology=self.topo)
        self.engine.register_host("00:00:00:00:00:01", dpid=1, port=1)
        self.engine.register_host("00:00:00:00:00:03", dpid=2, port=1)

    def test_initial_shortest_path_takes_primary(self):
        res = self.topo.find_shortest_path(1, 2)
        self.assertIsNotNone(res)
        dpids, hops = res
        self.assertEqual(dpids, [1, 2])
        self.assertEqual(hops, [(1, 3)])

    def test_route_computation_between_hosts(self):
        flow = self.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=10.0)
        self.assertIsNotNone(flow)
        self.assertEqual(flow.path_dpids, [1, 2])
        # Hop ports: switch 1 port 3 -> switch 2 port 1 (host)
        self.assertEqual(flow.hop_ports, [(1, 3), (2, 1)])

    def test_congestion_causes_reroute_to_bypass_path(self):
        # 1. Establish initial flow
        flow = self.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=10.0)
        self.assertEqual(flow.path_dpids, [1, 2])

        # 2. Congestion confirmed on switch 1 port 3
        rerouted = self.engine.on_congestion_confirmed(dpid=1, port=3, now=15.0)
        self.assertEqual(len(rerouted), 1)

        updated_flow, old_path = rerouted[0]
        self.assertEqual(old_path, [1, 2])
        # New path must traverse s1 -> s3 -> s2
        self.assertEqual(updated_flow.path_dpids, [1, 3, 2])
        self.assertEqual(updated_flow.hop_ports, [(1, 4), (3, 2), (2, 1)])

    def test_recovery_restores_primary_path(self):
        # Setup and trigger congestion
        self.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=10.0)
        self.engine.on_congestion_confirmed(dpid=1, port=3, now=15.0)
        self.assertEqual(self.engine.active_flows[("00:00:00:00:00:01", "00:00:00:00:00:03")].path_dpids, [1, 3, 2])

        # Recovery confirmed on switch 1 port 3
        restored = self.engine.on_recovery_confirmed(dpid=1, port=3, now=30.0, auto_revert=True)
        self.assertEqual(len(restored), 1)

        new_flow, old_path = restored[0]
        self.assertEqual(old_path, [1, 3, 2])
        self.assertEqual(new_flow.path_dpids, [1, 2])

    def test_same_switch_host_routing(self):
        self.engine.register_host("00:00:00:00:00:02", dpid=1, port=2)
        flow = self.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:02", now=1.0)
        self.assertEqual(flow.path_dpids, [1])
        self.assertEqual(flow.hop_ports, [(1, 2)])

    def test_unknown_host_returns_none(self):
        flow = self.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:99:99", now=1.0)
        self.assertIsNone(flow)

    def test_find_all_paths(self):
        paths = self.topo.find_all_paths(1, 2)
        # In diamond topo: s1 -> s2 (cost 1.0) and s1 -> s3 -> s2 (cost 3.0)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0][0], [1, 2])
        self.assertEqual(paths[1][0], [1, 3, 2])

    def test_multi_flow_load_distribution(self):
        # Register second pair of hosts
        self.engine.register_host("00:00:00:00:00:02", dpid=1, port=2)
        self.engine.register_host("00:00:00:00:00:04", dpid=2, port=2)

        # Flow 1: h1 -> h3
        flow1 = self.engine.compute_route_balanced("00:00:00:00:00:01", "00:00:00:00:00:03", now=1.0)
        self.assertEqual(flow1.path_dpids, [1, 2])

        # Flow 2: h2 -> h4 should be distributed to the alternate path [1, 3, 2] to balance load!
        flow2 = self.engine.compute_route_balanced("00:00:00:00:00:02", "00:00:00:00:00:04", now=2.0)
        self.assertEqual(flow2.path_dpids, [1, 3, 2])


class MockDatapath:
    def __init__(self, dpid):
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


class TestAdaptiveRoutingController(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg_file = os.path.join(self.td.name, "test_cfg.json")
        cfg = {
            "poll_interval_s": 1.0,
            "adapter": {
                "capacity_bps": {
                    "1:3": 10000000, "1:4": 10000000,
                    "2:3": 10000000, "2:4": 10000000,
                    "3:1": 10000000, "3:2": 10000000
                }
            },
            "monitored_ports": {"1": [3, 4], "2": [3, 4], "3": [1, 2]}
        }
        with open(self.cfg_file, "w") as fh:
            json.dump(cfg, fh)
        os.environ["SDN_CONGESTION_CONFIG"] = self.cfg_file

    def tearDown(self):
        self.td.cleanup()
        os.environ.pop("SDN_CONGESTION_CONFIG", None)

    def test_controller_initialization_and_reroute_event(self):
        ctrl = AdaptiveRoutingController()
        # Connect switches s1, s2, s3
        dp1, dp2, dp3 = MockDatapath(1), MockDatapath(2), MockDatapath(3)
        ctrl.datapaths = {1: dp1, 2: dp2, 3: dp3}

        # Register hosts
        ctrl.engine.register_host("00:00:00:00:00:01", dpid=1, port=1)
        ctrl.engine.register_host("00:00:00:00:00:03", dpid=2, port=1)

        # Compute initial route
        flow = ctrl.engine.compute_route("00:00:00:00:00:01", "00:00:00:00:00:03", now=1.0)
        self.assertEqual(flow.path_dpids, [1, 2])

        # Fire CONGESTION_CONFIRMED event via _on_congestion_event callback
        decision = Decision(
            seq=1, entity=(1, 3), timestamp=10.0, value=0.95, valid=True,
            reason="PERSISTENCE_MET", prev_state=State.CONGESTION_PENDING,
            state=State.CONGESTED, state_changed=True,
            event=Event.CONGESTION_CONFIRMED,
            baseline=0.1, variation=0.02, t_enter=0.4, t_exit=0.3,
            enter_count=3, exit_count=0, invalid_streak=0, warmup_complete=True
        )

        ctrl._on_congestion_event(decision)

        # Check that reroute history was logged
        self.assertEqual(len(ctrl.reroute_history), 1)
        rec = ctrl.reroute_history[0]
        self.assertEqual(rec["event"], "REROUTE")
        self.assertEqual(rec["old_path"], [1, 2])
        self.assertEqual(rec["new_path"], [1, 3, 2])

        # Check that FlowMod messages were sent to datapaths
        flow_mods_dp1 = [m for m in dp1.sent_msgs if m[0] == "flow_mod"]
        self.assertTrue(len(flow_mods_dp1) > 0)


if __name__ == "__main__":
    unittest.main()
