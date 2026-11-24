#!/usr/bin/env python3
"""Compute detector metrics from a decision JSONL log + the phase file written by mininet/scenario_driver.py.
    python3 scripts/analyze_run.py --decisions decisions.jsonl --phases phases.json --entity 1 3
Timestamps in both files must come from the same monotonic clock (same host, time.monotonic())."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from congestion_detection.evaluation import evaluate  # noqa: E402


def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--phases", required=True)
    ap.add_argument("--entity", nargs=2, type=int, required=True, metavar=("DPID", "PORT"))
    a = ap.parse_args()
    with open(a.decisions) as fh:
        recs = [r for r in map(json.loads, fh) if r["entity"] == list(a.entity)]
    with open(a.phases) as fh:
        phases = json.load(fh)["phases"]
    truth = merge([(p["start"], p["end"]) for p in phases if p["congested"]])
    print(json.dumps(evaluate(recs, truth), indent=2))


if __name__ == "__main__":
    main()
