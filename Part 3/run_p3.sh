#!/bin/bash
# Part 3: run the congestion scenario with the controller in one mode and save the evidence.
#
#   sudo bash run_p3.sh aware    # congestion-aware -> p3_aware_ryu.log,  p3_aware_mininet.txt
#   sudo bash run_p3.sh static   # static baseline  -> p3_static_ryu.log, p3_static_mininet.txt
#
# Uses ../Part 2 (p2_topo.py, p2_controller.py, links_default.json), so keep both folders together.
# Ryu is taken from $RYU_ENV (default: ~<user>/ryu-env, the Python 3.9 venv).

set -u
cd "$(dirname "$0")"

MODE=${1:-aware}
case "$MODE" in
    aware)  AWARE=1 ;;
    static) AWARE=0 ;;
    *) echo "usage: $0 aware|static"; exit 1 ;;
esac
USER_HOME=$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)
RYU_ENV=${RYU_ENV:-$USER_HOME/ryu-env}
RYU_LOG=p3_${MODE}_ryu.log
MN_OUT=p3_${MODE}_mininet.txt

service openvswitch-switch start >/dev/null
mn -c >/dev/null 2>&1

rm -f "$RYU_LOG" "$MN_OUT"
CONGESTION_AWARE=$AWARE "$RYU_ENV/bin/ryu-manager" --ofp-tcp-listen-port 6633 --observe-links \
    p3_controller.py >"$RYU_LOG" 2>&1 &
RYU_PID=$!
trap 'kill $RYU_PID 2>/dev/null' EXIT
sleep 2

python3 p3_experiment.py "$MODE" "$RYU_LOG" 2>&1 | tee "$MN_OUT"

sleep 1
echo; echo "Saved: $RYU_LOG  $MN_OUT"
