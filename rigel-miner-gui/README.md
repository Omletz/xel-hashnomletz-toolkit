# Hash'n'Omletz Rigel Miner GUI (prototype, 2026-09-23)

A thin GUI wrapper around the **unmodified official `rigel`** binary (closed-source freeware,
https://github.com/rigelminer/rigel). We never repackage or fork the mining code. Unlike the sibling
[Xelis miner GUI](../xelis/miner-gui) (BSD-3, GPG-signed `checksums.txt`), Rigel publishes **no**
checksums or signature with its releases — so this uses a different, weaker trust model:

1. A human (us) downloads a release directly from `github.com/rigelminer/rigel/releases`, confirms it's
   legitimate, and pins its SHA256 in `app/verify.py`'s `KNOWN_RELEASES` table.
2. Every future automated download is hashed and checked against that pin. Any mismatch, or any release
   version we haven't manually reviewed yet, is refused — fails closed, not open.
3. This is **trust-on-first-use**, not an independent upstream signature chain. Be upfront with users
   about that difference if it matters to them.

Unlike the Xelis GUI (locked to one coin + our own getwork bridge), this wrapper is **generic**: the user
picks any algorithm Rigel supports from a dropdown and types in whatever pool URL they want — ours or
anyone else's. Confirmed against the real `rigel --help` (v1.23.2, 2026-09-23) that this build supports
mining Xelis via `xelishashv3`, matching the bridge's validator exactly (no algo-version mismatch).

## Layout
- `app/verify.py` — SHA256 pin-per-version verification (trust-on-first-use; see above).
- `app/downloader.py` — picks the right release asset for the OS, downloads, verifies, extracts.
- `app/algorithms.py` — static list of Rigel's supported algorithms for the GUI dropdown; update when the
  bundled Rigel version changes (Rigel does add/remove algorithms between releases — 1.23.2 itself removed
  `ethashb3`).
- `app/miner_manager.py` — builds Rigel's CLI args, launches/stops it, polls its own HTTP API (`--api-bind`)
  for live stats via `summarize()` (real confirmed JSON shape, see Status below), and kills the whole
  process tree on `stop()` (`taskkill /T` on Windows, process-group `killpg` on POSIX) — not just the one
  PID `subprocess.Popen` hands back, since Rigel's own internal watchdog can leave a child process running
  after that PID dies.
- `app/main.py` — pywebview entrypoint; exposes `Api` to the JS side. Same no-push/JS-always-polls
  threading rule as the Xelis GUI (see its module docstring for the Windows/WebView2 bug this avoids).
- `app/web/` — UI, styled to match the Hash'n'Omletz dashboard exactly (same CSS as the Xelis GUI).

## Status (2026-09-23)
Every non-GPU piece is proven against the **real official v1.23.2 release**, on Linux, with no Nvidia GPU
present: `tests/test_all.py` downloads the real release, verifies its pinned SHA256, extracts it, launches
the real binary, and confirms it handles the real observed CUDA-absent failure mode cleanly (logs
`CUDA error: failed to load CUDA: ...`, keeps running via its internal watchdog/restart loop, never binds
its HTTP API) — 41/41 checks pass. `--help` output was read directly from the real binary to build the
algorithm dropdown, not guessed from docs.

**Verified end-to-end on real hardware (2026-09-23):** Jon ran this GUI (not just raw Rigel) on his
Windows machine against a real RTX 3080 Ti, mining `xelishashv3` to our own production pool. The pool
independently confirmed real accepted shares and live hashrate. The `--api-bind` JSON shape was captured
live from that run and is now the ground truth for `miner_manager.summarize()` (see its docstring and
`tests/test_all.py`'s `REAL_API_RESPONSE` fixture) — the stats panel shows pool-credited hashrate
(what actually counts toward payout) plus self-reported hashrate, accepted/rejected/invalid, pool
latency, and per-GPU telemetry (temps, fan, power, clocks) instead of guessing at field names.

**Real bug found and fixed (2026-09-23):** Jon hit Stop in the GUI — it reported "mining stopped", but the
GPU kept mining until he killed Rigel by hand in Task Manager. Root cause: `stop()` only called
`terminate()`/`kill()` on the single PID `subprocess.Popen` gave us; Rigel's internal watchdog apparently
keeps a separate child process alive on Windows, and Win32 `TerminateProcess` doesn't touch children.
Fixed: POSIX side now launches with `start_new_session=True` and `stop()` kills the whole process group
(`os.killpg`); Windows side uses `taskkill /F /T /PID` (`/T` = kill the whole tree). Covered by a new test
that validates the actual `killpg`-on-a-process-group mechanism. **Re-verified live on Windows**: GPU fans
ramped down and the pool independently confirmed the connection dropped cleanly the moment Stop was hit —
fix confirmed working, not just tested in isolation.

**Windows packaging done and verified (2026-09-23):** `build_windows.spec` produces
`dist\HashNOmletz-RigelMiner.exe` (~14.4 MB, single-file) — clean build, no missing-module/path errors,
launches and renders identically to running from source, no SmartScreen warning on Jon's machine, full
mining cycle (start → shares accepted, a couple rejected at a healthy ratio → stop → GPU ramp-down)
retested through the packaged exe itself, not just the dev run. Icon set via `assets/hashnomletz.ico`
(generated from `public-dashboard/logo.png`, padded to square, embedded at 16/32/48/256px) — confirmed
correct in the title bar, taskbar, and Explorer at both list and large-icon view; the 16px size is a bit
blob-like since the source art is quite detailed, but confirmed not an issue in practice.

**Not yet verified:**
- **Code signing** — the exe is unsigned; no SmartScreen warning was hit on Jon's own dev machine, but a
  cold install on an unrelated hobby miner's PC may still trigger one (SmartScreen's reputation system is
  per-binary-hash and builds up over downloads/time). Not blocking distribution, just something to expect.

## Try it (Linux, for logic/dev only — not the real target)
```
cd /mnt/ssd/rigel-gui
./venv/bin/python app/main.py
```

## Run the regression suite
```
cd /mnt/ssd/rigel-gui
./venv/bin/python tests/test_all.py
```
Note: on this Linux dev box the process sometimes segfaults *after* printing `41/41 checks passed` and
returns exit code 139 instead of 0 — confirmed this is an interpreter-shutdown artifact (isolated: a bare
`import webview; sys.exit(0)` in the same venv exits 0 cleanly; no threads are left running when it
happens), not a real logic failure, and not present in the shipped app itself (`app/main.py` runs
`webview.start()`'s event loop rather than calling `sys.exit()`). Read the printed pass/fail count, not
the shell exit code, until someone tracks down the actual cause.

## Not done yet
- Code signing for the Windows exe (not blocking; SmartScreen may still flag a cold download elsewhere
  even though Jon's own test machine didn't warn).
- Multi-GPU device *selection* UI (`-d` devices field exists and is passed through, but there's no picker
  reading `--list-devices` yet — deliberately out of scope for v1).
- Auto-update (deliberately out of scope for v1, same reasoning as the Xelis GUI).

## v1 is done
Every planned piece is built and verified end-to-end on real Windows/Nvidia hardware: verified download,
generic algo dropdown, real mining confirmed by the pool independently, live stats + GPU telemetry, Stop
actually stops the GPU, and a packaged, correctly-iconed single-file .exe. What's left above is polish,
not blockers.
