"""Hash'n'Omletz Xelis Wallet GUI -- a thin, verified wrapper around the UNMODIFIED official xelis_wallet
binary (same BSD-3 project/release as the sibling xelis/miner-gui, reusing its exact GPG+SHA256
verification chain -- see verify.py). Built for hobby miners who are used to Windows GUIs and found the
official wallet's CLI-only interface (no commands, everything typed from memory) a real barrier to
getting started, per Jon's own account.

v1 scope: create/open a wallet, see your receiving address (to point pool payouts at) and balance, safely
back up your seed phrase once at creation (shown with a confirm checkbox before continuing -- losing it
means losing the funds forever, so this isn't skippable), and send/receive XEL (needed for real use --
verifying payouts and moving funds to an exchange -- before this ships publicly).

Send/receive uses `build_transaction`/`estimate_fees`/`list_transactions` RPC, confirmed against REAL
request/response shapes captured live 2026-09-23 against a funded devnet wallet (not just the docs) --
see send_transaction()'s docstring for the one real gotcha found doing that (a transient "invalid
reference" error on a just-mined tip, retried automatically).

Threading rule (same as the Rigel and Xelis miner GUIs, learned the hard way on Windows/WebView2): NEVER
call window.evaluate_js() from a thread we spawn ourselves. Python never pushes; JS always polls."""
import json
import os
import sys
import threading
import time

import webview

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import downloader
from verify import VerificationError
from wallet_manager import WalletError, WalletProcess

APP_DIR = os.path.join(os.path.expanduser("~"), ".hashnomletz-xelis-wallet")
WALLETS_DIR = os.path.join(APP_DIR, "wallets")
TABLES_DIR = os.path.join(APP_DIR, "tables")  # shared across ALL wallets -- the slow precomputed-table
                                               # generation must only ever happen once per machine, not
                                               # once per wallet (see wallet_manager.py's module docstring)
os.makedirs(WALLETS_DIR, exist_ok=True)
os.makedirs(TABLES_DIR, exist_ok=True)

DEFAULT_NETWORK = "mainnet"
DEFAULT_DAEMON_ADDRESS = "http://127.0.0.1:8080"  # NOT yet a real, publicly-reachable endpoint for
                                                    # outside miners -- see README. Editable in the UI,
                                                    # same reasoning as the Rigel GUI's pool-URL field.

XEL_DECIMALS = 8
NATIVE_ASSET = "0" * 64  # confirmed live: the native XEL asset ID for transfers/estimate_fees -- unlike
                          # get_balance, this field does NOT accept null/None (confirmed live: raises
                          # "invalid type: null, expected a string")


def _xel_to_atomic(amount_xel) -> int:
    return int(round(float(amount_xel) * (10 ** XEL_DECIMALS)))


def _atomic_to_xel(amount_atomic) -> float:
    return amount_atomic / (10 ** XEL_DECIMALS)


def _safe_wallet_name(name: str) -> str:
    name = "".join(c for c in name.strip() if c.isalnum() or c in "-_")
    if not name:
        raise ValueError("wallet name must contain at least one letter, number, - or _")
    return name


