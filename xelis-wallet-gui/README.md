# Hash'n'Omletz Xelis Wallet GUI (prototype, 2026-09-23)

A thin GUI wrapper around the **unmodified official `xelis_wallet`** binary — same signed release as the
sibling [xelis/miner-gui](../miner-gui) project (`xelis-project/xelis-blockchain`, BSD-3), so it reuses
that project's exact GPG+SHA256 verification chain unchanged. We never repackage or fork the wallet code.

Built because the official wallet is CLI-only with no GUI, which was a real barrier for the hobby-miner
audience this pool targets (per Jon directly: "to figure anything out I had to look up commands... deep
down I'm a Windows user"). Scope: **create/open a wallet, see your receiving address (to point pool
payouts at) and balance, safely back up your seed phrase once at creation, and send/receive XEL** —
send was pulled in as a hard requirement before public release, specifically to verify pool payouts are
correct and move funds to an exchange. See "Send/receive" below for how thoroughly that's been tested.

## How it actually works
Two interfaces into the same `xelis_wallet` process, run at once:
1. **JSON-RPC** (`--rpc-bind-address`) for everything normal — address, balance, topoheight, online status,
   sending funds, transaction history. Confirmed live: `POST http://127.0.0.1:<port>/json_rpc`, HTTP Basic
   Auth, standard JSON-RPC 2.0 body.
