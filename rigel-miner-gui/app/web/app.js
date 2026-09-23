let verified = false, running = false, pollTimer = null, verifyPollTimer = null, verifyLogShown = 0, verifyDone = false;

function appLog(msg) {
  const el = document.getElementById('log');
  const line = document.createElement('div');
  if (/fail|error|mismatch/i.test(msg)) line.className = 'l-err';
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function onVerified(info) {
  verified = true;
  document.getElementById('verifyStatus').innerHTML =
    `<span class="ok">&#10003; VERIFIED</span> — Rigel <b>${info.version}</b><br>` +
    `official release: <a href="${info.release_url}" target="_blank">${info.release_url}</a><br>` +
    `sha256: <span class="hash">${info.sha256}</span><br>` +
    `<span class="dim">Rigel is closed-source and publishes no checksums/signature of its own, so this SHA256 was ` +
    `pinned by us after manually downloading and reviewing this exact release — not an independent upstream ` +
    `signature. Compare it yourself against the release page if you want a second check.</span>`;
  document.getElementById('startBtn').disabled = false;
}

function onVerifyFailed(err) {
  document.getElementById('verifyStatus').innerHTML = `<span class="fail">&#10007; VERIFICATION FAILED</span><br>${err}<br><span class="dim">Refusing to run an unverified binary.</span>`;
  document.getElementById('statusDot').className = 'status-dot error';
}

function setStatusDot(state) {
  document.getElementById('statusDot').className = 'status-dot' + (state === 'live' ? ' live' : state === 'error' ? ' error' : '');
}

async function loadAlgorithms(selected) {
  const algos = await pywebview.api.get_algorithms();
  const sel = document.getElementById('algo');
  sel.innerHTML = '';
  for (const a of algos) {
    const opt = document.createElement('option');
    opt.value = a.id;
    opt.textContent = a.label;
    sel.appendChild(opt);
  }
  if (selected) sel.value = selected;
}

async function loadSettings() {
  const s = await pywebview.api.load_settings();
  await loadAlgorithms(s.algo);
  document.getElementById('poolUrl').value = s.pool_url || '';
  document.getElementById('username').value = s.username || '';
  document.getElementById('worker').value = s.worker || 'gui';
  document.getElementById('password').value = s.password || 'x';
  document.getElementById('devices').value = s.devices || '';
}

async function startMining() {
  const algo = document.getElementById('algo').value;
  const poolUrl = document.getElementById('poolUrl').value.trim();
  const username = document.getElementById('username').value.trim();
  const worker = document.getElementById('worker').value.trim();
  const password = document.getElementById('password').value.trim();
  const devices = document.getElementById('devices').value.trim();
  if (!poolUrl) { appLog('enter a pool URL first, e.g. stratum+tcp://host:port'); return; }
  if (!username) { appLog('enter a username / wallet address first'); return; }
  const r = await pywebview.api.start_mining(algo, poolUrl, username, password, worker, devices);
  if (!r.ok) { appLog('start failed: ' + r.error); setStatusDot('error'); return; }
  running = true;
  document.getElementById('startBtn').disabled = true;
  document.getElementById('stopBtn').disabled = false;
  appLog(`mining started -> ${algo} @ ${poolUrl}`);
  setStatusDot('live');
  startPolling();
}

async function stopMining() {
  await pywebview.api.stop_mining();
  running = false;
  document.getElementById('startBtn').disabled = false;
  document.getElementById('stopBtn').disabled = true;
  setStatusDot('');
  appLog('mining stopped');
  if (pollTimer) clearInterval(pollTimer);
}

// Rigel's --api-bind JSON shape, confirmed live 2026-09-23 (real v1.23.2, RTX 3080 Ti, mining xelishashv3
// to our own pool) and flattened server-side by miner_manager.summarize(). See that function for the raw
// field mapping (monitoring_info.core_temperature, etc.) if this ever needs re-deriving.
function fmtHashrate(h) {
  if (h === null || h === undefined) return '—';
  if (h >= 1e6) return (h / 1e6).toFixed(2) + ' MH/s';
  if (h >= 1e3) return (h / 1e3).toFixed(2) + ' kH/s';
  return h.toFixed(2) + ' H/s';
}

function renderStats(stats) {
  const grid = document.getElementById('statsGrid');
  if (!stats || stats.hashrate_pool === undefined) {
    grid.innerHTML = '<div class="stat-box"><div class="stat-val dim">—</div><div class="stat-lbl">WAITING</div></div>';
    document.getElementById('gpuCard').style.display = 'none';
    return;
  }
  const boxes = [
    ['HASHRATE', fmtHashrate(stats.hashrate_pool), 'amber'],
    ['SELF-REPORTED', fmtHashrate(stats.hashrate_self), 'dim'],
    ['ACCEPTED', stats.accepted ?? 0, ''],
    ['REJECTED', stats.rejected ?? 0, stats.rejected ? 'red' : ''],
    ['INVALID', stats.invalid ?? 0, stats.invalid ? 'red' : ''],
    ['LATENCY', stats.latency_ms != null ? stats.latency_ms + ' ms' : '—', ''],
  ];
  grid.innerHTML = boxes.map(([lbl, val, cls]) =>
    `<div class="stat-box"><div class="stat-val ${cls}">${val}</div><div class="stat-lbl">${lbl}</div></div>`
  ).join('');

  const devices = stats.devices || [];
  const gpuCard = document.getElementById('gpuCard');
  if (devices.length === 0) { gpuCard.style.display = 'none'; return; }
  gpuCard.style.display = '';
  document.getElementById('gpuList').innerHTML = devices.map(d => {
    const hot = (t) => t != null && t >= 85 ? ' hot' : '';
    return `<div class="gpu-row">
      <span class="gpu-name">${d.name || 'GPU'} <span class="dim">(${d.state || 'unknown'})</span></span>
      <span class="gpu-field">core <b class="${hot(d.core_temp)}">${d.core_temp ?? '—'}&deg;C</b></span>
      <span class="gpu-field">mem <b class="${hot(d.mem_temp)}">${d.mem_temp ?? '—'}&deg;C</b></span>
      <span class="gpu-field">fan <b>${d.fan_speed ?? '—'}%</b></span>
      <span class="gpu-field">power <b>${d.power_usage != null ? d.power_usage.toFixed(0) : '—'}W</b></span>
      <span class="gpu-field">core clk <b>${d.core_clock ?? '—'}MHz${d.core_clock_offset ? ' (' + (d.core_clock_offset > 0 ? '+' : '') + d.core_clock_offset + ')' : ''}</b></span>
      <span class="gpu-field">mem clk <b>${d.memory_clock ?? '—'}MHz${d.memory_clock_offset ? ' (' + (d.memory_clock_offset > 0 ? '+' : '') + d.memory_clock_offset + ')' : ''}</b></span>
      <span class="gpu-field">hashrate <b>${fmtHashrate(d.pool_hashrate)}</b></span>
    </div>`;
  }).join('');
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const status = await pywebview.api.get_status();
    renderStats(status.stats);
    if (!status.running && running) {
      appLog('miner process exited unexpectedly' + (status.error ? ': ' + status.error : ''));
      setStatusDot('error');
      running = false;
      document.getElementById('startBtn').disabled = false;
      document.getElementById('stopBtn').disabled = true;
      clearInterval(pollTimer);
    }
  }, 2000);
}

// Python never pushes into JS (see main.py's threading-rule comment) -- the download/verify step is just
// another thing we poll for, same as live stats.
function startVerifyPolling() {
  verifyPollTimer = setInterval(async () => {
    const s = await pywebview.api.get_verify_status();
    for (; verifyLogShown < s.log.length; verifyLogShown++) appLog(s.log[verifyLogShown]);
    if (verifyDone) return;
    if (s.verified) { verifyDone = true; onVerified(s.info); clearInterval(verifyPollTimer); }
    else if (s.failed) { verifyDone = true; onVerifyFailed(s.failed); clearInterval(verifyPollTimer); }
  }, 400);
}

window.addEventListener('pywebviewready', async () => {
  await loadSettings();
  document.getElementById('startBtn').addEventListener('click', startMining);
  document.getElementById('stopBtn').addEventListener('click', stopMining);
  appLog('checking for the official Rigel release...');
  await pywebview.api.check_or_download_miner();
  startVerifyPolling();
});
