"""Regression suite for the Xelis wallet GUI's non-visual logic (download/verify, wallet create/open,
RPC, seed-reveal). Run: /mnt/ssd/xelis/wallet-gui/venv/bin/python tests/test_all.py

Needs network (downloads the real official xelis_wallet release, same signed release as the sibling
xelis/miner-gui project). Uses .testcache/ as a persistent fixture directory (gitignore this) so the
slow, CPU-heavy precomputed-table generation (confirmed live: real wall-clock minutes, ~4-12 cores) only
ever happens once on a given machine, not once per test run -- matches how the shipped app itself is
supposed to behave (see wallet_manager.py's module docstring)."""
import json, os, shutil, sys, tempfile, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
import downloader
from verify import VerificationError
from wallet_manager import WalletError, WalletProcess

pass_ = fail_ = 0
def check(name, cond, detail=''):
    global pass_, fail_
    if cond: pass_ += 1
    else: fail_ += 1
    print(('PASS ' if cond else 'FAIL ') + name + (f'  — {detail}' if detail else ''))

TESTCACHE = os.path.join(os.path.dirname(__file__), '..', '.testcache')
TABLES_DIR = os.path.join(TESTCACHE, 'tables')
os.makedirs(TABLES_DIR, exist_ok=True)

# --- downloader.py (real network, real official release -- same repo/signature chain proven in
# xelis/miner-gui's own test suite, re-proven here independently since this is a separate project)
tmp = tempfile.mkdtemp(prefix='xelis-wallet-gui-test-')
info = None
try:
    info = downloader.download_and_verify(tmp)
    check('download_and_verify returns a version/binary_path/sha256', all(k in info for k in ('version', 'binary_path', 'sha256')), info)
    check('extracted binary is xelis_wallet, not xelis_miner', os.path.basename(info['binary_path']).startswith('xelis_wallet'), info['binary_path'])
    check('extracted binary exists and is executable', os.path.exists(info['binary_path']) and os.access(info['binary_path'], os.X_OK))
except VerificationError as e:
    check('download_and_verify succeeds', False, str(e))

# --- wallet_manager.py (real process, real precomputed tables cached in .testcache for speed)
if info:
    binary_path = info['binary_path']
    wallet_dir = os.path.join(TESTCACHE, 'wallet1')
    is_first_run = not os.path.isdir(wallet_dir)

    wp = WalletProcess(binary_path, TABLES_DIR)
    try:
        t0 = time.time()
        wp.open(wallet_dir, 'testpass1234', 'devnet', '', offline=True)
        elapsed = time.time() - t0
        check('wallet opens (creates on first run, reopens after)', wp.is_running(), f'{elapsed:.1f}s, first_run={is_first_run}')
        check('address is populated after open (real xet:/xel:-style address)', bool(wp.address) and ':' in wp.address, wp.address)

        # --- RPC surface (confirmed live 2026-09-23: POST /json_rpc, HTTP Basic Auth, standard JSON-RPC 2.0)
        version = wp.rpc_call('get_version')
        check('RPC get_version returns a string', isinstance(version, str), version)
        network = wp.rpc_call('get_network')
        check('RPC get_network reflects the requested devnet', str(network).lower() == 'devnet', network)
        addr = wp.rpc_call('get_address')
        check('RPC get_address matches WalletProcess.address', addr == wp.address, (addr, wp.address))
        balance = wp.rpc_call('get_balance', {"asset": None})
        check('RPC get_balance returns a plain integer (atomic units)', isinstance(balance, int), balance)
        online = wp.rpc_call('is_online')
        check('RPC is_online reflects offline_mode=True', online is False, online)

        try:
            wp.rpc_call('does_not_exist_method')
            check('RPC error response raises WalletError', False, 'no exception raised')
        except WalletError:
            check('RPC error response raises WalletError', True)

        try:
            wp.reveal_seed('definitely-the-wrong-password')
            check('reveal_seed with the wrong password raises rather than returning garbage', False, 'no exception')
        except WalletError:
            check('reveal_seed with the wrong password raises rather than returning garbage', True)

        try:
            WalletProcess(binary_path, TABLES_DIR).reveal_seed('x')
        except WalletError:
            check('reveal_seed on a wallet that is not open raises WalletError', True)
        else:
            check('reveal_seed on a wallet that is not open raises WalletError', False, 'no exception')

    finally:
        wp.stop()
        time.sleep(1)
        check('wallet process stops cleanly', not wp.is_running())

    # --- seed-reveal success path (real interactive-prompt flow, confirmed live: 'seed' -> password
    # re-prompt -> 'Seed: <words>' -> 'Press ENTER to continue'). Uses a fresh throwaway wallet every run
    # (not the persistent fixture above) so this is exercised deterministically every time, not just on
    # a fixture's first-ever creation -- cheap now since the precomputed tables are already cached.
    throwaway_dir = os.path.join(tmp, 'seed_test_wallet')
    wp2 = WalletProcess(binary_path, TABLES_DIR)
    try:
        wp2.open(throwaway_dir, 'testpass1234', 'devnet', '', offline=True)
        seed = wp2.reveal_seed('testpass1234')
        words = seed.split()
        check('reveal_seed returns a real multi-word phrase', len(words) >= 12, f'{len(words)} words')
        check('wallet prompt is usable again after seed reveal (not stuck at the ENTER gate)', wp2.is_running())
        # RPC and the interactive prompt run on the SAME process concurrently -- prove RPC still responds
        # after driving the interactive channel, since that concurrency is the whole point of this design
        check('RPC still responds after driving the interactive seed flow', isinstance(wp2.rpc_call('get_version'), str))
    finally:
        wp2.stop()

    # --- validation before spawning
    try:
        WalletProcess(binary_path, TABLES_DIR).open('', 'x', 'devnet', '', True)
    except Exception:
        check('empty wallet_dir is rejected or fails cleanly, not a crash', True)
    else:
        check('empty wallet_dir is rejected or fails cleanly, not a crash', False, 'silently accepted')
