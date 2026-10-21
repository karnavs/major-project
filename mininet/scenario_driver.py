#!/usr/bin/env python3
"""Runs phased iperf3 UDP load h1->h3 and records ground-truth phases. DRAFT - NOT YET RUN.
Prereqs: Ryu running with your routing app + CongestionMonitor (or the bridge) logging to a JSONL file;
`iperf3` installed. Run as root:  sudo python3 mininet/scenario_driver.py sustained
Phase 'congested' truth = offered load >= 9 Mbit/s on a 10 Mbit/s bottleneck (declared before the run).
Phase timestamps use time.monotonic() so they can be compared with the controller's monotonic timestamps
(same host, same boot). iperf3 start-up adds ~1 s of inaccuracy to detection-delay figures."""
import json
import sys
import time

from mininet.log import setLogLevel
from mininet.net import Mininet

from bottleneck_topo import CONTROLLER, BottleneckTopo

# (duration_s, offered_mbps)
SCENARIOS = {
    "baseline":  [(60, 1)],
    "burst":     [(30, 1), (2, 9.5), (30, 1)],
    "sustained": [(30, 1), (40, 9.5), (40, 1)],
    "no_trigger": [(30, 1), (3, 9.5), (10, 1), (3, 9.5), (10, 1), (3, 9.5), (30, 1)],
    "changing":  [(30, 1), (20, 5), (20, 9.5), (20, 3), (20, 9.5), (40, 1)],
}
CONGESTED_MBPS = 9.0


def main(name, out="phases.json"):
    setLogLevel("info")
    net = Mininet(topo=BottleneckTopo(), build=False, **CONTROLLER)
    net.build(); net.start()
    h1, h3 = net.get("h1"), net.get("h3")
    net.pingAll()
    h3.cmd("iperf3 -s -D")
    time.sleep(1)
    phases = []
    for dur, mbps in SCENARIOS[name]:
        start = time.monotonic()
        h1.cmd(f"iperf3 -u -b {mbps}M -t {dur} -c {h3.IP()} > /dev/null")
        phases.append({"start": start, "end": time.monotonic(), "mbps": mbps,
                       "congested": mbps >= CONGESTED_MBPS})
    with open(out, "w") as fh:
        json.dump({"scenario": name, "phases": phases}, fh, indent=2)
    h3.cmd("pkill iperf3")
    net.stop()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sustained")
