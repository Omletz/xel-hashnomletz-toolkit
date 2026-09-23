"""Launches/stops the verified official xelis_wallet binary and drives it two ways at once:

1. Its HTTP JSON-RPC server (--rpc-bind-address) for all normal operations -- address, balance,
   transaction history, sending funds. Clean, structured, no terminal parsing needed.
2. Its interactive terminal prompt, over a real pseudo-terminal via pexpect, for the ONE thing that
   is deliberately NOT exposed over RPC: revealing the seed phrase. Confirmed live 2026-09-23 by
   grepping the real binary's own command list (`xelis_common::prompt::command`) -- there is no RPC
   method for it anywhere in the project's own API.md, and the interactive `seed` command re-prompts
   for the wallet password before showing it. That is a deliberate security boundary in the wallet
   itself (a locally-listening RPC port should not be able to leak the master secret), not an
   oversight, and this wrapper preserves it rather than working around it.

Both interfaces run on the SAME process: xelis_wallet's interactive prompt and its RPC server are not
mutually exclusive (confirmed live -- the interactive command list itself includes start_rpc_server,
meaning both were designed to coexist). So one subprocess, driven two ways.

Real, confirmed facts about the interactive prompt (2026-09-23, live testing, not guessed):
- It redraws its whole status line (a live "XELIS Wallet | <addr> | TopoHeight | Balance | Online/Offline"
  bar) on every keystroke using raw ANSI cursor-up + clear-line codes, not plain line-buffered output.
  A naive `expect('>>')` match fires on nearly every redraw frame (mid-typing included), not just when
  a command has actually finished -- so this uses a "quiet period" drain (no new bytes for N seconds)
  for generic synchronization, and specific substring markers ("Password:", "Seed:",
  "Press ENTER to continue") for the seed-reveal flow specifically, which is more deterministic.
- First-ever wallet creation (or first-ever run on a machine with no cached tables) triggers a slow,
  CPU-heavy "generating precomputed tables" step (confirmed: pegs ~4-12 cores, real wall-clock minutes
  depending on hardware) before the wallet even opens. --precomputed-tables-path must be pinned to a
  persistent app-data directory so this only ever happens once per machine, not once per wallet.
  Do NOT let a user tune --precomputed-tables-l1 down to "speed this up" -- confirmed live that a too-small
  value (e.g. 1) crashes the binary outright with an internal panic ("Cuckoo hashmap insert needs
  rehashing"). Always use the binary's own default.
"""
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request

import pty_compat

STARTUP_QUIET_SECS = 1.5
STARTUP_MAX_WAIT = 180  # generous: covers a cold, uncached precomputed-table generation
COMMAND_QUIET_SECS = 1.2
COMMAND_MAX_WAIT = 20
# The step between entering the seed-reveal password and the 'Seed: ...' line appearing has a real,
# variable pause (confirmed live: consistently exceeded a 2.0s quiet threshold under load on this box,
# even though the wallet itself wasn't stuck -- just slower to redraw than the 2s cutoff assumed).
# Generous on purpose: a false "wrong password" from cutting off too early is a much worse failure mode
# here than waiting a few extra seconds, since it's the one flow that touches the actual secret.
SEED_REVEAL_QUIET_SECS = 4.0
SEED_REVEAL_MAX_WAIT = 30


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)


class WalletError(Exception):
    pass


