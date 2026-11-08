#!/usr/bin/env python3
"""Part 1 starter topology: five hosts connected to two OpenFlow 1.3 switches."""

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.topo import Topo


class CustomTopo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", protocols="OpenFlow13")

        h1 = self.addHost("h1")
        h2 = self.addHost("h2")
        h3 = self.addHost("h3")
        h4 = self.addHost("h4")
        h5 = self.addHost("h5")

        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)
        self.addLink(h4, s2)
        self.addLink(h5, s2)
        # A shaped inter-switch link makes the topology suitable for basic tests.
        self.addLink(s1, s2, bw=10, delay="5ms")


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
