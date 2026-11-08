#!/usr/bin/env python3
"""Part 2 topology: p3_topo.py ring, but inter-switch link properties are read
from a JSON file so the controller and Mininet always agree on them.

Change vs p3_topo.py: only the source of the link bw/delay values (JSON file
instead of hard-coded). With links_default.json it is identical to p3_topo.py.

Run:
  sudo python3 p2_topo.py                          # uses links_default.json
  sudo python3 p2_topo.py links_changed.json       # s1-s2 delay = 40 ms
(Start the controller with the SAME json file, see p2_controller.py.)
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
    def build(self, links):
        sw = {i: self.addSwitch("s%d" % i, protocols="OpenFlow13") for i in range(1, 5)}
        # Host links first -> host is always on port 1 of its switch
        for i in range(1, 5):
            self.addLink(self.addHost("h%d" % i), sw[i])
        for l in links:
            self.addLink(sw[l["a"]], sw[l["b"]], bw=l["bw"], delay="%sms" % l["delay"])


def run():
    cfg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "links_default.json")
    links = load_links(cfg)
    print("Using link config:", cfg)
    for l in links:
        print("  s%d-s%d  bw=%s Mbps  delay=%s ms" % (l["a"], l["b"], l["bw"], l["delay"]))

    net = Mininet(topo=RingTopo(links=links), controller=None, link=TCLink,
                  switch=OVSKernelSwitch, autoSetMacs=True, build=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
    try:
        net.start()
        CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    run()
