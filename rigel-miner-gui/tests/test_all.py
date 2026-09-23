"""Regression suite for the Rigel miner GUI's non-visual logic (verification chain, download+extract,
process manager, Api class). Run: /mnt/ssd/rigel-gui/venv/bin/python tests/test_all.py

Needs network (downloads the real official Rigel release). This host has no Nvidia GPU, so the
miner_manager tests below prove process start/stop/error-capture against the REAL binary's REAL
CUDA-absent failure mode (observed directly: it logs "CUDA error: failed to load CUDA: ..." and never
binds its HTTP API), not a live mining/share-accepting path -- that needs a real GPU rig to verify."""
import json, os, signal, subprocess, sys, shutil, tempfile, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
import downloader, miner_manager
from verify import KNOWN_RELEASES, VerificationError, sha256_of, verify_release_asset

pass_ = fail_ = 0
def check(name, cond, detail=''):
    global pass_, fail_
    if cond: pass_ += 1
    else: fail_ += 1
    print(('PASS ' if cond else 'FAIL ') + name + (f'  — {detail}' if detail else ''))

# --- miner_manager.summarize() against a REAL --api-bind response, captured live 2026-09-23 from a real
# Rigel v1.23.2 mining xelishashv3 (RTX 3080 Ti) to our own production pool. This is ground truth, not a
# guess -- pins the exact field mapping so a future refactor can't silently break the stats display again.
REAL_API_RESPONSE = json.loads('''
{
  "name": "Rigel", "version": "1.23.2", "os_name": "Windows", "cuda_driver": "596.49", "uptime": 286,
  "algorithm": "xelishashv3", "watchdog": "on",
  "pools": {"xelishashv3": [{"id": 0, "connection_details": {"protocol": "stratum",
    "username": "xel:7zfts4pm0tjk8p753xgk8cxjh82cqzf7dxa0lyu9kj8vfshjgg8qq64p89f", "password": "x",
    "worker": "test", "hostname": "stratum.hashnomletz.com", "port": 13333, "ssl": false, "dns_mode": "system"},
    "state": {"issued_job": "16.00K"}, "solution_stat": {"accepted": 1405, "rejected": 0, "invalid": 0},
    "average_latency_ms": 29}]},
  "devices": [{"id": 0, "selected": true, "name": "RTX 3080 Ti", "total_mem": 12884246528,
    "pci_address": "0b:0", "state": "mining",
    "solution_stat": {"xelishashv3": {"accepted": 1405, "rejected": 0, "invalid": 0}},
    "monitoring_info": {"core_temperature": 72, "memory_temperature": 88, "fan_speed": 83,
      "power_usage": 294.36225, "core_clock": 1980, "core_clock_offset": 0, "memory_clock": 9251,
      "memory_clock_offset": 0},
    "hashrate": {"xelishashv3": 12112.195564915472}, "pool_hashrate": {"xelishashv3": 11388.111888111887},
    "dual_ratio": null, "tune": {"xelishashv3": null}, "crash_count": 0}],
  "solution_stat": {"xelishashv3": {"accepted": 1405, "rejected": 0, "invalid": 0}},
  "hashrate": {"xelishashv3": 12112.195564915472}, "pool_hashrate": {"xelishashv3": 11388.111888111887},
  "power_usage": 294.36225
}
''')

s = miner_manager.summarize(REAL_API_RESPONSE, "xelishashv3")
check('summarize picks pool_hashrate (payout-credited) as hashrate_pool', abs(s["hashrate_pool"] - 11388.111888111887) < 1e-6, s["hashrate_pool"])
check('summarize picks self-reported hashrate as hashrate_self', abs(s["hashrate_self"] - 12112.195564915472) < 1e-6, s["hashrate_self"])
check('summarize reads top-level solution_stat.accepted/rejected/invalid', (s["accepted"], s["rejected"], s["invalid"]) == (1405, 0, 0), s)
check('summarize reads pools.<algo>[0].average_latency_ms', s["latency_ms"] == 29, s["latency_ms"])
check('summarize reads top-level uptime', s["uptime"] == 286, s["uptime"])
check('summarize produces exactly one device entry', len(s["devices"]) == 1, s["devices"])
d = s["devices"][0] if s["devices"] else {}
check('device: name/state', (d.get("name"), d.get("state")) == ("RTX 3080 Ti", "mining"), d)
check('device: core/memory temperature from monitoring_info', (d.get("core_temp"), d.get("mem_temp")) == (72, 88), d)
check('device: fan_speed from monitoring_info', d.get("fan_speed") == 83, d)
check('device: power_usage from monitoring_info (not the duplicated document-root copy)', abs(d.get("power_usage") - 294.36225) < 1e-6, d)
check('device: core/memory clock + offsets from monitoring_info', (d.get("core_clock"), d.get("core_clock_offset"), d.get("memory_clock"), d.get("memory_clock_offset")) == (1980, 0, 9251, 0), d)
check('device: per-device pool_hashrate matches the document-root figure for this single-device rig', abs(d.get("pool_hashrate") - 11388.111888111887) < 1e-6, d)

