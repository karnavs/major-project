# Integration contract

## What the module RECEIVES
OpenFlow 1.3 `OFPPortStatsReply` bodies: per port `port_no`, `tx_bytes`, `rx_bytes`, plus a **monotonic receive
timestamp** (`time.monotonic()` taken in the reply handler) and the switch `dpid`. Reserved ports (≥ 0xffffff00, e.g.
LOCAL) are skipped. Link capacity per monitored port comes from config (bit/s).

## What it EMITS
A `Decision` (JSON form below) per processed sample. The router should act **only** on `decision.event`:
`CONGESTION_CONFIRMED` (port is congested; `decision.entity == (dpid, port_no)`) and `RECOVERY_CONFIRMED`
(port recovered). Everything else is observability. **The detector never touches flow tables.** Whether/when to restore
the original route after `RECOVERY_CONFIRMED` is the routing module's policy.
```json
{"seq":28,"entity":[1,3],"ts":120.4,"value":0.95,"valid":true,"reason":"PERSISTENCE_MET",
 "prev_state":"CONGESTION_PENDING","state":"CONGESTED","state_changed":true,"event":"CONGESTION_CONFIRMED",
 "baseline":0.1,"variation":0.02,"t_enter":0.4,"t_exit":0.3,"enter_count":3,"exit_count":0,
 "invalid_streak":0,"warmup_complete":true,"meta":{"rate_bps":9500000.0,"capacity_bps":10000000.0,"dt_s":1.0}}
```
(The example is illustrative formatting, not a captured run.)

## Option A (recommended): hook into your EXISTING stats handler — no second polling loop
```python
# in your existing controller app
import time, json
from congestion_detection import build_service

def __init__(...):
    cfg = json.load(open("config/congestion_detector.json"))
    self.congestion = build_service(cfg, on_event=self._on_congestion_event, logger=self.logger)

@set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
def _port_stats_reply_handler(self, ev):
    ...                                   # your existing code unchanged
    self.congestion.ingest_port_stats(ev.msg.datapath.id, ev.msg.body, time.monotonic())

def _on_congestion_event(self, decision):          # called synchronously, keep it fast
    dpid, port = decision.entity
    if decision.event.value == "CONGESTION_CONFIRMED": ...   # hand to routing module
    else: ...                                                 # RECOVERY_CONFIRMED
# on datapath DEAD_DISPATCHER:  self.congestion.on_switch_disconnect(dp.id)
```
Cost measured: ~9 µs/sample (synthetic benchmark), no blocking I/O except an optional JSONL append on transitions.

## Option B: stand-alone app `congestion_detection/ryu_app.py`
Polls port stats itself and publishes `EventCongestionChange`. Use **only** if no existing poller. A consumer app declares
`_CONTEXTS`/`required_apps` and `@set_ev_cls(EventCongestionChange)`. **Status: exercised only against stubbed Ryu modules
(tests/test_ryu_app_stubbed.py); never run in a live Ryu — verify before relying on it.**

## Files touched in the existing project (minimal)
New: `congestion_detection/`, `config/congestion_detector.json` (copy the example, set real dpid:port capacities), `tests/`.
Existing controller: one import, one constructor line, one line in the stats-reply handler, one callback. Revert by deleting
those lines — the package has no side effects.
