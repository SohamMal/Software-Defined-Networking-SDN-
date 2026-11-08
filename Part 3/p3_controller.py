#!/usr/bin/env python3
"""Part 3: congestion-aware routing for NEW flows. Extends the Part 2 controller.

What is added to Part 2 (../Part 2/p2_controller.py, class DelayRouting)
  * Utilization: every POLL_INTERVAL s the controller requests port statistics
    from every switch. The tx_bytes difference on the port of switch u that faces
    switch v gives the rate of directed link u->v; utilization = rate / link bandwidth
    (bandwidth from the same JSON file as the topology).
  * Congestion rule: a directed link whose utilization is above UTIL_THRESHOLD is
    "congested" and its cost becomes  delay + CONGESTION_PENALTY_MS.
    The cost map is used only when a new flow is routed; existing flows keep their path.
  * Per-flow rules: Part 2 matched on (ipv4_src, ipv4_dst). Here every new
    transport flow (ip_proto + TCP/UDP ports) gets its own routing decision and its own
    rules, so a later flow between the same hosts can take a different path.
    Rules have idle_timeout = 30 s, so they disappear when a flow ends.
  * CONGESTION_AWARE=0 disables only the penalty -> static delay routing (baseline).
    Monitoring and logging stay the same, so both runs are directly comparable.

Run (Terminal 1, Ryu venv; topology = ../Part 2/p2_topo.py with links_default.json):
    source ~/ryu-env/bin/activate
    ryu-manager --ofp-tcp-listen-port 6633 --observe-links p3_controller.py 2>&1 | tee p3_aware_ryu.log
    CONGESTION_AWARE=0 ryu-manager --ofp-tcp-listen-port 6633 --observe-links p3_controller.py 2>&1 | tee p3_static_ryu.log
Or run the whole scenario automatically:  sudo bash run_p3.sh aware   /   sudo bash run_p3.sh static
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Part 2"))

from ryu.controller import ofp_event                                    # noqa: E402
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls          # noqa: E402
from ryu.lib import hub                                                 # noqa: E402
from ryu.lib.packet import ether_types, in_proto, packet, tcp, udp      # noqa: E402

import p2_controller                                                    # noqa: E402
from p2_controller import DelayRouting, sw                              # noqa: E402

POLL_INTERVAL = 1.0           # seconds between port-statistics requests
UTIL_THRESHOLD = 0.70         # a link above 70 % utilization is congested
CONGESTION_PENALTY_MS = 100.0  # extra cost added to a congested link
FLOW_PRIORITY = 20
FLOW_IDLE_TIMEOUT = 30
CONGESTION_AWARE = os.environ.get("CONGESTION_AWARE", "1") != "0"


def load_link_bandwidth(name):
    path = name if os.path.isabs(name) else os.path.join(p2_controller.HERE, name)
    with open(path) as f:
        links = json.load(f)["links"]
    return {frozenset((int(l["a"].lstrip("s")), int(l["b"].lstrip("s")))): float(l["bw_mbps"])
            for l in links}


class CongestionAwareRouting(DelayRouting):

    def __init__(self, *args, **kwargs):
        super(CongestionAwareRouting, self).__init__(*args, **kwargs)
        self.bw_mbps = load_link_bandwidth(p2_controller.LINKS_FILE)
        self.port_bytes = {}    # (dpid, port) -> (tx_bytes, switch time in s)
        self.port_rate = {}     # (dpid, port) -> Mbit/s over the last interval
        self.congested = {}     # (u, v) -> utilization, links above the threshold
        self.recent_flows = {}  # flow 5-tuple -> (time, out_ports), avoids re-routing
        self.logger.info("mode: %s (threshold %.0f%%, penalty %g ms, poll every %g s)",
                         "CONGESTION-AWARE" if CONGESTION_AWARE else "STATIC (penalty disabled)",
                         UTIL_THRESHOLD * 100, CONGESTION_PENALTY_MS, POLL_INTERVAL)
        self.monitor_thread = hub.spawn(self.monitor)

    # ------------------------------------------------------------- measurement
    def monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(POLL_INTERVAL)
            self.update_congestion()

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply(self, ev):
        dpid = ev.msg.datapath.id
        for st in ev.msg.body:
            key = (dpid, st.port_no)
            t = st.duration_sec + st.duration_nsec * 1e-9
            if key in self.port_bytes:
                b0, t0 = self.port_bytes[key]
                if t > t0:
                    self.port_rate[key] = (st.tx_bytes - b0) * 8 / (t - t0) / 1e6
            self.port_bytes[key] = (st.tx_bytes, t)

    def link_utilization(self):
        """(u, v) -> (rate Mbit/s, utilization) for every directed switch link."""
        util = {}
        for (a, b), (pa, _) in self.links.items():
            rate = self.port_rate.get((a, pa), 0.0)
            cap = self.bw_mbps.get(frozenset((a, b)))
            util[(a, b)] = (rate, rate / cap if cap else 0.0)
        return util

    def update_congestion(self):
        util = self.link_utilization()
        busy = sorted((l, ru) for l, ru in util.items() if ru[1] >= 0.05)
        if busy:
            self.logger.info("util: %s", "  ".join(
                "%s->%s %.2fMb/s %3.0f%%" % (sw(a), sw(b), r, u * 100) for (a, b), (r, u) in busy))
        now_congested = {l: u for l, (r, u) in util.items() if u > UTIL_THRESHOLD}
        for l in sorted(set(now_congested) - set(self.congested)):
            self.logger.info("CONGESTED: %s->%s at %.0f%% (> %.0f%%)",
                             sw(l[0]), sw(l[1]), now_congested[l] * 100, UTIL_THRESHOLD * 100)
        for l in sorted(set(self.congested) - set(now_congested)):
            self.logger.info("cleared:   %s->%s back to %.0f%%",
                             sw(l[0]), sw(l[1]), util.get(l, (0, 0))[1] * 100)
        self.congested = now_congested

    # ------------------------------------------------------------- path costs
    def link_costs(self):
        costs = super(CongestionAwareRouting, self).link_costs()
        if CONGESTION_AWARE:
            for l in self.congested:
                if l in costs:
                    costs[l] += CONGESTION_PENALTY_MS
        return costs

    # ------------------------------------------------------------- per-flow routing
    @staticmethod
    def flow_name(flow):
        src, dst, proto, sport, dport = flow
        name = {in_proto.IPPROTO_TCP: "TCP", in_proto.IPPROTO_UDP: "UDP",
                in_proto.IPPROTO_ICMP: "ICMP"}.get(proto, "proto %d" % proto)
        if sport is None:
            return "%s %s -> %s" % (name, src, dst)
        return "%s %s:%d -> %s:%d" % (name, src, sport, dst, dport)

    def flow_match(self, parser, flow):
        src, dst, proto, sport, dport = flow
        fields = dict(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=src, ipv4_dst=dst, ip_proto=proto)
        if proto == in_proto.IPPROTO_TCP and sport is not None:
            fields.update(tcp_src=sport, tcp_dst=dport)
        elif proto == in_proto.IPPROTO_UDP and sport is not None:
            fields.update(udp_src=sport, udp_dst=dport)
        return parser.OFPMatch(**fields)

    def install_flow(self, path, flow, last_port):
        out_ports = {}
        for i, dpid in enumerate(path):
            out_ports[dpid] = self.links[(dpid, path[i + 1])][0] if i < len(path) - 1 else last_port
        for dpid in reversed(path):  # downstream switches first
            dp = self.datapaths[dpid]
            parser = dp.ofproto_parser
            self.add_flow(dp, FLOW_PRIORITY, self.flow_match(parser, flow),
                          [parser.OFPActionOutput(out_ports[dpid])], idle=FLOW_IDLE_TIMEOUT)
        self.logger.info("    installed %s on %s", self.flow_name(flow),
                         ", ".join("%s(out %d)" % (sw(d), out_ports[d]) for d in path))
        return out_ports

    def route_flow(self, flow):
        src, dst, proto, sport, dport = flow
        reverse = (dst, src, proto, dport, sport)
        now = time.time()
        # packets of a flow that reach the controller before its rules are active
        for key in (flow, reverse):
            if key in self.recent_flows and now - self.recent_flows[key][0] < 2.0:
                return self.recent_flows[key][1]

        _, s_dpid, s_port = self.hosts[src]
        _, d_dpid, d_port = self.hosts[dst]
        costs = self.link_costs()
        path, total = self.shortest_path(s_dpid, d_dpid, costs)
        if path is None:
            self.logger.warning("no path %s -> %s", sw(s_dpid), sw(d_dpid))
            return {}

        self.logger.info("NEW FLOW %s", self.flow_name(flow))
        if self.congested:
            self.logger.info("    congested links: %s%s", ", ".join(
                "%s->%s %.0f%%" % (sw(a), sw(b), u * 100) for (a, b), u in sorted(self.congested.items())),
                "  (+%g ms each)" % CONGESTION_PENALTY_MS if CONGESTION_AWARE else "  (ignored: static mode)")
        else:
            self.logger.info("    no congested links")
        self.log_decision(src, dst, path, total, costs)
        forward = self.install_flow(path, flow, d_port)
        backward = self.install_flow(path[::-1], reverse, s_port)
        self.recent_flows[flow] = (now, forward)
        self.recent_flows[reverse] = (now, backward)
        return forward

    def handle_ipv4(self, dp, in_port, eth, ip, data):
        self.learn_host(dp.id, in_port, eth.src, ip.src)
        if ip.src not in self.hosts or ip.dst not in self.hosts:
            return
        pkt = packet.Packet(data)
        l4 = pkt.get_protocol(tcp.tcp) or pkt.get_protocol(udp.udp)
        flow = (ip.src, ip.dst, ip.proto,
                l4.src_port if l4 else None, l4.dst_port if l4 else None)
        out_ports = self.route_flow(flow)
        if dp.id in out_ports:
            self.packet_out(dp, out_ports[dp.id], data)
