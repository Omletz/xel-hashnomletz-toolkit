"""Launches/stops the verified official Rigel binary and polls its own HTTP API for live stats. Never
runs anything that hasn't passed downloader.download_and_verify(). Unlike the Xelis miner GUI (locked to
one coin + our own getwork bridge), Rigel is a generic multi-algo, multi-pool miner: the user picks the
algorithm from Rigel's own supported list (algorithms.py) and types in whichever pool URL they want --
our pool or someone else's.

Rigel's `--api-bind` JSON shape is confirmed live (2026-09-23, real Rigel v1.23.2, RTX 3080 Ti, mining
xelishashv3 to our own pool) -- see summarize() below for the real, observed field names. It's keyed by
algorithm name throughout (a device can dual/triple mine), so summarize() picks out the numbers for the
single algorithm this GUI session is running."""
import json
import os
import signal
import socket
import subprocess
import threading
import urllib.request

# Tried in order; first one that returns valid JSON wins for the rest of this process's life. "/" is the
# confirmed real endpoint; "/api/v1/status" is kept as a fallback in case a future Rigel version moves it.
_STATS_PATHS = ("/", "/api/v1/status")


def summarize(raw: dict, algo: str) -> dict:
    """Flattens Rigel's real --api-bind response (confirmed live, 2026-09-23) into the shape the UI wants.
    `pool_hashrate` is what the pool is actually crediting (what counts toward payout); `hashrate` is
    Rigel's own self-reported figure, shown as a secondary comparison. Solution stats and pool latency
    come from the top-level aggregate (same numbers as the per-pool entry for a single-pool setup)."""
    if not raw:
        return {}
    sol = (raw.get("solution_stat") or {}).get(algo, {})
    pool_entries = (raw.get("pools") or {}).get(algo) or []
    latency = pool_entries[0].get("average_latency_ms") if pool_entries else None

    devices = []
    for d in raw.get("devices", []):
        mon = d.get("monitoring_info") or {}
        d_sol = (d.get("solution_stat") or {}).get(algo, {})
        devices.append({
            "name": d.get("name"),
            "state": d.get("state"),
            "hashrate": (d.get("hashrate") or {}).get(algo),
            "pool_hashrate": (d.get("pool_hashrate") or {}).get(algo),
            "accepted": d_sol.get("accepted"),
            "rejected": d_sol.get("rejected"),
            "invalid": d_sol.get("invalid"),
            "core_temp": mon.get("core_temperature"),
            "mem_temp": mon.get("memory_temperature"),
            "fan_speed": mon.get("fan_speed"),
            "power_usage": mon.get("power_usage"),
            "core_clock": mon.get("core_clock"),
            "core_clock_offset": mon.get("core_clock_offset"),
            "memory_clock": mon.get("memory_clock"),
            "memory_clock_offset": mon.get("memory_clock_offset"),
        })

    return {
        "hashrate_self": (raw.get("hashrate") or {}).get(algo),
        "hashrate_pool": (raw.get("pool_hashrate") or {}).get(algo),
        "accepted": sol.get("accepted"),
        "rejected": sol.get("rejected"),
        "invalid": sol.get("invalid"),
        "latency_ms": latency,
        "uptime": raw.get("uptime"),
        "devices": devices,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MinerProcess:
    """One running (or stopped) miner subprocess + its stats. Not thread-safe across instances, fine for
    a single GUI window controlling a single miner."""

    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.proc: subprocess.Popen | None = None
        self.api_port: int | None = None
        self.algo: str | None = None
        self._stats_path: str | None = None
        self.last_stats: dict = {}
        self.last_error: str | None = None
        self._stop_flag = threading.Event()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, algo: str, pool_url: str, username: str, password: str, worker: str, devices: str, work_dir: str):
        if self.is_running():
            raise RuntimeError("already running")
        if not algo:
            raise ValueError("select an algorithm")
        if not pool_url:
            raise ValueError("enter a pool URL, e.g. stratum+tcp://host:port")
        if not username:
            raise ValueError("enter a username / wallet address")

        self.api_port = _free_port()
        self.algo = algo
        self._stats_path = None
        args = [
            self.binary_path,
            "-a", algo,
            "-o", pool_url,
            "-u", username,
            "--api-bind", f"127.0.0.1:{self.api_port}",
            "--no-tui",
        ]
        if password:
            args += ["-p", password]
        if worker:
            args += ["-w", worker]
        if devices:
            args += ["-d", devices]

        self._stop_flag.clear()
        self.last_error = None
        self.last_stats = {}
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            args, cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),  # POSIX: own process group, so stop() can kill the whole tree
        )
        threading.Thread(target=self._watch_output, daemon=True).start()

    def _watch_output(self):
        proc = self.proc
        if not proc or not proc.stdout: return
        for line in proc.stdout:
            low = line.lower()
            if "error" in low or "fatal" in low:
                self.last_error = line.strip()

    def stop(self):
        """Kills the whole process tree, not just the one PID subprocess.Popen gave us. Rigel runs its own
        internal watchdog and -- confirmed live on Windows, 2026-09-23 -- can leave a separate child mining
        process running after that PID is terminated: the GUI reported "stopped" but the GPU kept mining
        until the leftover process was killed by hand in Task Manager. plain .terminate()/.kill() only
        signal the single PID (Win32 TerminateProcess doesn't touch children), so this reaches the whole
        tree instead: taskkill /T on Windows, the process group on POSIX (see start_new_session above)."""
        self._stop_flag.set()
        if not self.proc or self.proc.poll() is not None:
            self.proc = None
            return
        pid = self.proc.pid
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                self.proc.kill()
            else:
                try: os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError: pass
                try: self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired: pass
        self.proc = None

    def poll_stats(self) -> dict:
        if not self.is_running() or not self.api_port:
            return self.last_stats

        paths = (self._stats_path,) if self._stats_path else _STATS_PATHS
        for path in paths:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.api_port}{path}", timeout=2) as r:
                    data = json.loads(r.read().decode())
                self._stats_path = path
                self.last_stats = data
                return self.last_stats
            except Exception:
                continue
        return self.last_stats  # transient miss or API not up yet -- keep last known stats
