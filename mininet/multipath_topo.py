#!/usr/bin/env python3
"""Diamond Multi-Path Topology for SDN Congestion-Aware Rerouting and Load Distribution.

Topology Diagram:
                +---------------+
                |   Switch s3   |
           +--->|   (Bypass)    |---+
   (10M)   |    +---------------+   | (10M)
  port 4   |                        | port 2
+----------+----+              +----+----------+
|   Switch s1   |===(10 Mbps)==|   Switch s2   |
|   (Ingress)   |  (Bottleneck)|   (Egress)    |
+---------------+    port 3    +---------------+
  | port 1 | port 2              | port 1 | port 2
  |        |                     |        |
[h1]      [h2]                  [h3]     [h4]

Traffic path under normal conditions:
  h1 -> s1 -> s2 -> h3 (Direct primary path)
Traffic path during congestion on s1:port3:
  h1 -> s1 -> s3 -> s2 -> h3 (Dynamically rerouted bypass path)
"""
from mininet.link import TCLink
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo


class DiamondMultipathTopo(Topo):
    """Diamond topology providing a primary bottleneck link and an alternate bypass link."""

    def build(self, primary_bw=10, bypass_bw=10, host_bw=100, delay="2ms"):
        # Switches
        s1 = self.addSwitch("s1", dpid="0000000000000001")
        s2 = self.addSwitch("s2", dpid="0000000000000002")
        s3 = self.addSwitch("s3", dpid="0000000000000003")

        # Ingress Hosts
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

        # Egress Hosts
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        h4 = self.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")

        # Host links (ports 1 & 2 on s1 and s2)
        # Link creation order defines port numbers in Mininet
        self.addLink(h1, s1, cls=TCLink, bw=host_bw, port2=1)
        self.addLink(h2, s1, cls=TCLink, bw=host_bw, port2=2)

        self.addLink(h3, s2, cls=TCLink, bw=host_bw, port2=1)
        self.addLink(h4, s2, cls=TCLink, bw=host_bw, port2=2)

        # Primary Bottleneck Link: s1 port 3 <---> s2 port 3
        self.addLink(s1, s2, cls=TCLink, bw=primary_bw, delay=delay, port1=3, port2=3)

        # Bypass Route: s1 port 4 <---> s3 port 1; s3 port 2 <---> s2 port 4
        self.addLink(s1, s3, cls=TCLink, bw=bypass_bw, delay=delay, port1=4, port2=1)
        self.addLink(s3, s2, cls=TCLink, bw=bypass_bw, delay=delay, port1=2, port2=4)


topos = {"diamond": DiamondMultipathTopo}
CONTROLLER = dict(controller=RemoteController, ip="127.0.0.1", port=6633, switch=OVSSwitch)


if __name__ == "__main__":
    from mininet.net import Mininet
    from mininet.log import setLogLevel
    from mininet.cli import CLI

    setLogLevel("info")
    net = Mininet(topo=DiamondMultipathTopo(), link=TCLink, **CONTROLLER)
    net.start()
    print("\nDiamond Multipath Topology Started. Type 'exit' to terminate CLI.")
    CLI(net)
    net.stop()
