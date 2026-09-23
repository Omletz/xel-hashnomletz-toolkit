"""Standalone Windows PTY diagnostic -- NOT part of the automated test suite (this needs a fresh wallet
dir and prints a lot of raw output on purpose). Bypasses wallet_manager.py and the GUI entirely: spawns
xelis_wallet directly via pywinpty and prints every byte read AS IT ARRIVES, with a timestamp, so we can
see in real time whether output is flowing at all.

Why this exists: the first Windows PTY attempt (wexpect) deadlocked -- the wallet subprocess spawned and
stayed alive (Task Manager showed it holding memory) but sat at 0% CPU indefinitely during wallet
creation, never producing output, never erroring. This script isolates the PTY layer from everything else
(no background thread, no queue, no wallet_manager.py abstractions) to see raw behavior directly.

Run from the project root after `pip install -r requirements.txt`:
    venv\\Scripts\\python tests\\diag_pty_windows.py

Expected GOOD outcome: within the first few seconds you should see a stream of
"[+0.3s] chunk: ..." lines with "Generating precomputed tables" / "Progress: X%" text scrolling by
continuously (it's verbose -- lots of lines, that's normal and expected, not a bug).

If instead you see the "opened, waiting for output..." line and then NOTHING for 10+ seconds while
Task Manager shows xelis_wallet.exe alive at ~0% CPU, that's the same deadlock as before -- pywinpty
isn't the fix either, and this narrows it down to genuinely needing a completely different approach
(e.g. driving via ConPTY more directly, or reconsidering whether interactive-prompt automation is
viable on Windows at all for this binary)."""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

BIN_DIR = os.path.join(os.path.expanduser('~'), '.hashnomletz-xelis-wallet')
BINARY = os.path.join(BIN_DIR, 'xelis_wallet.exe')
if not os.path.exists(BINARY):
    print(f"ERROR: {BINARY} doesn't exist yet.")
    print("Run the real app once first (python app/main.py) so it downloads+verifies the binary, then Ctrl+C out and re-run this script.")
    sys.exit(1)

WALLET_DIR = os.path.join(os.path.dirname(__file__), '_diag_wallet')
shutil.rmtree(WALLET_DIR, ignore_errors=True)
TABLES_DIR = os.path.join(BIN_DIR, 'tables') + os.sep
os.makedirs(TABLES_DIR, exist_ok=True)

import winpty

args = [
    BINARY,
    '--wallet-path', WALLET_DIR,
    '--password', 'diagtest1234',
    '--network', 'devnet',
    '--offline-mode',
    '--disable-ascii-art',
    '--precomputed-tables-path', TABLES_DIR,
]

print("spawning:", args)
t0 = time.time()
proc = winpty.PtyProcess.spawn(args)
print(f"[+{time.time()-t0:.1f}s] spawned, pid={proc.pid}, isalive={proc.isalive()}")
print("opened, waiting for output...")

total_bytes = 0
last_output = time.time()
try:
    while True:
        chunk = proc.read(4096)  # NOTE: this call is BLOCKING in this diagnostic on purpose --
                                  # we want to see exactly how long it blocks, not hide that behind a timeout
        now = time.time()
        if not chunk:
            print(f"[+{now-t0:.1f}s] read() returned empty -- process likely ended")
            break
        total_bytes += len(chunk)
        gap = now - last_output
        last_output = now
        preview = repr(chunk)[:200]
        print(f"[+{now-t0:.1f}s] (gap {gap:.1f}s) +{len(chunk)}b (total {total_bytes}b): {preview}")
        if now - t0 > 120:
            print("hit 120s cap, stopping diagnostic (this is just a safety limit, not a verdict)")
            break
except Exception as e:
    print(f"[+{time.time()-t0:.1f}s] EXCEPTION during read: {type(e).__name__}: {e}")
finally:
    # `finally` (not just the `except Exception` above) specifically so Ctrl+C -- a KeyboardInterrupt,
    # which does NOT subclass Exception -- still reaches this cleanup. Confirmed live 2026-09-23: without
    # this, interrupting the diagnostic left xelis_wallet.exe running and holding a file lock, which then
    # made the next `app\main.py` launch fail with "[WinError 5] Access is denied" trying to replace the
    # binary. Whoever's driving this script by hand will very likely Ctrl+C it once they've seen enough.
    print(f"\nfinal: isalive={proc.isalive()}, total bytes read={total_bytes}, elapsed={time.time()-t0:.1f}s")
    try:
        proc.terminate(force=True)
    except Exception:
        pass