check('summarize on empty/None raw returns {} (poll_stats degrades gracefully before any response)', miner_manager.summarize({}, "xelishashv3") == {} and miner_manager.summarize(None, "xelishashv3") == {})
check('summarize on an algo with no matching data returns None/empty fields rather than crashing', miner_manager.summarize(REAL_API_RESPONSE, "kawpow")["hashrate_pool"] is None)

# --- verify.py
tmp = tempfile.mkdtemp(prefix='rigel-gui-test-')
(version, asset_name), pinned_hash = next(iter(KNOWN_RELEASES.items()))

good_path = os.path.join(tmp, asset_name)
with open(good_path, 'wb') as f:
    f.write(b'x' * 1024)  # placeholder content; we don't need a real archive to test hash-matching logic
real_hash = sha256_of(good_path)
KNOWN_RELEASES_BACKUP = dict(KNOWN_RELEASES)
KNOWN_RELEASES[(version, asset_name)] = real_hash  # temporarily point the pin at our placeholder's real hash
try:
    got = verify_release_asset(good_path, version, asset_name)
    check('matching pinned hash verifies', got == real_hash, got)
finally:
    KNOWN_RELEASES.clear(); KNOWN_RELEASES.update(KNOWN_RELEASES_BACKUP)  # restore the real pins

try:
    verify_release_asset(good_path, version, asset_name)  # placeholder content no longer matches restored real pin
    check('tampered/mismatched content is rejected', False, 'accepted!')
except VerificationError:
    check('tampered/mismatched content is rejected', True)

try:
    verify_release_asset(good_path, '0.0.0-not-a-real-version', asset_name)
    check('unpinned (not-yet-reviewed) release is rejected', False, 'accepted!')
except VerificationError:
    check('unpinned (not-yet-reviewed) release is rejected', True)

# --- downloader.py (real network, real official release)
info = None
try:
    latest = downloader.fetch_release_info()
    latest_tag = latest['tag_name']
    if latest_tag in {v for (v, _) in KNOWN_RELEASES}:
        info = downloader.download_and_verify(tmp)
        check('download_and_verify returns a version/binary_path/sha256', all(k in info for k in ('version', 'binary_path', 'sha256')), info)
        check('extracted binary exists and is executable', os.path.exists(info['binary_path']) and os.access(info['binary_path'], os.X_OK))
        check('no leftover extracted directory clutter', sorted(os.listdir(tmp)) == [os.path.basename(info['binary_path'])], os.listdir(tmp))
        check('the downloaded archive itself was cleaned up after extraction', not any(f.endswith(('.tar.gz', '.zip')) for f in os.listdir(tmp)), os.listdir(tmp))
    else:
        # Rigel shipped a newer release than we've pinned -- correct behaviour is to refuse it, not download blindly.
        try:
            downloader.download_and_verify(tmp)
            check(f'unpinned newer release {latest_tag} is refused, not silently trusted', False, 'accepted!')
        except VerificationError:
            check(f'unpinned newer release {latest_tag} is refused, not silently trusted', True)
except Exception as e:
    check('downloader.py network path completes without a crash', False, str(e))

