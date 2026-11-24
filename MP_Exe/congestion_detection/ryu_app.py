"""OPTIONAL stand-alone Ryu app. Use this ONLY if your controller does not already poll port stats;
otherwise call CongestionService.ingest_port_stats() from your existing handler (no duplicate polling).

Run (UNTESTED against a live Ryu in this repo's CI; see docs/PROJECT_CONTEXT.md):
    SDN_CONGESTION_CONFIG=config/congestion_detector.json ryu-manager congestion_detection/ryu_app.py <your_routing_app>

Publishes EventCongestionChange to observers ONLY on CONGESTION_CONFIRMED / RECOVERY_CONFIRMED.
It never installs flows and never selects routes.
"""
import json
import os
import time

from ryu.base import app_manager
from ryu.controller import event, ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

from congestion_detection.controller_bridge import build_service


class EventCongestionChange(event.EventBase):
    """`decision` is a congestion_detection.Decision; decision.event tells congestion vs recovery."""
    def __init__(self, decision):
        super().__init__()
        self.decision = decision


class CongestionMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _EVENTS = [EventCongestionChange]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        path = os.environ.get("SDN_CONGESTION_CONFIG", "config/congestion_detector.json")
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.poll_interval = float(cfg.get("poll_interval_s", 1.0))
        self.service = build_service(cfg, on_event=self._publish, logger=self.logger)
        self.datapaths = {}
        self._thread = hub.spawn(self._poll_loop)

    def _publish(self, decision):
        self.send_event_to_observers(EventCongestionChange(decision))

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        elif dp.id in self.datapaths:
            del self.datapaths[dp.id]
            self.service.on_switch_disconnect(dp.id)

    def _poll_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
            hub.sleep(self.poll_interval)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        self.service.ingest_port_stats(ev.msg.datapath.id, ev.msg.body, time.monotonic())
