#!/bin/bash
# Start the FS-UAE built from source (grahambates/fs-uae, branch
# remote_debugger_barto -- see fsuaebuildcontainer.sh and fsuaebuildclang.sh)
# in a private Xvfb, and time its GDB-remote memory reads while the machine
# runs.  A probe for #464: does a read return while the Amiga is running?
#
# Uses work/issue464/forksrc/fs-uae as the emulator and work/issue464/base3 as
# its base directory, display :78, debugger port 6528.  Those are fixed: check
# nothing else is on them.  No window reaches the desktop (Xvfb), audio is
# dummied, and the emulator's process group is killed on the way out.
#
# Reads with the Gdb class of tools/fsuaegdbprobe.py.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
D="$ROOT/work/issue464"
mkdir -p "$D/base3"
Xvfb :78 -screen 0 800x600x24 -nolisten tcp >"$D/xvfb78.log" 2>&1 &
XPID=$!
sleep 2
env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE DISPLAY=:78 GDK_BACKEND=x11 \
    SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null \
    setsid "$D/forksrc/fs-uae" \
      --base_dir="$D/base3" \
      --fullscreen=0 --volume=0 \
      --remote_debugger=30 --remote_debugger_port=6528 \
      >"$D/built-run.log" 2>&1 &
FPID=$!
echo "xvfb=$XPID fsuae=$FPID"
sleep 6
ss -ltnp 2>/dev/null | grep 6528 || echo "NOT LISTENING YET"
PY_EXIT=0
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY' || PY_EXIT=$?
import time
from tools.fsuaegdbprobe import Gdb
g = Gdb(port=6528)
print("qSupported:", g.ask("qSupported")[:120])
g.send("vCont;c")
time.sleep(0.5)
for i in range(6):
    t0=time.perf_counter(); v=g.read_mem(0xDFF006,2); dt=1000*(time.perf_counter()-t0)
    t1=time.perf_counter(); b=g.read_mem(0x0,1024); dt2=1000*(time.perf_counter()-t1)
    print(f"vhposr={v.hex()} {dt:5.1f}ms   1KB {dt2:5.1f}ms nonzero={sum(1 for x in b if x)}")
    time.sleep(0.4)
PY
echo "PY_EXIT=$PY_EXIT"
kill -- -$FPID 2>/dev/null || true
sleep 1
kill -9 -$FPID 2>/dev/null || true
kill $XPID 2>/dev/null || true
echo "audio sinks touched:"; pactl list sink-inputs 2>/dev/null | grep -ci amiga || true
