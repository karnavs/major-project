"""Converts raw OpenFlow port counters into validated utilization Samples."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from .detector import Sample

Entity = Tuple[int, int]  # (dpid, port_no)


@dataclass
class _Prev:
    counter: int
    ts: float


class PortStatsAdapter:
    """utilization = (delta_bytes * 8 / dt) / capacity_bps, from tx_bytes (egress, default) or rx_bytes.

    Capacity is NEVER guessed: a port with no configured capacity (and no default) yields an
    invalid sample (UNKNOWN_CAPACITY).  Counter decreases are treated as resets, not wrap-around
    (OpenFlow counters are 64-bit; wrap-around is not realistic at testbed rates).
    """

    def __init__(self, capacity_bps: Optional[Mapping[Entity, float]] = None,
                 default_capacity_bps: Optional[float] = None,
                 max_interval_s: float = 30.0, direction: str = "tx") -> None:
        if direction not in ("tx", "rx"):
            raise ValueError("direction must be 'tx' or 'rx'")
        if max_interval_s <= 0:
            raise ValueError("max_interval_s must be > 0")
        caps = dict(capacity_bps or {})
        for k, v in list(caps.items()) + [("default", default_capacity_bps)]:
            if v is not None and v <= 0:
                raise ValueError(f"capacity for {k} must be > 0 bit/s")
        self.capacity_bps = caps
        self.default_capacity_bps = default_capacity_bps
        self.max_interval_s = max_interval_s
        self.direction = direction
        self._prev: Dict[Entity, _Prev] = {}

    def process(self, dpid: int, port_no: int, tx_bytes: int, rx_bytes: int, timestamp: float) -> Sample:
        ent: Entity = (dpid, port_no)
        counter = tx_bytes if self.direction == "tx" else rx_bytes
        meta = {"counter": counter, "direction": self.direction}
        prev = self._prev.get(ent)
        cap = self.capacity_bps.get(ent, self.default_capacity_bps)

        def invalid(reason: str, store: bool = True) -> Sample:
            if store:
                self._prev[ent] = _Prev(counter, timestamp)
            return Sample(ent, timestamp, None, valid=False, reason=reason, meta=meta)

        if prev is None:
            return invalid("FIRST_SAMPLE")
        dt = timestamp - prev.ts
        if dt <= 0:
            return invalid("NON_POSITIVE_INTERVAL", store=False)   # keep the older reference
        meta["dt_s"] = dt
        if counter < prev.counter:
            return invalid("COUNTER_RESET")
        if dt > self.max_interval_s:
            return invalid("STALE_INTERVAL")
        if cap is None:
            return invalid("UNKNOWN_CAPACITY")
        delta = counter - prev.counter
        rate_bps = delta * 8.0 / dt
        self._prev[ent] = _Prev(counter, timestamp)
        meta.update(delta_bytes=delta, rate_bps=rate_bps, capacity_bps=cap)
        return Sample(ent, timestamp, rate_bps / cap, meta=meta)

    def forget_switch(self, dpid: int) -> None:
        """Call on switch disconnect so the first post-reconnect sample is not diffed against stale counters."""
        for ent in [e for e in self._prev if e[0] == dpid]:
            del self._prev[ent]
