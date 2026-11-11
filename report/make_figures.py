"""Builds the report figures from the experiment logs.  Run from the repository root:
    python report/make_figures.py
"""
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "report", "figs")
os.makedirs(OUT, exist_ok=True)
C = {"blue": "#4C72B0", "orange": "#DD8452", "green": "#55A868", "purple": "#8172B3", "grey": "#9a9a9a"}
plt.rcParams.update({"font.size": 9, "axes.titlesize": 9, "figure.dpi": 150})


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace") as f:
        return f.read()


def first_ping_rtts(text, dst):
    """RTTs of the first 'ping ... dst' block in a Mininet output."""
    block = text.split("PING %s" % dst, 1)[1].split("ping statistics", 1)[0]
    return [float(x) for x in re.findall(r"icmp_seq=\d+ ttl=\d+ time=([\d.]+) ms", block)]


# ---------------------------------------------------------------- Figure 1: Part 1
reactive = read("Part 1", "reactive_mininet.txt")
proactive = read("Part 1", "proactive_mininet.txt")
r_rtt, p_rtt = first_ping_rtts(reactive, "10.0.0.5"), first_ping_rtts(proactive, "10.0.0.5")
r_pin = len(re.findall(r"PacketIn #\d+", read("Part 1", "reactive_ryu.log")))
p_pin = len(re.findall(r"PacketIn #\d+", read("Part 1", "proactive_ryu.log")))

fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.5))
b = ax[0].bar(["reactive", "proactive"], [r_pin, p_pin], color=[C["blue"], C["orange"]], width=0.55)
ax[0].bar_label(b, padding=2)
ax[0].set_ylabel("Packet-Ins at controller")
ax[0].set_title("(a) controller workload (ping + pingall)")
ax[0].set_ylim(0, r_pin * 1.2)
x = range(1, len(r_rtt) + 1)
w = 0.38
ax[1].bar([i - w / 2 for i in x], r_rtt, w, label="reactive", color=C["blue"])
ax[1].bar([i + w / 2 for i in x], p_rtt, w, label="proactive", color=C["orange"])
ax[1].set_xticks(list(x))
ax[1].set_xlabel("ping sequence number (h1 -> h5)")
ax[1].set_ylabel("RTT (ms)")
ax[1].set_title("(b) RTT of the first five pings")
ax[1].legend(frameon=False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "p1.pdf"))
plt.close(fig)

# ---------------------------------------------------------------- Figure 2: Part 2
pos = {1: (0, 1), 2: (1, 1), 3: (1, 0), 4: (0, 0)}
delays = {(1, 2): 20, (2, 3): 10, (3, 4): 20, (4, 1): 15}
bw = {(1, 2): 2, (2, 3): 2, (3, 4): 1, (4, 1): 1}


def draw_ring(ax, path, d12, title, colour):
    on_path = {frozenset(p) for p in zip(path, path[1:])}
    for (a, b), d in delays.items():
        d = d12 if (a, b) == (1, 2) else d
        hot = frozenset((a, b)) in on_path
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ax.plot([x1, x2], [y1, y2], color=colour if hot else C["grey"], lw=3.2 if hot else 1.3, zorder=1)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        off = {(1, 2): (0, 0.11), (2, 3): (0.2, 0), (3, 4): (0, -0.13), (4, 1): (-0.2, 0)}[(a, b)]
        ax.text(mx + off[0], my + off[1], "%d ms\n%d Mb/s" % (d, bw[(a, b)]), ha="center", va="center",
                fontsize=7.5, fontweight="bold" if (a, b) == (1, 2) and d12 != 20 else "normal")
    for s, (px, py) in pos.items():
        ax.scatter([px], [py], s=430, color="white", edgecolor="black", zorder=2)
        ax.text(px, py, "s%d" % s, ha="center", va="center", zorder=3)
        hx, hy = px + (-0.17 if px == 0 else 0.17), py + (0.17 if py == 1 else -0.17)
        ax.text(hx, hy, "h%d" % s, ha="center", va="center", fontsize=7.5, color="#444")
    ax.set_title(title)
    ax.set_xlim(-0.45, 1.45)
    ax.set_ylim(-0.35, 1.35)
    ax.set_aspect("equal")
    ax.axis("off")


