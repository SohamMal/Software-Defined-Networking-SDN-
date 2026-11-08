#!/usr/bin/env python3
"""Part 2: link-metric-based path selection (metric = link delay), Ryu / OpenFlow 1.3.

What it does
  * Switch-level topology: learned with Ryu's LLDP discovery (--observe-links).
    Every inter-switch link is stored as (src_dpid, dst_dpid) -> (src_port, dst_port).
  * Host attachment points: learned from ARP/IPv4 Packet-Ins that arrive on a port
    that is NOT an inter-switch port (an "edge" port).
  * Link cost: the link's configured one-way delay in ms, read from the same JSON
    file the topology uses (lower delay = lower cost).
  * Path: Dijkstra over the switch graph. For the first IPv4 packet of a host pair
    the controller installs (ipv4_src, ipv4_dst) -> out_port rules on every switch
    of the path, for both directions, and logs every candidate path with its cost.
  * ARP: the ring has a loop, so ARP is never flooded through the switches. The
    controller answers ARP requests itself when it knows the target (proxy ARP);
    otherwise it sends the request only out of edge (host) ports.
  * IPv6 is dropped (priority 100), as in Part 1, so it does not create Packet-Ins.

Assumptions: hosts do not move (the first learned location is kept), switch dpid N
is named sN (Mininet default), link delays are symmetric.

Run (Terminal 1, Ryu venv):
    source ~/ryu-env/bin/activate
    ryu-manager --ofp-tcp-listen-port 6633 --observe-links p2_controller.py 2>&1 | tee p2_default_ryu.log
  changed-property test (must match the topology file):
    LINKS_FILE=links_changed.json ryu-manager --ofp-tcp-listen-port 6633 --observe-links p2_controller.py 2>&1 | tee p2_changed_ryu.log
Wait for "topology complete: 4 switches, 8 directed links" before sending traffic.

Part 3 hook: link_costs() returns the cost map used for every new route. A subclass
can override it to add a congestion penalty on top of the static delay.
"""

import heapq
import json
import os
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import arp, ether_types, ethernet, ipv4, packet
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event as topo_event

HERE = os.path.dirname(os.path.abspath(__file__))
LINKS_FILE = os.environ.get("LINKS_FILE", "links_default.json")

PATH_PRIORITY = 10
IPV6_DROP_PRIORITY = 100
IDLE_TIMEOUT = 30          # path rules expire after 30 s idle, so a later flow is re-routed
UNKNOWN_LINK_COST = 1000.0  # for a discovered link that is missing from the JSON file
EXPECTED_SWITCHES = 4
EXPECTED_DIRECTED_LINKS = 8


def sw(dpid):
    return "s%d" % dpid


def load_link_delays(name):
    path = name if os.path.isabs(name) else os.path.join(HERE, name)
    with open(path) as f:
        links = json.load(f)["links"]
    delays = {}
    for l in links:
        a, b = int(l["a"].lstrip("s")), int(l["b"].lstrip("s"))
        delays[frozenset((a, b))] = float(l["delay_ms"])
    return path, delays


