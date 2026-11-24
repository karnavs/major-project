"""Glue between controller-collected port statistics and the detector. No Ryu import here, so it can
be dropped into an EXISTING stats handler and unit-tested without a controller.

    service = build_service(cfg_dict, on_event=my_routing_callback)
    ...inside your existing EventOFPPortStatsReply handler...
    service.ingest_port_stats(ev.msg.datapath.id, ev.msg.body, time.monotonic())
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .detector import Decision, DetectorConfig, DetectorManager
from .stats_adapter import PortStatsAdapter

OFPP_MAX = 0xffffff00   # OpenFlow 1.3 reserved port numbers start above this (LOCAL, CONTROLLER, ...)
EventCallback = Callable[[Decision], None]


class CongestionService:
    def __init__(self, manager: DetectorManager, adapter: PortStatsAdapter,
                 on_event: Optional[EventCallback] = None,
                 monitored_ports: Optional[Mapping[int, Iterable[int]]] = None,
                 decision_log_path: Optional[str] = None, log_all_samples: bool = False,
                 logger: Optional[logging.Logger] = None) -> None:
        self.manager, self.adapter, self.on_event = manager, adapter, on_event
        self.monitored: Optional[Dict[int, Set[int]]] = (
            {int(d): set(p) for d, p in monitored_ports.items()} if monitored_ports else None)
        self.decision_log_path, self.log_all_samples = decision_log_path, log_all_samples
        self.log = logger or logging.getLogger("congestion")
        self._last_invalid: Dict[Tuple[int, int], str] = {}

    def ingest_port_stats(self, dpid: int, port_stats: Iterable[Any],
                          timestamp: Optional[float] = None) -> List[Decision]:
        """One OFPPortStatsReply body for one switch. `timestamp` must be monotonic seconds taken when
        the reply was RECEIVED (not when requested)."""
        ts = time.monotonic() if timestamp is None else timestamp
        out: List[Decision] = []
        for st in port_stats:
            port = st.port_no
            if port >= OFPP_MAX:
                continue
            if self.monitored is not None and port not in self.monitored.get(dpid, ()):
                continue
            sample = self.adapter.process(dpid, port, st.tx_bytes, st.rx_bytes, ts)
            d = self.manager.update(sample)
            out.append(d)
            self._log(d)
            if d.event is not None and self.on_event is not None:
                try:
                    self.on_event(d)
                except Exception:   # a faulty consumer must never break statistics processing
                    self.log.exception("congestion event consumer failed for %s", d.entity)
        return out

    def on_switch_disconnect(self, dpid: int) -> None:
        self.adapter.forget_switch(dpid)
        for ent in [e for e in self.manager.states() if e[0] == dpid]:
            self.manager.reset(ent)
            self._last_invalid.pop(ent, None)

    # ---- logging ---------------------------------------------------------
    def _log(self, d: Decision) -> None:
        ent = tuple(d.entity)
        write = self.log_all_samples or d.state_changed or d.event is not None
        if not d.valid:
            if self._last_invalid.get(ent) != d.reason:      # de-duplicate repeated invalid reasons
                self._last_invalid[ent] = d.reason
                write = True
                self.log.warning("invalid sample %s: %s", ent, d.reason)
        else:
            self._last_invalid.pop(ent, None)
        if d.event is not None:
            self.log.info("%s on %s at %.3f (value=%.3f t_enter=%.3f t_exit=%.3f)", d.event.value, ent,
                          d.timestamp, d.value, d.t_enter, d.t_exit)
        if write and self.decision_log_path:
            with open(self.decision_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(d.to_dict()) + "\n")


def build_service(cfg: Mapping[str, Any], on_event: Optional[EventCallback] = None,
                  logger: Optional[logging.Logger] = None) -> CongestionService:
    """Build from a config dict (see config/congestion_detector.example.json)."""
    det_cfg = DetectorConfig.from_dict(cfg.get("detector", {}))
    ad = cfg.get("adapter", {})
    caps = {}
    for key, bps in ad.get("capacity_bps", {}).items():
        dpid, port = key.split(":")
        caps[(int(dpid), int(port))] = float(bps)
    adapter = PortStatsAdapter(caps, ad.get("default_capacity_bps"),
                               ad.get("max_interval_s", 30.0), ad.get("direction", "tx"))
    mon = {int(k): v for k, v in cfg.get("monitored_ports", {}).items()} or None
    return CongestionService(DetectorManager(det_cfg), adapter, on_event, mon,
                             cfg.get("decision_log_path"), cfg.get("log_all_samples", False), logger)