d_rtt = first_ping_rtts(read("Part 2", "p2_default_mininet.txt"), "10.0.0.3")
c_rtt = first_ping_rtts(read("Part 2", "p2_changed_mininet.txt"), "10.0.0.3")
fig = plt.figure(figsize=(7.2, 2.6))
ax1 = fig.add_axes([0.0, 0.02, 0.27, 0.9])
ax2 = fig.add_axes([0.27, 0.02, 0.27, 0.9])
ax3 = fig.add_axes([0.63, 0.17, 0.36, 0.72])
draw_ring(ax1, [1, 2, 3], 20, "(a) default\nh1->h3 via s2 (30 ms)", C["blue"])
draw_ring(ax2, [1, 4, 3], 40, "(b) s1-s2 raised to 40 ms\nh1->h3 via s4 (35 ms)", C["orange"])
x = range(1, len(d_rtt) + 1)
ax3.bar([i - w / 2 for i in x], d_rtt, w, label="default (via s2)", color=C["blue"])
ax3.bar([i + w / 2 for i in x], c_rtt, w, label="changed (via s4)", color=C["orange"])
ax3.axhline(60, color=C["blue"], ls="--", lw=0.8)
ax3.axhline(70, color=C["orange"], ls="--", lw=0.8)
ax3.set_xticks(list(x))
ax3.set_xlabel("ping sequence number (h1 -> h3)")
ax3.set_ylabel("RTT (ms)")
ax3.set_title("(c) RTT; dashed = 2 x path delay")
ax3.legend(frameon=False, fontsize=7.5, loc="upper right")
fig.savefig(os.path.join(OUT, "p2.pdf"))
plt.close(fig)


# ---------------------------------------------------------------- Figure 3: Part 3
def util_series(log):
    """Utilization per poll (one 'util:' line per second) and the poll index of flow B."""
    series, b_at = [], None
    for line in log.splitlines():
        if line.startswith("util:"):
            series.append({k: float(u) for k, u in re.findall(r"(s\d->s\d) [\d.]+Mb/s\s+(\d+)%", line)})
        elif line.startswith("NEW FLOW TCP") and b_at is None:
            b_at = len(series)
    return series, b_at


def server_intervals(text, label):
    block = text.split("flow %s measured at the receiver" % label, 1)[1].split("\n###", 1)[0]
    rows = re.findall(r"\]\s+([\d.]+)-([\d.]+) sec\s+[\d.]+ \w?Bytes\s+([\d.]+) Mbits/sec", block)
    rows = [(float(a), float(b), float(r)) for a, b, r in rows]
    total = [r for r in rows if r[0] == 0 and r[1] > 5.5][-1]   # the whole-run summary line
    return [r for r in rows if r is not total and r[1] - r[0] <= 5.01], total[2]


fig, ax = plt.subplots(1, 3, figsize=(7.2, 2.5), gridspec_kw={"width_ratios": [1, 1, 1.05]})
for i, mode in enumerate(("static", "aware")):
    series, b_at = util_series(read("Part 3", "p3_%s_ryu.log" % mode))
    t = [k - b_at for k in range(len(series))]
    for link, col in (("s1->s2", C["blue"]), ("s1->s4", C["orange"])):
        ax[i].plot(t, [s.get(link, 0) for s in series], color=col, lw=1.4, label=link)
    ax[i].axhline(70, color="black", ls=":", lw=0.9)
    ax[i].axvline(0, color=C["grey"], lw=0.9)
    ax[i].text(0.6, 4, "flow B\nstarts", fontsize=7, color="#555")
    ax[i].set_ylim(0, 108)
    ax[i].set_xlim(-8, 28)
    ax[i].set_xlabel("time relative to flow B start (s)")
    ax[i].set_title("(%s) link utilization, %s" % ("ab"[i], mode))
ax[0].set_ylabel("utilization (%)")
ax[0].legend(frameon=False, fontsize=7.5, loc="center left")

for mode, col in (("static", C["blue"]), ("aware", C["green"])):
    per, total = server_intervals(read("Part 3", "p3_%s_mininet.txt" % mode), "B")
    xs, ys = [], []
    for a, b2, r in per:
        xs += [a, b2]
        ys += [r, r]
    ax[2].plot(xs, ys, color=col, lw=1.5, label="%s (avg %.2f)" % (mode, total))
ax[2].set_ylim(0, 2.0)
ax[2].set_xlabel("time since flow B start (s)")
ax[2].set_ylabel("flow B throughput (Mbit/s)")
ax[2].set_title("(c) flow B at the receiver")
ax[2].legend(frameon=False, fontsize=7.5, loc="upper left")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "p3.pdf"))
plt.close(fig)
print("figures written to", OUT)
