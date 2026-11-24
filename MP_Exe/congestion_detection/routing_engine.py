"""Core graph topology and adaptive routing engine for SDN.
Dependency-free (stdlib only) so it can be tested and simulated anywhere without Ryu.
"""
from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class LinkInfo:
    src_dpid: int
    src_port: int
    dst_dpid: int
    dst_port: int
    capacity_bps: float = 10_000_000.0
    default_weight: float = 1.0
    current_weight: float = 1.0
    is_congested: bool = False


@dataclass
class HostLocation:
    mac: str
    dpid: int
    port: int
    ip: Optional[str] = None


@dataclass
class ActiveFlow:
    flow_id: Tuple[str, str]  # (eth_src, eth_dst)
    path_dpids: List[int]
    hop_ports: List[Tuple[int, int]]  # [(dpid, out_port), ...]
    installed_at: float
    last_updated: float


class TopologyGraph:
    """Directed multi-switch graph with dynamic link weights and Dijkstra routing."""

    def __init__(self, congestion_penalty: float = 1000.0, logger: Optional[logging.Logger] = None) -> None:
        self.congestion_penalty = float(congestion_penalty)
        self.log = logger or logging.getLogger("routing.topology")
        # dpid -> set of neighbor dpids
        self.adj: Dict[int, Dict[int, LinkInfo]] = {}
        # (src_dpid, src_port) -> LinkInfo
        self.port_to_link: Dict[Tuple[int, int], LinkInfo] = {}

    def add_switch(self, dpid: int) -> None:
        if dpid not in self.adj:
            self.adj[dpid] = {}

    def add_link(self, src_dpid: int, src_port: int,
                 dst_dpid: int, dst_port: int,
                 capacity_bps: float = 10_000_000.0,
                 weight: float = 1.0,
                 bidirectional: bool = True) -> None:
        """Add directed link src -> dst. If bidirectional=True, also adds dst -> src."""
        self.add_switch(src_dpid)
        self.add_switch(dst_dpid)

        link_fwd = LinkInfo(
            src_dpid=src_dpid, src_port=src_port,
            dst_dpid=dst_dpid, dst_port=dst_port,
            capacity_bps=capacity_bps,
            default_weight=weight,
            current_weight=weight,
            is_congested=False
        )
        self.adj[src_dpid][dst_dpid] = link_fwd
        self.port_to_link[(src_dpid, src_port)] = link_fwd

        if bidirectional:
            link_rev = LinkInfo(
                src_dpid=dst_dpid, src_port=dst_port,
                dst_dpid=src_dpid, dst_port=src_port,
                capacity_bps=capacity_bps,
                default_weight=weight,
                current_weight=weight,
                is_congested=False
            )
            self.adj[dst_dpid][src_dpid] = link_rev
            self.port_to_link[(dst_dpid, dst_port)] = link_rev

    def mark_congested(self, dpid: int, port: int) -> Optional[LinkInfo]:
        """Mark a link originating at (dpid, port) as congested and apply penalty weight."""
        link = self.port_to_link.get((dpid, port))
        if link is None:
            self.log.debug("Unknown link for congested entity (%d, %d)", dpid, port)
            return None

        if not link.is_congested:
            link.is_congested = True
            link.current_weight = link.default_weight + self.congestion_penalty
            self.log.info("Congestion penalised link (%d:%d -> %d:%d), weight: %.1f -> %.1f",
                          link.src_dpid, link.src_port, link.dst_dpid, link.dst_port,
                          link.default_weight, link.current_weight)
        return link

    def mark_recovered(self, dpid: int, port: int) -> Optional[LinkInfo]:
        """Restore normal weight on link originating at (dpid, port)."""
        link = self.port_to_link.get((dpid, port))
        if link is None:
            return None

        if link.is_congested:
            link.is_congested = False
            link.current_weight = link.default_weight
            self.log.info("Congestion cleared on link (%d:%d -> %d:%d), weight restored to %.1f",
                          link.src_dpid, link.src_port, link.dst_dpid, link.dst_port,
                          link.default_weight)
        return link

    def find_shortest_path(self, src_dpid: int, dst_dpid: int) -> Optional[Tuple[List[int], List[Tuple[int, int]]]]:
        """Find lowest-cost path from src_dpid to dst_dpid using Dijkstra's algorithm.

        Returns (path_dpids, hop_ports) where:
          - path_dpids is [dpid_1, dpid_2, ..., dpid_k]
          - hop_ports is [(dpid_1, out_port_1), (dpid_2, out_port_2), ...]
        Returns None if no path exists.
        """
        if src_dpid not in self.adj or dst_dpid not in self.adj:
            return None

        if src_dpid == dst_dpid:
            return [src_dpid], []

        # dist[u] = (cost, hops)
        distances: Dict[int, float] = {u: float("inf") for u in self.adj}
        distances[src_dpid] = 0.0
        previous: Dict[int, Optional[int]] = {u: None for u in self.adj}
        prev_link: Dict[int, Optional[LinkInfo]] = {u: None for u in self.adj}

        # Priority queue entries: (cost, hop_count, dpid)
        pq: List[Tuple[float, int, int]] = [(0.0, 0, src_dpid)]

        while pq:
            curr_dist, hops, u = heapq.heappop(pq)
            if curr_dist > distances[u]:
                continue
            if u == dst_dpid:
                break

            for v, link in self.adj[u].items():
                alt = curr_dist + link.current_weight
                if alt < distances[v]:
                    distances[v] = alt
                    previous[v] = u
                    prev_link[v] = link
                    heapq.heappush(pq, (alt, hops + 1, v))

        if distances[dst_dpid] == float("inf"):
            return None

        # Reconstruct path
        path_dpids: List[int] = []
        hop_ports: List[Tuple[int, int]] = []
        curr = dst_dpid
        while curr is not None:
            path_dpids.append(curr)
            curr = previous[curr]
        path_dpids.reverse()

        for i in range(len(path_dpids) - 1):
            u = path_dpids[i]
            v = path_dpids[i + 1]
            link = self.adj[u][v]
            hop_ports.append((u, link.src_port))

        return path_dpids, hop_ports

    def find_all_paths(self, src_dpid: int, dst_dpid: int, max_hops: int = 8) -> List[Tuple[List[int], List[Tuple[int, int]], float]]:
        """Find all simple (loop-free) paths from src_dpid to dst_dpid.

        Returns list of (path_dpids, hop_ports, total_weight) sorted by total_weight.
        """
        if src_dpid not in self.adj or dst_dpid not in self.adj:
            return []
        if src_dpid == dst_dpid:
            return [([src_dpid], [], 0.0)]

        results: List[Tuple[List[int], List[Tuple[int, int]], float]] = []

        def dfs(u: int, visited: Set[int], path: List[int], hops: List[Tuple[int, int]], cost: float):
            if len(path) > max_hops:
                return
            if u == dst_dpid:
                results.append((list(path), list(hops), cost))
                return
            for v, link in self.adj[u].items():
                if v not in visited:
                    visited.add(v)
                    path.append(v)
                    hops.append((u, link.src_port))
                    dfs(v, visited, path, hops, cost + link.current_weight)
                    hops.pop()
                    path.pop()
                    visited.remove(v)

        dfs(src_dpid, {src_dpid}, [src_dpid], [], 0.0)
        results.sort(key=lambda item: item[2])
        return results