else:
    check('wallet_manager tests skipped (no verified binary this run)', False, 'downloader step above did not produce one')

shutil.rmtree(tmp, ignore_errors=True)

# --- main.py's send/estimate_fee/get_transactions logic. The live send flow itself (real devnet daemon +
# funded wallet + mining to generate a spendable balance) was proven working end-to-end manually on
# 2026-09-23 -- see README's "Send/receive: verified live" section for that record; it's not re-run here
# since standing up a funded devnet wallet is expensive and this is meant to be a fast, routine suite.
# What IS covered here: the pure validation logic (no RPC needed) and get_transactions' parsing against
# REAL response shapes captured live during that manual test, pinned as fixtures below so this can't
# silently regress even without redoing the live setup.
import main as main_mod

class _FakeWallet:
    """Stands in for WalletProcess in Api tests that don't need a real process -- just enough surface
    for main.py's Api methods to call: is_running(), address, rpc_call()."""
    def __init__(self, rpc_responses=None):
        self.address = 'xet:faketest0000000000000000000000000000000000000000000000000000'
        self._responses = rpc_responses or {}
    def is_running(self):
        return True
    def rpc_call(self, method, params=None):
        if method not in self._responses:
            raise AssertionError(f'unexpected RPC call in fake wallet: {method}')
        return self._responses[method]

api = main_mod.Api()
check('estimate_fee/send_transaction/get_transactions with no wallet open all report that cleanly', all(
    r['ok'] is False and 'no wallet open' in r['error']
    for r in (api.estimate_fee('x', '1'), api.send_transaction('x', '1'), api.get_transactions())
))

api.wallet = _FakeWallet()
check('send_transaction rejects an address with no xel:/xet: prefix', api.send_transaction('not-an-address', '1')['error'] == "that doesn't look like a valid Xelis address")
check('send_transaction rejects a non-numeric amount', api.send_transaction('xet:abc', 'banana')['error'] == 'invalid amount')
check('send_transaction rejects a zero amount', api.send_transaction('xet:abc', '0')['error'] == 'enter an amount greater than 0')
check('send_transaction rejects a negative amount', api.send_transaction('xet:abc', '-3')['error'] == 'enter an amount greater than 0')
check('estimate_fee rejects a non-numeric amount the same way', api.estimate_fee('xet:abc', 'nope')['error'] == 'invalid amount')
# Regression test for the real bug found live 2026-09-23 (Windows): estimate_fee originally had no
# address-prefix check (unlike send_transaction), so a partial/placeholder address typed while testing
# hit the raw RPC call and threw -- combined with app.js collapsing any failure into the same '—' shown
# for "nothing typed yet" (also fixed), a real, surfaced error looked like total silence.
check('estimate_fee rejects an address with no xel:/xet: prefix, same as send_transaction', api.estimate_fee('not-an-address', '1')['error'] == "that doesn't look like a valid Xelis address")

