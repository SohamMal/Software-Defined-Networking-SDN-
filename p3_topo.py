#!/usr/bin/env python3
"""Parts 2-3 starter topology: four hosts and a four-switch ring."""

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.topo import Topo


class CustomTopo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", protocols="OpenFlow13")
        s3 = self.addSwitch("s3", protocols="OpenFlow13")
        s4 = self.addSwitch("s4", protocols="OpenFlow13")

        h1 = self.addHost("h1")
        h2 = self.addHost("h2")
        h3 = self.addHost("h3")
        h4 = self.addHost("h4")

        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)
        self.addLink(h4, s4)

        # Ring links: bandwidth is in Mbps; delays are end-to-end link delays.
        self.addLink(s1, s2, bw=2, delay="20ms")
        self.addLink(s2, s3, bw=2, delay="10ms")
        self.addLink(s3, s4, bw=1, delay="20ms")
        self.addLink(s4, s1, bw=1, delay="15ms")


def run():
    net = Mininet(
        topo=CustomTopo(),
        controller=None,
        link=TCLink,
        switch=OVSKernelSwitch,
        autoSetMacs=True,
        build=True,
    )
    net.addController(
        "c0", controller=RemoteController, ip="127.0.0.1", port=6633
    )
    try:
        net.start()
        CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    run()
