# Part 1 - REACTIVE flow installation (MAC-learning switch)
# Run: ryu-manager --ofp-tcp-listen-port 6633 p1_reactive.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types


class ReactiveSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}       # {dpid: {mac: port}} learned from traffic
        self.packet_in_count = 0    # <-- our comparison metric

    def add_flow(self, dp, priority, match, actions, idle_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle_timeout))

    # Called once when a switch connects: install only the bare minimum.
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        # Table-miss: anything unmatched -> send to controller (Packet-In)
        self.add_flow(dp, 0, parser.OFPMatch(),
                      [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        # Drop IPv6 (router solicitations etc.) so it doesn't pollute the count
        self.add_flow(dp, 100, parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IPV6), [])
        self.logger.info("s%d connected: table-miss rule installed", dp.id)

    # Called for every packet that hit the table-miss rule.
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match['in_port']
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.packet_in_count += 1
        src, dst = eth.src, eth.dst

        # 1. Learn: src MAC lives behind in_port on this switch
        self.mac_to_port.setdefault(dp.id, {})[src] = in_port

        # 2. Decide: known dst -> its port, else flood
        out_port = self.mac_to_port[dp.id].get(dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        # 3. Install a rule so future packets of this flow skip the controller
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
            self.add_flow(dp, 1, match, actions, idle_timeout=60)

        self.logger.info("PacketIn #%d  s%d in=%d  %s -> %s  out=%s",
                         self.packet_in_count, dp.id, in_port, src, dst,
                         "FLOOD" if out_port == ofp.OFPP_FLOOD else out_port)

        # 4. Forward this first packet ourselves (Packet-Out)
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions, data=data))