2. **The interactive terminal prompt**, driven over a real pseudo-terminal (`pexpect` on POSIX, `pywinpty`
   on Windows — see `pty_compat.py`), for exactly one thing: revealing the seed phrase. Confirmed live by
   reading the real binary's own command list — there is **no RPC method for this anywhere** in the
   project's own bundled `API.md`. That's a deliberate security boundary in the wallet itself (a
   locally-listening RPC port shouldn't be able to leak the master secret), not an oversight, and this
   wrapper preserves it rather than working around it. The interactive `seed` command re-prompts for the
   wallet password before showing anything.

Both interfaces run on the same process — confirmed live, not assumed (the interactive command list
itself includes `start_rpc_server`, meaning the binary is designed for both to coexist).

## Real findings from live testing (2026-09-23), not guessed
- **First-ever wallet creation (or first run on a machine with no cached tables) triggers a slow, CPU-heavy
  "precomputed tables" generation** before the wallet even opens — confirmed live, pegs 4-12+ cores, real
  wall-clock minutes. `--precomputed-tables-path` is pinned to a shared app-data directory
  (`~/.hashnomletz-xelis-wallet/tables`) so this only ever happens once per machine, not once per wallet.
  **Never let a user tune `--precomputed-tables-l1` down "to speed this up"** — confirmed live that too
  small a value (e.g. `1`) crashes the binary outright with an internal panic ("Cuckoo hashmap insert
  needs rehashing"). Always use the binary's own default.
- **The interactive prompt redraws its whole live status line on every keystroke** using raw ANSI
  cursor-up + clear-line codes, not plain buffered output. A naive `expect('>>')` match fires on nearly
  every redraw frame (mid-typing included), and driving it over a **plain pipe** (no real pty) garbles
  input badly — confirmed live on the very first attempt (commands got interleaved into one corrupted
  line). A real pseudo-terminal fixed this completely.
- **The seed-reveal step has a real, variable pause** between the password redraw and the `Seed: ...` line
  actually appearing — confirmed live that a 2.0s "quiet period" cutoff was too aggressive under load on
  this box (looked like a wrong-password failure, wasn't). Uses a more generous 4.0s/30s timeout
  specifically for this one step — see `SEED_REVEAL_QUIET_SECS` in `wallet_manager.py`.
- **`--precomputed-tables-path` must end with a path separator** or the binary rejects it outright
  ("Error: Path for precomputed tables must ends with / or \\") — `os.path.join()` never adds one; this
  was a real bug caught by the automated test suite (`tests/test_all.py`), not manual testing.
- **A wrong password on seed-reveal fails silently and cleanly** — the prompt returns to normal with no
  `Seed:` line and no error text, which `reveal_seed()` correctly turns into a `WalletError` rather than
  a false-positive garbled result.

## Layout
- `app/verify.py`, `app/pubkey.py`, `app/downloader.py` — copied/adapted directly from the sibling
  xelis/miner-gui project (same release, same signature chain); only `downloader.py` changed, to extract
  `xelis_wallet` instead of `xelis_miner` from the shared archive.
- `app/wallet_manager.py` — process lifecycle, the RPC client, and the seed-reveal interactive-prompt
  state machine. Kills the whole process tree on `stop()` (`taskkill /T` / `killpg`), applying the same
  fix the Rigel miner GUI needed the hard way, proactively here instead of waiting to rediscover it.
- `app/pty_compat.py` — cross-platform pseudo-terminal spawn (`pexpect` POSIX / `pywinpty` Windows).
  Confirmed working live on both platforms — see "Windows PTY: resolved" below.
- `app/main.py` — pywebview entrypoint; exposes `Api` to the JS side, including `estimate_fee`,
  `send_transaction`, `get_transactions`. Same no-push/JS-always-polls threading rule as the sibling GUIs.
- `app/web/` — UI, styled to match the dashboard (same CSS as the other two GUIs). Wallet picker
  (create new / open existing, multiple named wallets — per Jon's explicit call), a tabbed wallet view
  (Overview / Send / History), and a seed-backup flow that's not skippable: shown once, requires a
  confirm checkbox before continuing, per Jon's explicit call.

## Send/receive: verified live end-to-end (2026-09-23)
Pulled in as a hard requirement before public release ("we absolutely need a send tab and transaction tab
... so we can transfer to exchanges and make sure payouts are right"). Given this moves real money, it was
tested against a **real, live devnet daemon** (reusing existing chain data on this box from earlier bridge
work), not just built against the docs and hoped to work:

- Stood up a real devnet daemon, created two fresh wallets, mined real blocks to fund one.
- **`estimate_fees`/`build_transaction`'s `asset` field does NOT accept `null`** (confirmed live: `"invalid
  type: null, expected a string"`) — unlike `get_balance`, where `null` is fine and defaults to native
  XEL. This would have been a silent bug if guessed by analogy instead of tested. The wrapper always
  sends the explicit zero-hash native asset ID (`NATIVE_ASSET` in `main.py`).
- **Executed a real transfer**: `build_transaction` with `broadcast: true`, and confirmed the recipient
  wallet's balance increased by exactly the sent amount once mined in (not just that the RPC call
  "succeeded" — the actual fund movement was verified).
- **Found and handled a real, structural daemon behavior**: a transaction can transiently fail with
  `"invalid reference: block height X is higher than stable height Y"` if built against a tip that hasn't
  accumulated enough confirmations yet. Confirmed this is NOT a bug or a sync-lag issue that clears with
  time — `stableheight` is a permanently fixed depth behind the tip (24 blocks in this test) that only
  advances as new blocks arrive, never just by waiting idle. On a live, continuously-mining network this
  resolves within seconds; `send_transaction()` retries automatically on this specific error rather than
  failing a legitimate send on the transient window (proven: identical params succeeded moments later with
  zero code changes, once background mining was running continuously instead of stopped after a burst).
- Verified `list_transactions`'s real response shapes for all three entry kinds seen (`coinbase`,
  `outgoing`, `incoming`) against the actual transaction from the test above — pinned as fixtures in
  `tests/test_all.py` so the parsing logic can't silently regress.

**Real bug found on the first Windows test of these tabs, fixed:** the fee preview silently collapsed
into the exact same `—` shown for "nothing typed yet" on ANY failure — bad address, bad amount, RPC
error, all of it — with zero logging anywhere, making a real, surfaced error indistinguishable from
total silence. Traced to two things: `app.js`'s `refreshFeePreview()` only checked `r.ok` and fell back
to the same placeholder either way (fixed: now shows the real error text, styled red, and logs it), and
`estimate_fee()` in `main.py` — unlike `send_transaction()` — never validated the address prefix, so a
partial/placeholder address (plausible if testing without a real recipient handy) hit the raw RPC call
and threw an unhelpful daemon error instead of a friendly one (fixed: same `xel:`/`xet:` prefix check
`send_transaction()` already had). Confirmed live: a technically-prefixed-but-incomplete address like
`xet:abc` still reaches the RPC layer and gets a real daemon error ("Invalid separator position: 3") —
that's now visible instead of vanishing, even though the prefix check alone won't catch every malformed
address. **Re-verified live on Windows, including through the packaged exe — confirmed working.**

## Status (2026-09-23)
31/31 checks pass in `tests/test_all.py` against the **real official v1.25.0 release**: download+verify
(same signature chain as the miner GUI, re-proven independently here), wallet auto-creates when the path
doesn't exist and reopens cleanly when it does, real RPC calls (`get_version`, `get_network`,
`get_address`, `get_balance`, `is_online`, error handling), the full seed-reveal flow end-to-end (wrong
password correctly rejected, correct password returns a real 25-word phrase, prompt and RPC both stay
usable afterward), and send/estimate-fee/transaction-history validation + parsing logic against real
captured fixtures (the live send/receive test itself is documented above, not re-run in the routine suite
since it needs a funded devnet wallet — expensive to redo every run). Uses `.testcache/` (gitignore this)
so the expensive precomputed-table generation only happens once on a given dev machine, not once per test
run.

## Windows PTY: resolved (2026-09-23)
`wexpect` (first attempt) was tested live on real Windows hardware and **confirmed broken**: the wallet
subprocess spawned and stayed alive (holding memory in Task Manager) but sat at 0% CPU indefinitely during
wallet creation — a true silent deadlock, never even reached seed-reveal. Switched to `pywinpty` (the
`winpty` package, a real ConPTY-backed library used in production by Jupyter/terminado), implemented with
a background-thread-feeds-a-queue wrapper (`app/pty_compat.py`'s `_WinPty`) specifically to avoid needing
to guess its exact non-blocking-read semantics. **Confirmed working live on real Windows hardware**: the
standalone diagnostic (`tests/diag_pty_windows.py`) streamed continuously with real interactive output, no
stall, and the full GUI flow succeeded end-to-end — wallet created, address/balance rendered, seed phrase
revealed cleanly (25 distinct correctly-spelled words, no garbling), confirm-checkbox gate worked, app
stayed responsive afterward.

Two unrelated dependency gaps had to be fixed to even get that far (both now pinned in
`requirements.txt`): Python 3.14 dropped the stdlib `imghdr` module that `pgpy` needs (`standard-imghdr`
fixes it), and setuptools 84+ dropped `pkg_resources` that `wexpect` needed (moot now that wexpect is
gone, kept as a note in case pywinpty ever hits something similar). The download/verify chain itself (GPG
+ SHA256) was confirmed working correctly on Windows from the very first attempt — never in question.

Two smaller things the Windows test session surfaced and got fixed:
- **Window-close cleanup was missing entirely.** Closing the app via the window's X button (rather than
  the in-app "Close Wallet" button) left the wallet subprocess running — same class of bug as the
  diagnostic script's Ctrl+C gap below, but in the shipped app, where most users quit via window chrome.
  Fixed: `main.py` now wires `window.events.closing` to `api.close_wallet`.
- **`get_status()` bundled three RPC calls in one try/except.** A benign, expected error on a brand-new
  wallet (`get_topoheight` failing with "no TOPH key in DB yet" — confirmed live, didn't affect the UI in
  practice, but was fragile) would have silently blanked the entire status display instead of just leaving
  that one field unset. Fixed: each of balance/topoheight/online now fails independently.
- `tests/diag_pty_windows.py`'s cleanup lived after its main loop, not in a `finally` — a Ctrl+C
  (`KeyboardInterrupt`, which doesn't subclass `Exception`) skipped it entirely, leaving `xelis_wallet.exe`
  running and holding a file lock that then broke the next `app\main.py` launch with
  `[WinError 5] Access is denied`. Fixed with a proper `finally` block.

## Windows packaging: DONE, confirmed live (2026-09-23)
First packaged build hit a real bug: wallet creation broke consistently only in the packaged exe (source
runs were fine), with raw ConPTY escape sequences (`\x1b[?9001h\x1b[?1004h`) leaking through as the error
text. Root cause confirmed against a documented, known PyInstaller+pywinpty gap: PyInstaller's DLL
import-table scanning bundles `conpty.dll`/`winpty.dll` but misses `OpenConsole.exe` (located via a
runtime string path, not a static import), and there's no `pyinstaller-hooks-contrib` hook to fill that
gap automatically. Fixed in `build_windows.spec` — it now explicitly bundles the winpty package's native
files into a `winpty/` subfolder inside the frozen exe (that exact folder name is load-bearing).

**Re-tested and confirmed working end-to-end through the packaged exe**: clean rebuild with no warnings
(this pywinpty version's file layout matched what the spec expected), wallet creation completes correctly,
address/balance render, seed-reveal works cleanly, and closing via the window's X button leaves no
orphaned `xelis_wallet.exe` process (confirmed in Task Manager) — the window-close cleanup fix holds up in
the packaged build too.

## Not yet verified
- **A publicly-reachable Xelis daemon RPC endpoint doesn't exist yet.** `xelis-daemon.service` (mainnet)
  runs persistently now (better than an earlier note suggesting it was a fragile transient unit — that's
  stale), but its RPC port (8080) is bound to `127.0.0.1` only. Hobby miners on their own machines can't
  sync a wallet against it as-is. The daemon-address field is left editable (same pattern as the Rigel
  GUI's pool-URL field) so the GUI isn't blocked on this, but exposing a public endpoint (mirroring how
  `stratum.hashnomletz.com` works for the pool) is a real infra decision needed before "online mode" is
  actually usable by anyone outside this box.
- Sending funds (v2, deliberately out of scope for v1 — see the top of this README).

## Try it (Linux, for logic/dev only — not the real target)
```
cd /mnt/ssd/xelis/wallet-gui
./venv/bin/python app/main.py
```

## Run the regression suite
```
cd /mnt/ssd/xelis/wallet-gui
./venv/bin/python tests/test_all.py
```

## Not done yet
- **Re-run the Windows packaging test now that Send/History tabs exist** — the last packaged-exe
  verification predates this addition (top priority before shipping, per how this was requested).
- Expose a public Xelis daemon RPC endpoint so "online mode"/sending actually works for miners outside
  this box, not just against a local/self-run daemon.
- Multiple assets / tracked-asset UI (XEL only — Xelis supports other on-chain assets via `track_asset`,
  out of scope until there's a reason to need it).
- Insufficient-balance UX: `build_transaction` will simply fail with a daemon error if the balance can't
  cover amount+fee; that error surfaces in the Send tab's error box as-is (not yet given a friendlier,
  purpose-built message).
