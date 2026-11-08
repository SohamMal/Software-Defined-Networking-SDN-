#!/bin/bash
# Part 2: run one complete experiment (controller + Mininet) and save the evidence.
#
#   sudo bash run_p2.sh default    # links_default.json  -> p2_default_ryu.log, p2_default_mininet.txt
#   sudo bash run_p2.sh changed    # links_changed.json  -> p2_changed_ryu.log, p2_changed_mininet.txt
#
# Ryu is taken from $RYU_ENV (default: ~<user>/ryu-env, the Python 3.9 venv).
# For an interactive run instead, start p2_controller.py and p2_topo.py by hand
# (commands are at the top of those files).

set -u
cd "$(dirname "$0")"

NAME=${1:-default}
LINKS=links_${NAME}.json
[ -f "$LINKS" ] || { echo "no such file: $LINKS"; exit 1; }
USER_HOME=$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)
RYU_ENV=${RYU_ENV:-$USER_HOME/ryu-env}
RYU_LOG=p2_${NAME}_ryu.log
MN_OUT=p2_${NAME}_mininet.txt

service openvswitch-switch start >/dev/null
mn -c >/dev/null 2>&1

rm -f "$RYU_LOG" "$MN_OUT"
LINKS_FILE=$LINKS "$RYU_ENV/bin/ryu-manager" --ofp-tcp-listen-port 6633 --observe-links \
    p2_controller.py >"$RYU_LOG" 2>&1 &
RYU_PID=$!
trap 'kill $RYU_PID 2>/dev/null' EXIT
sleep 2

python3 p2_experiment.py "$LINKS" "$RYU_LOG" 2>&1 | tee "$MN_OUT"

sleep 1
echo; echo "Saved: $RYU_LOG  $MN_OUT"