class Api:
    def __init__(self):
        self.wallet: WalletProcess | None = None
        self.current_name: str | None = None
        self.release_info: dict | None = None
        self.verify_failed: str | None = None
        self._log_lines: list[str] = []
        self._log_lock = threading.Lock()

    def _log(self, msg: str):
        with self._log_lock:
            self._log_lines.append(msg)

    def check_or_download_wallet(self):
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

    def list_wallets(self):
        if not os.path.isdir(WALLETS_DIR):
            return []
        return sorted(d for d in os.listdir(WALLETS_DIR) if os.path.isdir(os.path.join(WALLETS_DIR, d)))

    def open_wallet(self, name, password, network, daemon_address, offline, is_new):
        if not self.release_info:
            return {"ok": False, "error": "wallet binary not verified yet"}
        try:
            name = _safe_wallet_name(name)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        wallet_dir = os.path.join(WALLETS_DIR, name)
        existed_before = os.path.isdir(wallet_dir)
        if is_new and existed_before:
            return {"ok": False, "error": f"a wallet named '{name}' already exists"}
        if not is_new and not existed_before:
            return {"ok": False, "error": f"no wallet named '{name}' found"}

        try:
            if self.wallet and self.wallet.is_running():
                self.wallet.stop()
            self.wallet = WalletProcess(self.release_info["binary_path"], TABLES_DIR)
            self.wallet.open(wallet_dir, password, network or DEFAULT_NETWORK, daemon_address or DEFAULT_DAEMON_ADDRESS, bool(offline))
            self.current_name = name
            return {"ok": True, "address": self.wallet.address, "is_new": is_new}
        except WalletError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def reveal_seed(self, password):
        if not self.wallet or not self.wallet.is_running():
            return {"ok": False, "error": "no wallet open"}
        try:
            seed = self.wallet.reveal_seed(password)
            return {"ok": True, "seed": seed}
        except WalletError as e:
            return {"ok": False, "error": str(e)}

    def close_wallet(self):
        if self.wallet:
            self.wallet.stop()
        self.wallet = None
        self.current_name = None
        return True

    def get_status(self):
        if not self.wallet or not self.wallet.is_running():
            return {"open": False}
        # Each RPC call fails independently rather than one try/except around all three -- confirmed
        # live 2026-09-23 (Windows) that get_topoheight legitimately errors on a brand-new wallet with no
        # chain data yet ("Error while loading data with hashed key TOPH from disk"), which is expected,
        # not a real fault. Bundling all three in one try meant that one benign, expected error would
        # have blanked the ENTIRE status display (balance, online, everything) instead of just leaving
        # topoheight unset while the rest still shows correctly.
        result = {"open": True, "name": self.current_name, "address": self.wallet.address}
        for key, method, params in (
            ("balance", "get_balance", {"asset": None}),
            ("topoheight", "get_topoheight", None),
            ("online", "is_online", None),
        ):
            try:
                result[key] = self.wallet.rpc_call(method, params)
            except Exception as e:
                result[key] = None
                result.setdefault("errors", {})[key] = str(e)
        return result

    def estimate_fee(self, to_address, amount_xel):
        # Confirmed live 2026-09-23 (Windows): this hadn't validated the address prefix the way
        # send_transaction() does, so a partial/placeholder address typed while testing (no real
        # recipient handy) hit the raw RPC call and threw -- combined with the app.js display bug this
        # was found alongside (fee preview collapsed any failure into the same '—' as "nothing typed
        # yet"), that made a real, surfaced error look like total silence. Fixed on both ends.
        if not self.wallet or not self.wallet.is_running():
            return {"ok": False, "error": "no wallet open"}
        to_address = to_address.strip()
        if not to_address.startswith(("xel:", "xet:")):
            return {"ok": False, "error": "that doesn't look like a valid Xelis address"}
        try:
            atomic = _xel_to_atomic(amount_xel)
        except (ValueError, TypeError):
            return {"ok": False, "error": "invalid amount"}
        if atomic <= 0:
            return {"ok": False, "error": "enter an amount greater than 0"}
        try:
            fee = self.wallet.rpc_call("estimate_fees", {"transfers": [
                {"amount": atomic, "asset": NATIVE_ASSET, "destination": to_address}
            ]})
            return {"ok": True, "fee": fee, "fee_xel": _atomic_to_xel(fee)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_transaction(self, to_address, amount_xel):
        """Confirmed live 2026-09-23 against a real funded devnet wallet: a freshly-mined tip can be
        briefly too new to reference ("transaction has an invalid reference: block height X is higher
        than stable height Y") -- this is the daemon's own finality-depth check (a fixed confirmation
        window, not a bug), and it self-resolves within seconds on a live, continuously-mining network
        (proven: identical params succeeded moments later with zero code changes, once more blocks had
        landed). Retried automatically rather than failing a legitimate send on this transient window."""
        if not self.wallet or not self.wallet.is_running():
            return {"ok": False, "error": "no wallet open"}
        to_address = to_address.strip()
        if not to_address.startswith(("xel:", "xet:")):
            return {"ok": False, "error": "that doesn't look like a valid Xelis address"}
        try:
            atomic = _xel_to_atomic(amount_xel)
        except (ValueError, TypeError):
            return {"ok": False, "error": "invalid amount"}
        if atomic <= 0:
            return {"ok": False, "error": "enter an amount greater than 0"}

        params = {
            "transfers": [{"amount": atomic, "asset": NATIVE_ASSET, "destination": to_address}],
            "broadcast": True,
        }
        last_err = None
        for _ in range(5):
            try:
                result = self.wallet.rpc_call("build_transaction", params)
                return {"ok": True, "hash": result.get("hash"), "fee": result.get("fee"), "fee_xel": _atomic_to_xel(result.get("fee", 0))}
            except WalletError as e:
                last_err = str(e)
                if "invalid reference" in last_err.lower():
                    time.sleep(2)
                    continue
                break
        return {"ok": False, "error": last_err}

    def get_transactions(self, limit=25):
        if not self.wallet or not self.wallet.is_running():
            return {"ok": False, "error": "no wallet open"}
        try:
            raw = self.wallet.rpc_call("list_transactions", {"limit": limit})
        except Exception as e:
            return {"ok": False, "error": str(e)}

        txs = []
        for tx in raw:
            kind = next((k for k in ("incoming", "outgoing", "coinbase", "burn") if k in tx), "other")
            payload = tx.get(kind, {}) or {}
            entry = {"hash": tx.get("hash"), "timestamp": tx.get("timestamp"), "topoheight": tx.get("topoheight"), "kind": kind}
            if kind == "incoming":
                entry["counterparty"] = payload.get("from")
                entry["amount_xel"] = _atomic_to_xel(sum(t.get("amount", 0) for t in payload.get("transfers", [])))
            elif kind == "outgoing":
                entry["counterparty"] = ", ".join(t.get("destination", "") for t in payload.get("transfers", []))
                entry["amount_xel"] = _atomic_to_xel(sum(t.get("amount", 0) for t in payload.get("transfers", [])))
                entry["fee_xel"] = _atomic_to_xel(payload.get("fee", 0))
            elif kind == "coinbase":
                entry["counterparty"] = "mining reward"
                entry["amount_xel"] = _atomic_to_xel(payload.get("reward", 0))
            else:
                entry["counterparty"] = kind
                entry["amount_xel"] = None
            txs.append(entry)
        return {"ok": True, "transactions": txs}


def main():
    api = Api()
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    window = webview.create_window(
        "Hash'n'Omletz — Xelis Wallet", os.path.join(web_dir, "index.html"),
        js_api=api, width=780, height=680, min_size=(620, 560), background_color="#010701",
    )
    # Confirmed live 2026-09-23 (Windows): closing the window via the X button without first clicking
    # "Close Wallet" leaves the wallet subprocess (and on Windows, its file lock on xelis_wallet.exe)
    # orphaned -- same class of bug as tests/diag_pty_windows.py's Ctrl+C gap, but in the shipped app,
    # where most users quit via the window chrome rather than an explicit in-app button.
    window.events.closing += api.close_wallet
    webview.start(debug=os.environ.get("WALLET_GUI_DEBUG") == "1")


if __name__ == "__main__":
    main()
