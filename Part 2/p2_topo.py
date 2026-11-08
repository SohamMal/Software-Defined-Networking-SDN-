#!/usr/bin/env python3
"""Part 2 topology: the p3_topo.py ring, with link properties read from a JSON file.

Change from the starter p3_topo.py: the ring link bandwidth/delay values come from
a JSON file (default links_default.json) so that the topology and the controller
always use the same numbers. With links_default.json the network is identical to
p3_topo.py. links_changed.json raises the s1-s2 delay from 20 ms to 40 ms.

Run (Terminal 2, system Python):
    sudo mn -c
    sudo python3 p2_topo.py                      # default link properties
    sudo python3 p2_topo.py links_changed.json   # changed-property test

Port numbers follow the addLink order: every host h_i is on port 1 of s_i,
s1: s2=2, s4=3 | s2: s1=2, s3=3 | s3: s2=2, s4=3 | s4: s3=2, s1=3
"""

import json
import os
import sys

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.topo import Topo

HERE = os.path.dirname(os.path.abspath(__file__))


def load_links(path):
    with open(path) as f:
        return json.load(f)["links"]


class RingTopo(Topo):
    def build(self, links, max_queue=None):
        # max_queue: optional queue limit (packets) on the ring links. Part 2 leaves it
        # at the Mininet default; Part 3 sets it (see Part 3/p3_experiment.py).
        queue = {"max_queue_size": max_queue} if max_queue else {}
        switches = {}
        for i in range(1, 5):
            switches["s%d" % i] = self.addSwitch("s%d" % i, protocols="OpenFlow13")
        for i in range(1, 5):
            host = self.addHost("h%d" % i)
            self.addLink(host, switches["s%d" % i])

        for l in links:
            self.addLink(switches[l["a"]], switches[l["b"]],
                         bw=l["bw_mbps"], delay="%gms" % l["delay_ms"], **queue)


def run():
    name = sys.argv[1] if len(sys.argv) > 1 else "links_default.json"
    path = name if os.path.isabs(name) else os.path.join(HERE, name)
    links = load_links(path)
    print("*** Link properties from %s" % path)
    for l in links:
        print("    %s-%s  %g Mbps  %g ms" % (l["a"], l["b"], l["bw_mbps"], l["delay_ms"]))

    net = Mininet(
        topo=RingTopo(links=links),
        controller=None,
        link=TCLink,
        switch=OVSKernelSwitch,
        autoSetMacs=True,
        build=True,
    )
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
    try:
        net.start()
        CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    run()