class DelayRouting(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(DelayRouting, self).__init__(*args, **kwargs)
        self.datapaths = {}      # dpid -> datapath
        self.switch_ports = {}   # dpid -> set of port numbers
        self.links = {}          # (src_dpid, dst_dpid) -> (src_port, dst_port)
        self.link_ports = set()  # (dpid, port) pairs that face another switch
        self.hosts = {}          # ip -> (mac, dpid, port)
        self.recent_arp = {}     # (src_mac, target_ip) -> time, stops duplicate floods
        self.topology_complete = False

        path, self.delay_ms = load_link_delays(LINKS_FILE)
        self.logger.info("link delays from %s:", path)
        for pair, d in sorted(self.delay_ms.items(), key=lambda x: sorted(x[0])):
            a, b = sorted(pair)
            self.logger.info("    %s-%s  %g ms", sw(a), sw(b), d)

    # ------------------------------------------------------------------ helpers
    def add_flow(self, dp, priority, match, actions, idle=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = []
        if actions:
            inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle))

    def packet_out(self, dp, port, data):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                                        in_port=ofp.OFPP_CONTROLLER,
                                        actions=[parser.OFPActionOutput(port)],
                                        data=data))

    def edge_ports(self):
        for dpid, ports in self.switch_ports.items():
            for port in ports:
                if (dpid, port) not in self.link_ports:
                    yield dpid, port

    def learn_host(self, dpid, port, mac, ip):
        if (dpid, port) in self.link_ports or ip in self.hosts:
            return
        self.hosts[ip] = (mac, dpid, port)
        self.logger.info("host %s (%s) is attached to %s port %d", ip, mac, sw(dpid), port)

    def log_topology(self):
        self.logger.info("topology: %d switches, %d directed links",
                         len(self.switch_ports), len(self.links))
        done = (len(self.switch_ports) >= EXPECTED_SWITCHES
                and len(self.links) >= EXPECTED_DIRECTED_LINKS)
        if done and not self.topology_complete:
            self.logger.info("topology complete: %d switches, %d directed links",
                             len(self.switch_ports), len(self.links))
            for (a, b), (pa, pb) in sorted(self.links.items()):
                self.logger.info("    %s port %d -> %s port %d", sw(a), pa, sw(b), pb)
        self.topology_complete = done

    # ------------------------------------------------------------ path selection
    def link_costs(self):
        """Cost of every directed switch link = its configured delay in ms."""
        return {(a, b): self.delay_ms.get(frozenset((a, b)), UNKNOWN_LINK_COST)
                for (a, b) in self.links}

    @staticmethod
    def shortest_path(src, dst, costs):
        """Dijkstra. Returns (path as list of dpids, total cost) or (None, inf)."""
        adj = {}
        for (a, b), c in costs.items():
            adj.setdefault(a, []).append((b, c))
        dist, prev, heap = {src: 0.0}, {}, [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                break
            if d > dist[u]:
                continue
            for v, c in sorted(adj.get(u, [])):
                if v not in dist or d + c < dist[v]:
                    dist[v], prev[v] = d + c, u
                    heapq.heappush(heap, (d + c, v))
        if dst not in dist:
            return None, float("inf")
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return path[::-1], dist[dst]

    @staticmethod
    def all_simple_paths(src, dst, costs):
        """Only used for logging, to show why the chosen path wins."""
        adj = {}
        for (a, b) in costs:
            adj.setdefault(a, []).append(b)
        out, stack = [], [(src, [src])]
        while stack:
            u, path = stack.pop()
            if u == dst:
                out.append((sum(costs[(path[i], path[i + 1])] for i in range(len(path) - 1)), path))
                continue
            for v in adj.get(u, []):
                if v not in path:
                    stack.append((v, path + [v]))
        return sorted(out)

    def log_decision(self, src_ip, dst_ip, path, total, costs):
        self.logger.info("route %s -> %s (%s -> %s), metric = delay",
                         src_ip, dst_ip, sw(path[0]), sw(path[-1]))
        for cost, p in self.all_simple_paths(path[0], path[-1], costs):
            parts = " + ".join("%g" % costs[(p[i], p[i + 1])] for i in range(len(p) - 1)) or "0"
            mark = "   <- chosen" if p == path else ""
            self.logger.info("    candidate %-12s: %s = %g ms%s",
                             "-".join(sw(d) for d in p), parts, cost, mark)

    def install_path(self, path, src_ip, dst_ip, last_port):
        """Install src_ip->dst_ip rules on every switch of path. Returns dpid -> out_port."""
        out_ports = {}
        for i, dpid in enumerate(path):
            if i < len(path) - 1:
                out_ports[dpid] = self.links[(dpid, path[i + 1])][0]
            else:
                out_ports[dpid] = last_port
        for dpid in reversed(path):  # downstream switches first
            dp = self.datapaths[dpid]
            parser = dp.ofproto_parser
            match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                    ipv4_src=src_ip, ipv4_dst=dst_ip)
            self.add_flow(dp, PATH_PRIORITY, match,
                          [parser.OFPActionOutput(out_ports[dpid])], idle=IDLE_TIMEOUT)
        self.logger.info("    installed %s -> %s on %s", src_ip, dst_ip,
                         ", ".join("%s(out %d)" % (sw(d), out_ports[d]) for d in path))
        return out_ports

    def route(self, src_ip, dst_ip):
        _, s_dpid, s_port = self.hosts[src_ip]
        _, d_dpid, d_port = self.hosts[dst_ip]
        costs = self.link_costs()
        path, total = self.shortest_path(s_dpid, d_dpid, costs)
        if path is None:
            self.logger.warning("no path %s -> %s (topology incomplete?)", sw(s_dpid), sw(d_dpid))
            return {}
        self.log_decision(src_ip, dst_ip, path, total, costs)
        forward = self.install_path(path, src_ip, dst_ip, d_port)
        self.install_path(path[::-1], dst_ip, src_ip, s_port)  # reply direction
        return forward

    # ------------------------------------------------------------ OpenFlow events
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp
        self.add_flow(dp, 0, parser.OFPMatch(),
                      [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        self.add_flow(dp, IPV6_DROP_PRIORITY,
                      parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IPV6), [])
        self.logger.info("%s connected: table-miss and IPv6-drop rules installed", sw(dp.id))

    @set_ev_cls(topo_event.EventSwitchEnter)
    def switch_enter(self, ev):
        s = ev.switch
        self.datapaths[s.dp.id] = s.dp
        self.switch_ports[s.dp.id] = {p.port_no for p in s.ports}
        self.log_topology()

    @set_ev_cls(topo_event.EventSwitchLeave)
    def switch_leave(self, ev):
        dpid = ev.switch.dp.id
        self.datapaths.pop(dpid, None)
        self.switch_ports.pop(dpid, None)
        for key in [k for k in self.links if dpid in k]:
            del self.links[key]
        self.rebuild_link_ports()
        self.log_topology()

    @set_ev_cls(topo_event.EventLinkAdd)
    def link_add(self, ev):
        s, d = ev.link.src, ev.link.dst
        self.links[(s.dpid, d.dpid)] = (s.port_no, d.port_no)
        self.rebuild_link_ports()
        # a port that carries a switch link can never be a host attachment point
        for ip in [ip for ip, (_, dpid, port) in self.hosts.items()
                   if (dpid, port) in self.link_ports]:
            del self.hosts[ip]
        self.log_topology()

    @set_ev_cls(topo_event.EventLinkDelete)
    def link_delete(self, ev):
        self.links.pop((ev.link.src.dpid, ev.link.dst.dpid), None)
        self.rebuild_link_ports()
        self.log_topology()

    def rebuild_link_ports(self):
        self.link_ports = set()
        for (a, b), (pa, pb) in self.links.items():
            self.link_ports.add((a, pa))
            self.link_ports.add((b, pb))

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # LLDP is handled by Ryu's topology discovery

        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
            self.handle_arp(dp, in_port, arp_pkt, msg.data)
            return
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is not None:
            self.handle_ipv4(dp, in_port, eth, ip_pkt, msg.data)

    def handle_arp(self, dp, in_port, a, data):
        if (dp.id, in_port) in self.link_ports:
            return  # ARP is never sent into the ring, so ignore anything arriving there
        self.learn_host(dp.id, in_port, a.src_mac, a.src_ip)

        if a.opcode == arp.ARP_REQUEST:
            key, now = (a.src_mac, a.dst_ip), time.time()
            if now - self.recent_arp.get(key, 0) < 1.0:
                self.logger.info("arp: request %s -> who-has %s at %s ignored (duplicate within 1 s)",
                                 a.src_ip, a.dst_ip, sw(dp.id))
                return
            self.logger.info("arp: request %s -> who-has %s at %s, %s", a.src_ip, a.dst_ip, sw(dp.id),
                             "proxy reply" if a.dst_ip in self.hosts else "sent to edge ports")
            self.recent_arp[key] = now
            if a.dst_ip in self.hosts:
                self.arp_reply(dp, in_port, a)
            else:
                for dpid, port in self.edge_ports():
                    if (dpid, port) != (dp.id, in_port):
                        self.packet_out(self.datapaths[dpid], port, data)
        elif a.opcode == arp.ARP_REPLY and a.dst_ip in self.hosts:
            _, dpid, port = self.hosts[a.dst_ip]
            self.packet_out(self.datapaths[dpid], port, data)

    def arp_reply(self, dp, port, req):
        target_mac = self.hosts[req.dst_ip][0]
        p = packet.Packet()
        p.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP,
                                         dst=req.src_mac, src=target_mac))
        p.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=target_mac, src_ip=req.dst_ip,
                               dst_mac=req.src_mac, dst_ip=req.src_ip))
        p.serialize()
        self.packet_out(dp, port, p.data)

    def handle_ipv4(self, dp, in_port, eth, ip, data):
        self.learn_host(dp.id, in_port, eth.src, ip.src)
        if ip.src not in self.hosts or ip.dst not in self.hosts:
            self.logger.info("unknown host for %s -> %s, dropping", ip.src, ip.dst)
            return
        out_ports = self.route(ip.src, ip.dst)
        if dp.id in out_ports:
            self.packet_out(dp, out_ports[dp.id], data)
