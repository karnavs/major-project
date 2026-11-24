#!/usr/bin/env python3
"""Minimal bottleneck topology for detector testing. DRAFT - NOT YET RUN in this repo's history.
   h1,h2 -- s1 ==10 Mbit/s== s2 -- h3,h4
Mininet numbers ports in link-creation order, so s1-eth3 (port 3) faces s2 and carries h1->h3 traffic.
Monitor that egress port: capacity_bps key "1:3" = 10000000 (dpid 1 assumes Mininet's default dpid for s1).
Adapt to YOUR team's topology; this file exists only to give a controlled single-bottleneck test."""
from mininet.link import TCLink
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo


class BottleneckTopo(Topo):
    def build(self, bw=10):
        s1, s2 = self.addSwitch("s1"), self.addSwitch("s2")
        for h, s in (("h1", s1), ("h2", s1), ("h3", s2), ("h4", s2)):
            self.addLink(self.addHost(h), s, cls=TCLink, bw=100)
        self.addLink(s1, s2, cls=TCLink, bw=bw)      # monitored bottleneck: s1 port 3


topos = {"bottleneck": BottleneckTopo}
CONTROLLER = dict(controller=RemoteController, ip="127.0.0.1", port=6633, switch=OVSSwitch)