class AdaptiveRoutingEngine:
    """Coordinates topology, host locations, Dijkstra routing, and congestion rerouting."""

    def __init__(self, topology: Optional[TopologyGraph] = None,
                 congestion_penalty: float = 1000.0,
                 logger: Optional[logging.Logger] = None) -> None:
        self.topology = topology or TopologyGraph(congestion_penalty=congestion_penalty)
        self.log = logger or logging.getLogger("routing.engine")
        self.hosts: Dict[str, HostLocation] = {}  # mac -> HostLocation
        self.active_flows: Dict[Tuple[str, str], ActiveFlow] = {}  # (src_mac, dst_mac) -> ActiveFlow

    def register_host(self, mac: str, dpid: int, port: int, ip: Optional[str] = None) -> HostLocation:
        """Record or update the attached switch port for a host MAC address."""
        loc = HostLocation(mac=mac, dpid=dpid, port=port, ip=ip)
        self.hosts[mac] = loc
        self.log.debug("Learned host %s at switch %d port %d", mac, dpid, port)
        return loc

    def compute_route(self, src_mac: str, dst_mac: str, now: float) -> Optional[ActiveFlow]:
        """Calculate route between known hosts. Returns ActiveFlow with per-switch out_ports."""
        src_loc = self.hosts.get(src_mac)
        dst_loc = self.hosts.get(dst_mac)
        if not src_loc or not dst_loc:
            return None

        if src_loc.dpid == dst_loc.dpid:
            # Same switch: direct output to destination host port
            flow = ActiveFlow(
                flow_id=(src_mac, dst_mac),
                path_dpids=[src_loc.dpid],
                hop_ports=[(src_loc.dpid, dst_loc.port)],
                installed_at=now,
                last_updated=now
            )
            self.active_flows[(src_mac, dst_mac)] = flow
            return flow

        res = self.topology.find_shortest_path(src_loc.dpid, dst_loc.dpid)
        if res is None:
            self.log.warning("No path found between %s (dpid %d) and %s (dpid %d)",
                             src_mac, src_loc.dpid, dst_mac, dst_loc.dpid)
            return None

        path_dpids, inter_switch_hops = res
        # Append the final hop: from destination switch to destination host port
        all_hops = list(inter_switch_hops)
        all_hops.append((dst_loc.dpid, dst_loc.port))

        flow = ActiveFlow(
            flow_id=(src_mac, dst_mac),
            path_dpids=path_dpids,
            hop_ports=all_hops,
            installed_at=now,
            last_updated=now
        )
        self.active_flows[(src_mac, dst_mac)] = flow
        return flow

    def compute_route_balanced(self, src_mac: str, dst_mac: str, now: float) -> Optional[ActiveFlow]:
        """Compute route with multi-path load distribution across uncongested candidate paths.

        If multiple candidate paths exist between ingress and egress switches, selects the
        candidate path with the fewest active flows (least-loaded path allocation).
        """
        src_loc = self.hosts.get(src_mac)
        dst_loc = self.hosts.get(dst_mac)
        if not src_loc or not dst_loc:
            return None

        if src_loc.dpid == dst_loc.dpid:
            return self.compute_route(src_mac, dst_mac, now)

        candidate_paths = self.topology.find_all_paths(src_loc.dpid, dst_loc.dpid)
        if not candidate_paths:
            return None

        # Filter out paths that currently contain congested links (cost >= congestion_penalty)
        uncongested = [p for p in candidate_paths if p[2] < self.topology.congestion_penalty]
        pool = uncongested if uncongested else candidate_paths

        # Count active flows currently assigned to each path tuple
        path_loads: Dict[Tuple[int, ...], int] = {tuple(p[0]): 0 for p in pool}
        for active in self.active_flows.values():
            tpl = tuple(active.path_dpids)
            if tpl in path_loads:
                path_loads[tpl] += 1

        # Select the path with minimum current flow load (ties broken by lowest base cost)
        best_choice = min(pool, key=lambda p: (path_loads[tuple(p[0])], p[2]))
        selected_dpids, inter_switch_hops, _ = best_choice

        all_hops = list(inter_switch_hops)
        all_hops.append((dst_loc.dpid, dst_loc.port))

        flow = ActiveFlow(
            flow_id=(src_mac, dst_mac),
            path_dpids=selected_dpids,
            hop_ports=all_hops,
            installed_at=now,
            last_updated=now
        )
        self.active_flows[(src_mac, dst_mac)] = flow
        self.log.info("[LOAD DISTRIBUTION] Assigned flow %s -> %s to path %s (active load on path: %d flows)",
                      src_mac, dst_mac, selected_dpids, path_loads[tuple(selected_dpids)])
        return flow

    def on_congestion_confirmed(self, dpid: int, port: int, now: float) -> List[Tuple[ActiveFlow, List[int]]]:
        """Apply congestion penalty and reroute any flows traversing the congested link.

        Returns list of tuples: (updated_flow, old_path_dpids).
        """
        link = self.topology.mark_congested(dpid, port)
        if link is None:
            return []

        congested_edge = (link.src_dpid, link.dst_dpid)
        rerouted: List[Tuple[ActiveFlow, List[int]]] = []

        for flow_id, flow in list(self.active_flows.items()):
            src_mac, dst_mac = flow_id
            # Check if flow traverses this congested edge
            edge_in_path = False
            for i in range(len(flow.path_dpids) - 1):
                if (flow.path_dpids[i], flow.path_dpids[i + 1]) == congested_edge:
                    edge_in_path = True
                    break

            if edge_in_path:
                old_path = list(flow.path_dpids)
                new_flow = self.compute_route(src_mac, dst_mac, now)
                if new_flow and new_flow.path_dpids != old_path:
                    self.log.info("[REROUTE] Flow %s -> %s rerouted from %s to %s due to congestion on link %s",
                                  src_mac, dst_mac, old_path, new_flow.path_dpids, congested_edge)
                    rerouted.append((new_flow, old_path))
                elif new_flow:
                    self.log.warning("No alternative path found for flow %s; staying on path %s",
                                     flow_id, old_path)

        return rerouted

    def on_recovery_confirmed(self, dpid: int, port: int, now: float,
                              auto_revert: bool = True) -> List[Tuple[ActiveFlow, List[int]]]:
        """Clear congestion penalty and optionally recompute optimal paths.

        Returns list of rerouted/restored flows: (updated_flow, old_path_dpids).
        """
        link = self.topology.mark_recovered(dpid, port)
        if link is None or not auto_revert:
            return []

        restored: List[Tuple[ActiveFlow, List[int]]] = []
        for flow_id, flow in list(self.active_flows.items()):
            src_mac, dst_mac = flow_id
            old_path = list(flow.path_dpids)
            new_flow = self.compute_route(src_mac, dst_mac, now)
            if new_flow and new_flow.path_dpids != old_path:
                self.log.info("[RESTORE] Flow %s -> %s restored from %s to %s after recovery on (%d, %d)",
                              src_mac, dst_mac, old_path, new_flow.path_dpids, dpid, port)
                restored.append((new_flow, old_path))

        return restored