class WalletProcess:
    """One running (or stopped) xelis_wallet subprocess, driven via pexpect (interactive prompt, PTY)
    and plain HTTP (RPC server on a random localhost port). Not thread-safe across instances, fine for
    a single GUI window controlling one open wallet at a time."""

    def __init__(self, binary_path: str, tables_dir: str):
        self.binary_path = binary_path
        self.tables_dir = tables_dir
        self.child = None
        self.rpc_port: int | None = None
        self.rpc_user: str | None = None
        self.rpc_pass: str | None = None
        self.address: str | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self.child is not None and self.child.isalive()

    def _drain_until_quiet(self, quiet_secs: float, max_wait: float) -> str:
        buf = ""
        last_data = time.time()
        start = time.time()
        while time.time() - start < max_wait:
            try:
                buf += self.child.read_nonblocking(size=4096, timeout=0.3)
                last_data = time.time()
            except Exception as e:
                if pty_compat.is_timeout_exception(e):
                    if time.time() - last_data >= quiet_secs:
                        break
                elif pty_compat.is_eof_exception(e):
                    break
                else:
                    raise
        return buf

    def open(self, wallet_dir: str, password: str, network: str, daemon_address: str, offline: bool):
        """Opens an existing wallet, or creates a new one if wallet_dir doesn't exist yet (confirmed
        live: xelis_wallet auto-creates when --wallet-path points at a non-existent directory, no
        separate 'create' flag needed). Raises WalletError on failure (e.g. wrong password against an
        existing wallet -- NOTE: that specific failure path is not yet verified live, see README)."""
        if self.is_running():
            raise RuntimeError("already running")

        os.makedirs(self.tables_dir, exist_ok=True)
        # confirmed live: xelis_wallet requires this path to end with a separator, rejects it otherwise
        # ("Error: Path for precomputed tables must ends with / or \") -- os.path.join never adds one
        tables_path = self.tables_dir if self.tables_dir.endswith(os.sep) else self.tables_dir + os.sep
        self.rpc_port = _free_port()
        self.rpc_user = os.urandom(8).hex()
        self.rpc_pass = os.urandom(16).hex()

        args = [
            self.binary_path,
            "--wallet-path", wallet_dir,
            "--password", password,
            "--network", network,
            "--disable-ascii-art",
            "--precomputed-tables-path", tables_path,
            "--rpc-bind-address", f"127.0.0.1:{self.rpc_port}",
            "--rpc-username", self.rpc_user,
            "--rpc-password", self.rpc_pass,
        ]
        if offline:
            args.append("--offline-mode")
        else:
            args += ["--daemon-address", daemon_address]

        self.last_error = None
        self.child = pty_compat.spawn(self.binary_path, args[1:], timeout=STARTUP_MAX_WAIT, encoding="utf-8", codec_errors="replace")

        startup = self._drain_until_quiet(STARTUP_QUIET_SECS, STARTUP_MAX_WAIT)
        clean = _strip_ansi(startup)
        if not self.is_running():
            self.last_error = clean.strip()[-500:] or "wallet process exited during startup"
            raise WalletError(self.last_error)

        # wait for the RPC server to actually come up before declaring success
        for _ in range(50):
            if self._rpc_ping():
                break
            time.sleep(0.2)
        else:
            self.last_error = "RPC server never came up"
            self.stop()
            raise WalletError(self.last_error)

        try:
            self.address = self.rpc_call("get_address")
        except Exception:
            self.address = None

    def reveal_seed(self, password: str) -> str:
        """Drives the interactive `seed` command. Confirmed live flow: send 'seed', it re-prompts for
        the wallet password (a deliberate security gate -- see module docstring), then prints a single
        'Seed: <words...>' line, then 'Press ENTER to continue' which must be dismissed. Confirmed live
        that a wrong password here returns silently to the normal prompt with no 'Seed:' line -- this
        correctly raises WalletError rather than mistaking it for a still-loading response."""
        if not self.is_running():
            raise WalletError("wallet is not open")
        with self._lock:
            self.child.send("seed\r")
            r1 = _strip_ansi(self._drain_until_quiet(COMMAND_QUIET_SECS, COMMAND_MAX_WAIT))
            if "Password:" not in r1:
                raise WalletError("did not see the expected password re-prompt after 'seed'")

            self.child.send(password + "\r")
            r2 = _strip_ansi(self._drain_until_quiet(SEED_REVEAL_QUIET_SECS, SEED_REVEAL_MAX_WAIT))
            m = re.search(r"Seed:\s*(.+)", r2)
            if not m:
                raise WalletError("did not see a 'Seed: ...' line after entering the password -- wrong password?")
            seed = m.group(1).strip()

            # dismiss the "Press ENTER to continue" gate so the prompt is usable again
            self.child.send("\r")
            self._drain_until_quiet(COMMAND_QUIET_SECS, COMMAND_MAX_WAIT)
            return seed

    def stop(self):
        """Kills the whole process tree, not just the one PID pexpect gave us -- same lesson learned the
        hard way on the Rigel miner GUI (its own internal watchdog left an orphaned child alive on
        Windows after a plain terminate()); applying that fix proactively here rather than waiting to
        rediscover the same bug."""
        if not self.child:
            return
        pid = self.child.pid
        if self.child.isalive():
            if os.name == "nt":
                # taskkill /T walks the real process tree by PID and force-kills it -- plain
                # terminate()/kill() only signal the single tracked PID (see the Rigel GUI's stop() for
                # the exact failure mode this avoids).
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                # the pty gives this child its own session (standard PTY semantics), so killpg reaches
                # the whole tree the same way it does for the Rigel GUI's process-group kill.
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                self.child.wait()
            except Exception:
                pass
            if self.child.isalive() and os.name != "nt":
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.child = None
        self.address = None

    # --- RPC (see rpc_call for the confirmed endpoint/auth shape) ---

    def _rpc_ping(self) -> bool:
        try:
            self.rpc_call("get_version")
            return True
        except Exception:
            return False

    def rpc_call(self, method: str, params=None):
        if not self.rpc_port:
            raise WalletError("RPC server not started")
        url = f"http://127.0.0.1:{self.rpc_port}/json_rpc"
        body = json.dumps({"jsonrpc": "2.0", "method": method, "id": 1, **({"params": params} if params is not None else {})}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        if self.rpc_user:
            import base64
            auth = base64.b64encode(f"{self.rpc_user}:{self.rpc_pass}".encode()).decode()
            req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode())
        if "error" in result:
            raise WalletError(f"RPC {method} failed: {result['error']}")
        return result.get("result")
