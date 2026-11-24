from congestion_detection import CongestionDetector, DetectorConfig, Sample, State, Event

ENT = ("s1", 2)


def feed(det, values, t0=0.0, dt=1.0, entity=None):
    """Feed values (None => producer-invalid sample). Returns list of Decisions."""
    out = []
    for i, v in enumerate(values):
        ts = t0 + i * dt
        s = Sample(entity or det.entity, ts, v) if v is not None else \
            Sample(entity or det.entity, ts, None, valid=False, reason="MISSING")
        out.append(det.update(s))
    return out


def warmed(cfg=None, level=0.1, n=None):
    """Detector warmed up on constant `level`. Returns (detector, next_t0)."""
    cfg = cfg or DetectorConfig()
    d = CongestionDetector(ENT, cfg)
    n = n or cfg.warmup_samples
    feed(d, [level] * n)
    return d, float(n)


def events(decisions):
    return [x.event for x in decisions if x.event]
