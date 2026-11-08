# Part 1 - PROACTIVE flow installation
# All forwarding rules are pushed when each switch connects, before any traffic.
# Run: ryu-manager --ofp-tcp-listen-port 6633 p1_proactive.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

BCAST = 'ff:ff:ff:ff:ff:ff'

def mac(i):
    return '00:00:00:00:00:%02x' % i   # autoSetMacs=True -> h1=..:01

# Static knowledge of p1_topo.py: {dpid: {host_number: out_port}}
# s1: h1-p1, h2-p2, h3-p3, s2 via p4 | s2: h4-p1, h5-p2, s1 via p3
FORWARDING = {
    1: {1: 1, 2: 2, 3: 3, 4: 4, 5: 4},
    2: {1: 3, 2: 3, 3: 3, 4: 1, 5: 2},
}


class ProactiveSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.packet_in_count = 0

    def add_flow(self, dp, priority, match, actions):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority,
                                      match=match, instructions=inst))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser

        # Same base rules as reactive (fair comparison)
        self.add_flow(dp, 0, parser.OFPMatch(),
                      [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        self.add_flow(dp, 100, parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IPV6), [])

        # Broadcast (ARP requests): flood in the data plane, no controller needed.
        # Safe because the topology has no loops.
        self.add_flow(dp, 10, parser.OFPMatch(eth_dst=BCAST),
                      [parser.OFPActionOutput(ofp.OFPP_FLOOD)])

        # One rule per destination host, installed BEFORE any traffic
        for host, port in FORWARDING.get(dp.id, {}).items():
            self.add_flow(dp, 10, parser.OFPMatch(eth_dst=mac(host)),
                          [parser.OFPActionOutput(port)])

        self.logger.info("s%d connected: %d host rules + broadcast rule pre-installed",
                         dp.id, len(FORWARDING.get(dp.id, {})))

    # Should stay at ~0: only fires if some traffic is not covered by our rules
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        eth = packet.Packet(ev.msg.data).get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        self.packet_in_count += 1
        self.logger.info("PacketIn #%d  s%d  %s -> %s (unexpected)",
                         self.packet_in_count, ev.msg.datapath.id, eth.src, eth.dst)