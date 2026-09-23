"""Hash'n'Omletz Rigel Miner GUI -- a thin, verified wrapper around the UNMODIFIED official Rigel binary.
We never repackage the mining binary: it's downloaded fresh from the project's own GitHub release and
checked against a pinned, manually-vetted SHA256 before it's ever executed (Rigel is closed-source and
publishes no checksums/signature of its own -- see verify.py for why this differs from the Xelis miner
GUI's GPG chain). Unlike that Xelis-only wrapper, this one is generic: the user picks any algorithm Rigel
supports and points it at any pool, ours or someone else's, so the same wrapper covers whatever GPU coin
gets added to the pool next.

Threading rule (carried over from the Xelis miner GUI, learned the hard way on Windows/WebView2): NEVER
call window.evaluate_js() from a thread we spawn ourselves -- pywebview's own js_api dispatch already runs
every pywebview.api.xxx() call on its own background thread and safely marshals the return value back
through evaluate_js's internal Windows-side wrapping. Calling evaluate_js() ourselves from our own thread
throws on Windows and destabilizes the webview for the rest of the session. So: Python NEVER pushes. JS
always polls."""
import json
import os
import sys
import threading

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import downloader
from algorithms import ALGORITHMS
from miner_manager import MinerProcess, summarize
from verify import VerificationError

APP_DIR = os.path.join(os.path.expanduser("~"), ".hashnomletz-rigel-miner")
os.makedirs(APP_DIR, exist_ok=True)
STATE_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "algo": "xelishashv3",
    "pool_url": "stratum+tcp://stratum.hashnomletz.com:13333",
    "username": "",
    "password": "x",
    "worker": "gui",
    "devices": "",
}


class Api:
    def __init__(self):
        self.miner: MinerProcess | None = None
        self.release_info: dict | None = None
        self.verify_failed: str | None = None
        self._log_lines: list[str] = []
        self._log_lock = threading.Lock()

    def _log(self, msg: str):
        with self._log_lock:
            self._log_lines.append(msg)

    def get_algorithms(self):
        return ALGORITHMS

    def load_settings(self):
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    return {**DEFAULT_SETTINGS, **json.load(f)}
            except Exception:
                pass
        return dict(DEFAULT_SETTINGS)

    def save_settings(self, settings: dict):
        with open(STATE_PATH, "w") as f:
            json.dump(settings, f, indent=2)
        return True

    def check_or_download_miner(self):
        """Kicks off the download+verify in the background and returns immediately. JS polls
        get_verify_status() for progress and the final result -- see the threading rule above."""
        def worker():
            try:
                info = downloader.download_and_verify(APP_DIR, progress_cb=self._log)
                self.release_info = info
            except VerificationError as e:
                self._log(f"VERIFICATION FAILED: {e}")
                self.verify_failed = str(e)
            except Exception as e:
                self._log(f"error: {e}")
                self.verify_failed = str(e)
        threading.Thread(target=worker, daemon=True).start()
        return True

    def get_verify_status(self):
        with self._log_lock:
            log = list(self._log_lines)
        return {"verified": self.release_info is not None, "failed": self.verify_failed, "info": self.release_info, "log": log}

    def start_mining(self, algo, pool_url, username, password, worker, devices):
        if not self.release_info:
            return {"ok": False, "error": "miner not verified yet"}
        try:
            self.miner = MinerProcess(self.release_info["binary_path"])
            self.miner.start(algo.strip(), pool_url.strip(), username.strip(), password.strip(), worker.strip(), devices.strip(), APP_DIR)
            self.save_settings({
                "algo": algo, "pool_url": pool_url, "username": username,
                "password": password, "worker": worker, "devices": devices,
            })
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop_mining(self):
        if self.miner:
            self.miner.stop()
        return True

    def get_status(self):
        if not self.miner:
            return {"running": False, "stats": {}}
        raw = self.miner.poll_stats()
        stats = summarize(raw, self.miner.algo) if raw else {}
        return {"running": self.miner.is_running(), "stats": stats, "error": self.miner.last_error}


def main():
    api = Api()
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    webview.create_window(
        "Hash'n'Omletz — Rigel Miner", os.path.join(web_dir, "index.html"),
        js_api=api, width=780, height=680, min_size=(620, 560), background_color="#010701",
    )
    webview.start(debug=os.environ.get("MINER_GUI_DEBUG") == "1")


if __name__ == "__main__":
    main()
