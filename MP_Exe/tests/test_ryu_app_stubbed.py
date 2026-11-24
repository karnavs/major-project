"""Exercises congestion_detection/ryu_app.py against STUBBED ryu modules (real Ryu is not importable on
the CI sandbox's Python 3.12). Proves our wiring/logic only - NOT behaviour inside a live Ryu runtime."""
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from collections import namedtuple

St = namedtuple("St", "port_no tx_bytes rx_bytes")


def install_stubs():
    def mod(name, **attrs):
        m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
    class EventBase: pass
    class RyuApp:
        def __init__(self, *a, **k): self.sent = []; self.logger = __import__("logging").getLogger("stub")
        def send_event_to_observers(self, ev, state=None): self.sent.append(ev)
    deco = lambda *a, **k: (lambda f: f)  # noqa: E731
    mod("ryu"); mod("ryu.base"); mod("ryu.controller"); mod("ryu.lib"); mod("ryu.ofproto")
    mod("ryu.base.app_manager", RyuApp=RyuApp)
    mod("ryu.controller.event", EventBase=EventBase)
    mod("ryu.controller.ofp_event", EventOFPStateChange=object, EventOFPPortStatsReply=object)
    mod("ryu.controller.handler", MAIN_DISPATCHER="main", DEAD_DISPATCHER="dead", set_ev_cls=deco)
    mod("ryu.lib.hub", spawn=lambda *a, **k: None, sleep=lambda s: None)
    mod("ryu.ofproto.ofproto_v1_3", OFP_VERSION=4)


class TestStubbedRyuApp(unittest.TestCase):
    def test_events_published_only_on_transitions(self):
        install_stubs()
        cfg = {"adapter": {"capacity_bps": {"1:3": 10_000_000}}, "monitored_ports": {"1": [3]}}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "c.json")
            with open(path, "w") as fh: json.dump(cfg, fh)
            os.environ["SDN_CONGESTION_CONFIG"] = path
            sys.modules.pop("congestion_detection.ryu_app", None)
            ra = importlib.import_module("congestion_detection.ryu_app")
            app = ra.CongestionMonitor()
            dp = types.SimpleNamespace(id=1)
            app._state_change(types.SimpleNamespace(datapath=dp, state="main"))
            self.assertIn(1, app.datapaths)
            cum, t = 0, 0.0
            def reply(util, now):
                nonlocal cum
                cum += int(util * 10_000_000 / 8)
                body = [St(3, cum, 0), St(0xfffffffe, 9, 9)]
                import congestion_detection.ryu_app as m
                m.time.monotonic = lambda: now
                app._port_stats_reply(types.SimpleNamespace(msg=types.SimpleNamespace(datapath=dp, body=body)))
            for i in range(15): reply(0.1, float(i))
            for i in range(15, 40): reply(0.95, float(i))
            self.assertEqual(len(app.sent), 1)
            self.assertEqual(app.sent[0].decision.event.value, "CONGESTION_CONFIRMED")
            self.assertEqual(app.sent[0].decision.entity, (1, 3))
            app._state_change(types.SimpleNamespace(datapath=dp, state="dead"))
            self.assertNotIn(1, app.datapaths)


if __name__ == "__main__":
    unittest.main()
