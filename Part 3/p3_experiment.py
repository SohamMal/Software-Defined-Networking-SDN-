#!/usr/bin/env python3
"""Part 3 congestion scenario on the Part 2 ring (../Part 2/p2_topo.py, links_default.json).

Normally started by run_p3.sh (which also starts the controller):
    sudo python3 p3_experiment.py <aware|static> <ryu log file>

Topology change for Part 3: ring-link queues are limited to MAX_QUEUE packets. With the
Mininet default (1000 packets) a 1 Mbit/s link can buffer ~12 s of traffic, which makes
TCP results and LLDP timing unrealistic. Bandwidth and delay are unchanged.

Timeline
  t = 0 s   flow A: h1 -> h3, UDP 1.5 Mbit/s for 30 s. Network idle -> s1-s2-s3 (30 ms).
            It fills ~80 % of the 2 Mbit/s links s1->s2 and s2->s3.
  t = 6 s   flow B: h1 -> h3, TCP for 15 s (new flow, routed with current measurements).
  t = 11 s  TCP/UDP rules of s1..s4 are dumped (shows which path each flow uses).
Measures (receiver side, iperf servers on h3): throughput of flow B, throughput/loss of flow A.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Part 2"))

from mininet.link import TCLink                              # noqa: E402
from mininet.log import setLogLevel                          # noqa: E402
from mininet.net import Mininet                              # noqa: E402
from mininet.node import OVSKernelSwitch, RemoteController   # noqa: E402

from p2_experiment import section, wait_for_topology         # noqa: E402
from p2_topo import HERE as P2_DIR, RingTopo, load_links     # noqa: E402

MAX_QUEUE = 100
SERVER_A = "stdbuf -oL iperf -s -u -p 5001 -i 5 -f m"
SERVER_B = "stdbuf -oL iperf -s -p 5002 -i 5 -f m"
FLOW_A = "iperf -c 10.0.0.3 -u -p 5001 -b 1.5M -t 30 -f m"
FLOW_B = "iperf -c 10.0.0.3 -p 5002 -t 15 -f m"


def popen(host, cmd):
    return host.popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main():
    mode, ryu_log = sys.argv[1], sys.argv[2]
    links = load_links(os.path.join(P2_DIR, "links_default.json"))
    print("*** Part 3 scenario, controller mode: %s, ring-link queue %d packets"
          % (mode, MAX_QUEUE))

    setLogLevel("info")
    net = Mininet(topo=RingTopo(links=links, max_queue=MAX_QUEUE), controller=None,
                  link=TCLink, switch=OVSKernelSwitch, autoSetMacs=True, build=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
    net.start()
    servers = {}
    try:
        wait_for_topology(ryu_log)
        h1, h3 = net.get("h1", "h3")

        section("pingall (connectivity check, also resolves ARP)")
        net.pingAll()

        servers = {"A": popen(h3, SERVER_A), "B": popen(h3, SERVER_B)}
        time.sleep(1)

        section("t=0  flow A: h1 -> h3  UDP 1.5 Mbit/s, 30 s   (%s)" % FLOW_A)
        flow_a = popen(h1, FLOW_A)
        time.sleep(6)

        section("t=6  flow B: h1 -> h3  TCP, 15 s   (%s)" % FLOW_B)
        flow_b = popen(h1, FLOW_B)
        time.sleep(5)

        for s in ("s1", "s2", "s3", "s4"):
            section("t=11  TCP/UDP rules on %s" % s)
            out = subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", s],
                                 capture_output=True, text=True).stdout
            rules = [l for l in out.splitlines() if "tcp" in l or "udp" in l]
            print("\n".join(rules) if rules else "(no TCP/UDP rules)", flush=True)

        flow_b.wait()
        flow_a.wait()
        time.sleep(2)
        for name in ("B", "A"):
            servers[name].terminate()
            out = servers[name].communicate()[0].decode()
            section("flow %s measured at the receiver h3 (iperf server)" % name)
            print(out, flush=True)
    finally:
        for p in servers.values():
            if p.poll() is None:
                p.terminate()
        net.stop()


if __name__ == "__main__":
    main()
