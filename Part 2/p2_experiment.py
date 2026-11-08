#!/usr/bin/env python3
"""Part 2 experiment: runs the test sequence on p2_topo.py without the interactive CLI.

Normally started by run_p2.sh (which also starts the Ryu controller):
    sudo python3 p2_experiment.py <links json> <ryu log file>

Sequence (first ping is the first traffic in the network):
    h1 ping h3 -> dump-flows s1..s4 -> h3 ping h1 -> pingall
"""

import subprocess
import sys
import time

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController

from p2_topo import HERE, RingTopo, load_links
import os


def section(title):
    print("\n" + "=" * 70 + "\n### " + title + "\n" + "=" * 70, flush=True)


def wait_for_topology(ryu_log, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(ryu_log) as f:
                if "topology complete" in f.read():
                    print("*** controller reports topology complete after %.1f s"
                          % (time.time() - start), flush=True)
                    return True
        except FileNotFoundError:
            pass
        time.sleep(0.5)
    print("*** WARNING: topology not complete after %d s" % timeout, flush=True)
    return False


def main():
    links_name, ryu_log = sys.argv[1], sys.argv[2]
    links = load_links(os.path.join(HERE, links_name))
    print("*** Link properties from %s" % links_name)
    for l in links:
        print("    %s-%s  %g Mbps  %g ms" % (l["a"], l["b"], l["bw_mbps"], l["delay_ms"]))

    setLogLevel("info")
    net = Mininet(topo=RingTopo(links=links), controller=None, link=TCLink,
                  switch=OVSKernelSwitch, autoSetMacs=True, build=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
    net.start()
    try:
        wait_for_topology(ryu_log)
        h1, h3 = net.get("h1", "h3")

        section("h1 ping -c 5 h3   (first traffic in the network)")
        print(h1.cmd("ping -c 5 %s" % h3.IP()), flush=True)

        for s in ("s1", "s2", "s3", "s4"):
            section("ovs-ofctl -O OpenFlow13 dump-flows %s" % s)
            print(subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", s],
                                 capture_output=True, text=True).stdout, flush=True)

        section("h3 ping -c 5 h1   (reverse direction)")
        print(h3.cmd("ping -c 5 %s" % h1.IP()), flush=True)

        section("pingall")
        net.pingAll()
    finally:
        net.stop()


if __name__ == "__main__":
    main()
