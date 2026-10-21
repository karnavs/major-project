"""Detector-level metrics against declared ground truth. Works on decision dicts (Decision.to_dict()
or JSONL lines).  Ground-truth intervals are half-open [start_ts, end_ts): congested from the first
congested sample (start) up to, not including, the first non-congested sample (end)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

Interval = Tuple[float, float]


def evaluate(records: Sequence[Dict[str, Any]], congested: Sequence[Interval]) -> Dict[str, Any]:
    cong_ev = [r["ts"] for r in records if r.get("event") == "CONGESTION_CONFIRMED"]
    rec_ev = [r["ts"] for r in records if r.get("event") == "RECOVERY_CONFIRMED"]
    det_delays: List[Optional[float]] = []
    rec_delays: List[Optional[float]] = []
    in_interval = set()
    for i, (s, e) in enumerate(congested):
        hits = [t for t in cong_ev if s <= t < e]
        in_interval.update(hits)
        det_delays.append(hits[0] - s if hits else None)
        nxt = congested[i + 1][0] if i + 1 < len(congested) else float("inf")
        rhits = [t for t in rec_ev if e <= t < nxt]
        rec_delays.append(rhits[0] - e if rhits else None)
    false_triggers = sum(1 for t in cong_ev if not any(s <= t < e for s, e in congested))
    extra = sum(max(0, sum(1 for t in cong_ev if s <= t < e) - 1) for s, e in congested)
    return {
        "congestion_events": len(cong_ev), "recovery_events": len(rec_ev),
        "detection_delays_s": det_delays, "missed_detections": sum(d is None for d in det_delays),
        "false_triggers": false_triggers, "recovery_delays_s": rec_delays,
        "missed_recoveries": sum(d is None for d in rec_delays),
        "flap_extra_congestion_events": extra,
        "state_transitions": sum(1 for r in records if r.get("state_changed")),
        "invalid_samples": sum(1 for r in records if not r.get("valid", True)),
        "samples": len(records),
    }