# --- miner_manager.py (real process; this host has no Nvidia GPU, so this proves start/stop/error-capture
# against Rigel's real, observed CUDA-absent failure mode, not a live share-accepting path)
if info:
    binary_path = info['binary_path']
    mp = miner_manager.MinerProcess(binary_path)
    try:
        mp.start('xelishashv3', 'stratum+tcp://127.0.0.1:13333', 'test', 'x', 'guitest', '', tmp)
        check('miner process starts', mp.is_running())
        time.sleep(3)
        check('process is still alive (watchdog keeps it up even after a CUDA-absent failure, observed live)', mp.is_running())
        check('CUDA-absent error is captured from stdout', mp.last_error is not None and 'cuda' in mp.last_error.lower(), mp.last_error)
        stats = mp.poll_stats()
        check('poll_stats degrades gracefully (empty dict) when the API never bound, no crash', stats == {}, stats)
    finally:
        mp.stop()
        time.sleep(1)
        check('process stops cleanly', not mp.is_running())

    # Regression test for the real bug found 2026-09-23: stop() must kill the WHOLE process tree, not just
    # the one PID subprocess.Popen gave us. Confirmed live on Windows -- Rigel's internal watchdog left a
    # separate child process mining after the GUI reported "stopped" (GPU kept running until killed by hand
    # in Task Manager). This can't literally reproduce Rigel's own Windows-specific watchdog/child behaviour
    # from a Linux unit test, but it does validate the actual primitive stop()'s POSIX branch relies on:
    # os.killpg reaping a whole process group, not just the process we happen to hold a Popen handle to.
    # (A naive attempt to setpgid a second, unrelated Popen into an existing group fails with EPERM --
    # POSIX forbids joining a process group in a different session -- so this uses a parent that spawns a
    # same-group child naturally instead, exactly how a real watchdog's child would inherit the group.)
    if os.name != 'nt':
        parent = subprocess.Popen(['bash', '-c', 'sleep 30 & wait'], start_new_session=True)
        try:
            time.sleep(0.3)
            pgid = os.getpgid(parent.pid)
            members = subprocess.run(['pgrep', '-g', str(pgid)], capture_output=True, text=True).stdout.split()
            check('simulated parent + its spawned child share one process group (child inherits it, no setsid)', str(parent.pid) in members and len(members) >= 2, members)
            os.killpg(pgid, signal.SIGKILL)
            try: parent.wait(timeout=2)  # reap the parent so it doesn't linger as a zombie and skew the pgrep check below
            except subprocess.TimeoutExpired: pass
            time.sleep(0.3)
            still_alive = subprocess.run(['pgrep', '-g', str(pgid)], capture_output=True, text=True).stdout.split()
            check("killpg (stop()'s actual POSIX mechanism) kills the whole group -- parent AND child -- not just the one tracked PID", still_alive == [], still_alive)
        finally:
            try: parent.wait(timeout=2)
            except Exception: pass
    else:
        check('process-tree-kill test skipped (this harness is POSIX-only; Windows path uses taskkill /T, verify manually there)', True)

    try:
        miner_manager.MinerProcess(binary_path).start('', 'stratum+tcp://h:1', 'u', '', '', '', tmp)
        check('missing algorithm is rejected before spawning', False, 'accepted!')
    except ValueError:
        check('missing algorithm is rejected before spawning', True)
    try:
        miner_manager.MinerProcess(binary_path).start('xelishashv3', '', 'u', '', '', '', tmp)
        check('missing pool URL is rejected before spawning', False, 'accepted!')
    except ValueError:
        check('missing pool URL is rejected before spawning', True)
    try:
        miner_manager.MinerProcess(binary_path).start('xelishashv3', 'stratum+tcp://h:1', '', '', '', '', tmp)
        check('missing username is rejected before spawning', False, 'accepted!')
    except ValueError:
        check('missing username is rejected before spawning', True)
else:
    check('miner_manager tests skipped (no verified binary this run)', False, 'downloader step above did not produce one')

shutil.rmtree(tmp, ignore_errors=True)

# --- algorithms.py
from algorithms import ALGORITHMS
check('algorithm list is non-empty and includes xelishashv3', any(a['id'] == 'xelishashv3' for a in ALGORITHMS), ALGORITHMS)
check('every algorithm entry has id and label', all('id' in a and 'label' in a for a in ALGORITHMS))

# --- main.py's Api class: same no-push threading rule as the Xelis GUI, verify_status polling, algo passthrough
import inspect
import main as main_mod

src = inspect.getsource(main_mod)
src_no_docstring = src.replace(inspect.getsource(main_mod).split('"""')[1], '')
check('main.py contains no actual .evaluate_js( calls outside the explanatory docstring', '.evaluate_js(' not in src_no_docstring, src_no_docstring if '.evaluate_js(' in src_no_docstring else '')
check('Api no longer holds a window reference to push through', 'self.window' not in src)

api = main_mod.Api()
st = api.get_verify_status()
check('get_verify_status before any check: not verified, not failed, empty log', st == {"verified": False, "failed": None, "info": None, "log": []}, st)
check('get_algorithms exposes the same list algorithms.py defines', api.get_algorithms() == ALGORITHMS)

s = api.load_settings()
check('load_settings always returns a usable algo + pool_url (defaults or saved)', bool(s.get('algo')) and 'pool_url' in s, s)

api.check_or_download_miner()
seen_progress = False
t0 = time.time()
while time.time() - t0 < 30:
    st = api.get_verify_status()
    if st['log']: seen_progress = True
    if st['verified'] or st['failed']:
        break
    time.sleep(0.2)
check('verify status log fills in via polling (no push) while the background download runs', seen_progress, st['log'])
check('verify status eventually reports a terminal result (verified or a correctly-refused unpinned release)', st['verified'] or st['failed'], st)

# concurrent-poll safety: hammer get_verify_status from multiple threads while a fresh check runs
api2 = main_mod.Api()
errors = []
def hammer():
    try:
        for _ in range(50):
            api2.get_verify_status()
    except Exception as e:
        errors.append(e)
api2.check_or_download_miner()
ts = [threading.Thread(target=hammer) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
check('get_verify_status is safe to poll concurrently from multiple threads', not errors, errors)

print(f'\n{pass_}/{pass_+fail_} checks passed')
sys.exit(1 if fail_ else 0)
