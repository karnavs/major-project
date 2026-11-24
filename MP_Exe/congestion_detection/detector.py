"""Core congestion-state detector. Pure Python, no Ryu/Mininet dependency, deterministic.

Signal semantics: a non-negative value where HIGHER = MORE congested (default unit: link
utilization as a fraction of capacity, 1.0 == 100 %).  See docs/CONGESTION_DETECTOR_SPEC.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Dict, Hashable, List, Mapping, Optional


class State(str, Enum):
    NORMAL = "NORMAL"
    CONGESTION_PENDING = "CONGESTION_PENDING"
    CONGESTED = "CONGESTED"
    RECOVERY_PENDING = "RECOVERY_PENDING"


class Event(str, Enum):
    CONGESTION_CONFIRMED = "CONGESTION_CONFIRMED"
    RECOVERY_CONFIRMED = "RECOVERY_CONFIRMED"


@dataclass(frozen=True)
class DetectorConfig:
    """All parameters. Defaults are INITIAL, UNTUNED values (see spec, parameter table)."""
    alpha: float = 0.1               # EWMA smoothing factor, (0, 1]
    k: float = 3.0                   # variation multiplier, >= 0
    min_variation: float = 0.02      # floor on variation estimate (signal units), > 0
    warmup_samples: int = 10         # valid baseline samples needed before adaptive thresholds
    threshold_min: float = 0.40      # lower clamp on entry threshold (signal units)
    threshold_max: float = 0.85      # upper clamp on entry threshold; also the fixed warm-up threshold
    hysteresis_margin: float = 0.10  # T_exit = T_enter - margin, 0 < margin < threshold_min
    enter_persistence: int = 3       # consecutive valid samples >= T_enter to confirm congestion
    exit_persistence: int = 5        # consecutive valid samples < T_exit to confirm recovery
    max_invalid_streak: int = 5      # consecutive invalid samples after which pending counters reset
    max_valid_value: float = 2.0     # values above this are rejected as implausible

    def __post_init__(self) -> None:
        e: List[str] = []
        if not (0 < self.alpha <= 1): e.append("alpha must be in (0, 1]")
        if self.k < 0: e.append("k must be >= 0")
        if self.min_variation <= 0: e.append("min_variation must be > 0")
        if self.warmup_samples < 1: e.append("warmup_samples must be >= 1")
        if not (0 < self.threshold_min < self.threshold_max): e.append("need 0 < threshold_min < threshold_max")
        if self.threshold_max > self.max_valid_value: e.append("threshold_max must be <= max_valid_value")
        if self.hysteresis_margin <= 0: e.append("hysteresis_margin must be > 0")
        elif self.hysteresis_margin >= self.threshold_min: e.append("hysteresis_margin must be < threshold_min")
        if self.enter_persistence < 1: e.append("enter_persistence must be >= 1")
        if self.exit_persistence < 1: e.append("exit_persistence must be >= 1")
        if self.max_invalid_streak < 1: e.append("max_invalid_streak must be >= 1")
        if e:
            raise ValueError("invalid DetectorConfig: " + "; ".join(e))

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "DetectorConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown detector parameters: {sorted(unknown)}")
        return cls(**dict(d))


@dataclass(frozen=True)
class Sample:
    """One observation for one monitored entity (e.g. (dpid, port_no))."""
    entity: Hashable
    timestamp: float                 # monotonic seconds (strictly increasing per entity)
    value: Optional[float]           # signal value, None if unavailable
    valid: bool = True               # False if the producer already knows the sample is unusable
    reason: str = ""                 # producer's reason when valid is False
    meta: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Decision:
    """Structured result of processing one sample. `event` is set only on confirmed transitions."""
    seq: int
    entity: Hashable
    timestamp: float
    value: Optional[float]
    valid: bool
    reason: str
    prev_state: State
    state: State
    state_changed: bool
    event: Optional[Event]
    baseline: Optional[float]
    variation: Optional[float]
    t_enter: float                   # thresholds USED for this decision (pre-update)
    t_exit: float
    enter_count: int
    exit_count: int
    invalid_streak: int
    warmup_complete: bool
    meta: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        ent = list(self.entity) if isinstance(self.entity, tuple) else self.entity
        return {
            "seq": self.seq, "entity": ent, "ts": self.timestamp, "value": self.value,
            "valid": self.valid, "reason": self.reason, "prev_state": self.prev_state.value,
            "state": self.state.value, "state_changed": self.state_changed,
            "event": self.event.value if self.event else None,
            "baseline": self.baseline, "variation": self.variation,
            "t_enter": self.t_enter, "t_exit": self.t_exit,
            "enter_count": self.enter_count, "exit_count": self.exit_count,
            "invalid_streak": self.invalid_streak, "warmup_complete": self.warmup_complete,
            "meta": dict(self.meta),
        }


class CongestionDetector:
    """State machine for ONE monitored entity. Feed samples with update()."""

    def __init__(self, entity: Hashable, config: Optional[DetectorConfig] = None) -> None:
        self.entity = entity
        self.config = config or DetectorConfig()
        self._state = State.NORMAL
        self._baseline: Optional[float] = None
        self._variation: Optional[float] = None
        self._warm_buf: List[float] = []
        self._enter_count = 0
        self._exit_count = 0
        self._recovery_buf: List[float] = []
        self._invalid_streak = 0
        self._last_ts: Optional[float] = None
        self._seq = 0

    # ---- read-only views -------------------------------------------------
    @property
    def state(self) -> State: return self._state
    @property
    def baseline(self) -> Optional[float]: return self._baseline
    @property
    def variation(self) -> Optional[float]: return self._variation
    @property
    def warmup_complete(self) -> bool: return self._baseline is not None

    def thresholds(self) -> "tuple[float, float]":
        """(T_enter, T_exit). Before warm-up completes T_enter is the fixed threshold_max."""
        c = self.config
        if self._baseline is None:
            t_enter = c.threshold_max
        else:
            raw = self._baseline + c.k * (self._variation or c.min_variation)
            t_enter = min(max(raw, c.threshold_min), c.threshold_max)
        return t_enter, t_enter - c.hysteresis_margin

    # ---- main entry point ------------------------------------------------
    def update(self, sample: Sample) -> Decision:
        self._seq += 1
        prev = self._state
        t_enter, t_exit = self.thresholds()
        bad = self._validate(sample)
        if bad:
            return self._on_invalid(sample, bad, prev, t_enter, t_exit)

        self._invalid_streak = 0
        self._last_ts = sample.timestamp
        x = float(sample.value)  # type: ignore[arg-type]
        c = self.config
        event: Optional[Event] = None
        reason = ""

        if self._state is State.NORMAL:
            if x >= t_enter:
                self._enter_count = 1
                if c.enter_persistence == 1:
                    self._state, event, reason = State.CONGESTED, Event.CONGESTION_CONFIRMED, "PERSISTENCE_MET"
                else:
                    self._state, reason = State.CONGESTION_PENDING, "THRESHOLD_CROSSED"
            else:
                self._learn(x)   # only non-suspect samples may influence the baseline
                reason = "NORMAL_OBSERVATION" if self.warmup_complete else "WARMUP"

        elif self._state is State.CONGESTION_PENDING:
            if x >= t_enter:
                self._enter_count += 1
                if self._enter_count >= c.enter_persistence:
                    self._state, event, reason = State.CONGESTED, Event.CONGESTION_CONFIRMED, "PERSISTENCE_MET"
                else:
                    reason = "PERSISTING"
            else:
                self._state, self._enter_count, reason = State.NORMAL, 0, "SPIKE_REJECTED"

        elif self._state is State.CONGESTED:
            if x < t_exit:
                self._exit_count, self._recovery_buf = 1, [x]
                if c.exit_persistence == 1:
                    event, reason = self._recover(), "RECOVERY_PERSISTENCE_MET"
                else:
                    self._state, reason = State.RECOVERY_PENDING, "BELOW_EXIT_THRESHOLD"
            else:
                reason = "HOLD_CONGESTED" if x >= t_enter else "IN_HYSTERESIS_BAND"

        else:  # RECOVERY_PENDING
            if x < t_exit:
                self._exit_count += 1
                self._recovery_buf.append(x)
                if self._exit_count >= c.exit_persistence:
                    event, reason = self._recover(), "RECOVERY_PERSISTENCE_MET"
                else:
                    reason = "RECOVERING"
            else:
                self._state, self._exit_count, self._recovery_buf = State.CONGESTED, 0, []
                reason = "RECOVERY_INTERRUPTED"

        return self._make(sample, True, reason, prev, event, x, t_enter, t_exit)

    # ---- internals -------------------------------------------------------
    def _validate(self, s: Sample) -> str:
        if not s.valid:
            return s.reason or "INVALID_SAMPLE"
        ts = s.timestamp
        if not isinstance(ts, (int, float)) or not math.isfinite(ts):
            return "INVALID_TIMESTAMP"
        v = s.value
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "NON_NUMERIC_VALUE"
        if v < 0:
            return "NEGATIVE_VALUE"
        if v > self.config.max_valid_value:
            return "VALUE_OUT_OF_RANGE"
        if self._last_ts is not None and ts <= self._last_ts:
            return "OUT_OF_ORDER_OR_DUPLICATE"
        return ""

    def _on_invalid(self, s: Sample, why: str, prev: State, t_enter: float, t_exit: float) -> Decision:
        """Policy: an invalid sample is NEUTRAL evidence (never counts toward congestion or recovery).
        Counters are held; after max_invalid_streak consecutive invalid samples pending states fall back
        to the last CONFIRMED state (fail-safe: invalid data can never confirm either transition)."""
        self._invalid_streak += 1
        reason = why
        if self._invalid_streak >= self.config.max_invalid_streak:
            if self._state is State.CONGESTION_PENDING:
                self._state, self._enter_count = State.NORMAL, 0
                reason = why + "|STALE_PENDING_RESET"
            elif self._state is State.RECOVERY_PENDING:
                self._state, self._exit_count, self._recovery_buf = State.CONGESTED, 0, []
                reason = why + "|STALE_PENDING_RESET"
        v = s.value if isinstance(s.value, (int, float)) and not isinstance(s.value, bool) else None
        return self._make(s, False, reason, prev, None, v, t_enter, t_exit)

    def _learn(self, x: float) -> None:
        c = self.config
        if self._baseline is None:
            self._warm_buf.append(x)
            if len(self._warm_buf) >= c.warmup_samples:
                b = sum(self._warm_buf) / len(self._warm_buf)
                dev = sum(abs(v - b) for v in self._warm_buf) / len(self._warm_buf)
                self._baseline, self._variation = b, max(dev, c.min_variation)
                self._warm_buf = []
        else:
            dev = abs(x - self._baseline)
            self._variation = max(c.alpha * dev + (1 - c.alpha) * (self._variation or c.min_variation),
                                  c.min_variation)
            self._baseline = c.alpha * x + (1 - c.alpha) * self._baseline

    def _recover(self) -> Event:
        buf = self._recovery_buf
        if self._baseline is None:          # never finished warm-up: recovery samples count as warm-up data
            for v in buf:
                self._learn(v)
        else:                               # re-seed to the observed post-congestion regime
            self._baseline = sum(buf) / len(buf)
        self._state, self._enter_count, self._exit_count, self._recovery_buf = State.NORMAL, 0, 0, []
        return Event.RECOVERY_CONFIRMED

    def _make(self, s: Sample, valid: bool, reason: str, prev: State, event: Optional[Event],
              value: Optional[float], t_enter: float, t_exit: float) -> Decision:
        return Decision(
            seq=self._seq, entity=self.entity, timestamp=s.timestamp, value=value, valid=valid,
            reason=reason, prev_state=prev, state=self._state, state_changed=prev is not self._state,
            event=event, baseline=self._baseline, variation=self._variation, t_enter=t_enter,
            t_exit=t_exit, enter_count=self._enter_count, exit_count=self._exit_count,
            invalid_streak=self._invalid_streak, warmup_complete=self._baseline is not None,
            meta=dict(s.meta))


class DetectorManager:
    """Independent CongestionDetector per entity (never shares state between links/ports)."""

    def __init__(self, config: Optional[DetectorConfig] = None,
                 per_entity_config: Optional[Mapping[Hashable, DetectorConfig]] = None) -> None:
        self.config = config or DetectorConfig()
        self._overrides = dict(per_entity_config or {})
        self._detectors: Dict[Hashable, CongestionDetector] = {}

    def detector(self, entity: Hashable) -> CongestionDetector:
        d = self._detectors.get(entity)
        if d is None:
            d = self._detectors[entity] = CongestionDetector(entity, self._overrides.get(entity, self.config))
        return d

    def update(self, sample: Sample) -> Decision:
        return self.detector(sample.entity).update(sample)

    def states(self) -> Dict[Hashable, State]:
        return {e: d.state for e, d in self._detectors.items()}

    def reset(self, entity: Hashable) -> None:
        self._detectors.pop(entity, None)