check('_xel_to_atomic/_atomic_to_xel round-trip exactly (8 decimals)', main_mod._atomic_to_xel(main_mod._xel_to_atomic('1.23456789')) == 1.23456789)
check('_xel_to_atomic matches the real captured send: 0.02 XEL -> 2000000 atomic', main_mod._xel_to_atomic('0.02') == 2000000)
check('NATIVE_ASSET is the confirmed live zero-hash, not None (None was confirmed to be REJECTED by the RPC)', main_mod.NATIVE_ASSET == '0' * 64)

# real response shapes captured live 2026-09-23 from an actual devnet send between two real wallets
# (build_transaction -> hash ff9e603f... -> confirmed received by the recipient for the exact sent amount)
REAL_LIST_TRANSACTIONS = [
    {"hash": "44b1bdc756f8f0cab5a592dc64ec5dbf803a6558c2debd474494c7a1e5877c4f", "timestamp": 1790200950112, "topoheight": 846,
     "coinbase": {"reward": 43868035}},
    {"hash": "ff9e603fe0246d93b76a2d92204de969e37dec43a8a188fa1221854790289859", "timestamp": 1790200817600, "topoheight": 829,
     "outgoing": {"fee": 125000, "nonce": 0, "transfers": [
         {"amount": 5000000, "asset": "0" * 64, "destination": "xet:0ffut4rh8hxt2vtemn8n5fwp4jj92thkds3zucagaertz8ymhvysqngkypg", "extra_data": None}
     ]}},
]
REAL_LIST_TRANSACTIONS_INCOMING = [
    {"hash": "ff9e603fe0246d93b76a2d92204de969e37dec43a8a188fa1221854790289859", "timestamp": 1790200817600, "topoheight": 829,
     "incoming": {"from": "xet:uc2atvgmlvpvl3k8r8qw0vm8kkke5p8fjcv8jvs6fd7quqcks4nqq6fvk03", "transfers": [
         {"amount": 5000000, "asset": "0" * 64, "extra_data": None}
     ]}},
]

api.wallet = _FakeWallet({"list_transactions": REAL_LIST_TRANSACTIONS})
r = api.get_transactions()
check('get_transactions parses a real coinbase entry', r['ok'] and r['transactions'][0] == {
    'hash': '44b1bdc756f8f0cab5a592dc64ec5dbf803a6558c2debd474494c7a1e5877c4f', 'timestamp': 1790200950112,
    'topoheight': 846, 'kind': 'coinbase', 'counterparty': 'mining reward', 'amount_xel': 0.43868035
}, r['transactions'][0])
check('get_transactions parses a real outgoing entry (matches the actual live send)', r['transactions'][1] == {
    'hash': 'ff9e603fe0246d93b76a2d92204de969e37dec43a8a188fa1221854790289859', 'timestamp': 1790200817600,
    'topoheight': 829, 'kind': 'outgoing',
    'counterparty': 'xet:0ffut4rh8hxt2vtemn8n5fwp4jj92thkds3zucagaertz8ymhvysqngkypg',
    'amount_xel': 0.05, 'fee_xel': 0.00125
}, r['transactions'][1])

api.wallet = _FakeWallet({"list_transactions": REAL_LIST_TRANSACTIONS_INCOMING})
r2 = api.get_transactions()
check('get_transactions parses a real incoming entry (the same tx, seen from the recipient wallet)', r2['transactions'][0] == {
    'hash': 'ff9e603fe0246d93b76a2d92204de969e37dec43a8a188fa1221854790289859', 'timestamp': 1790200817600,
    'topoheight': 829, 'kind': 'incoming',
    'counterparty': 'xet:uc2atvgmlvpvl3k8r8qw0vm8kkke5p8fjcv8jvs6fd7quqcks4nqq6fvk03', 'amount_xel': 0.05
}, r2['transactions'][0])

print(f'\n{pass_}/{pass_+fail_} checks passed')
sys.exit(1 if fail_ else 0)
