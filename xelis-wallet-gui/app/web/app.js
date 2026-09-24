let verifyPollTimer = null, verifyLogShown = 0, verifyDone = false, statusPollTimer = null;

function appLog(msg) {
  const el = document.getElementById('log');
  const line = document.createElement('div');
  if (/fail|error|mismatch/i.test(msg)) line.className = 'l-err';
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function onVerified(info) {
  document.getElementById('verifyStatus').innerHTML =
    `<span class="ok">&#10003; VERIFIED</span> — xelis_wallet <b>${info.version}</b><br>` +
    `official release: <a href="${info.release_url}" target="_blank">${info.release_url}</a><br>` +
    `sha256: <span class="hash">${info.sha256}</span><br>` +
    `<span class="dim">This is the unmodified official binary, same signed release as the Xelis miner GUI — GPG signature and checksum verified before it was ever run.</span>`;
  document.getElementById('pickerCard').style.display = '';
  document.getElementById('openBtn').disabled = false;
  loadWalletList();
}

function onVerifyFailed(err) {
  document.getElementById('verifyStatus').innerHTML = `<span class="fail">&#10007; VERIFICATION FAILED</span><br>${err}<br><span class="dim">Refusing to run an unverified binary.</span>`;
  setStatusDot('error');
}

function setStatusDot(state) {
  document.getElementById('statusDot').className = 'status-dot' + (state === 'live' ? ' live' : state === 'error' ? ' error' : '');
}

async function loadWalletList() {
  const wallets = await pywebview.api.list_wallets();
  const sel = document.getElementById('walletPicker');
  sel.innerHTML = '';
  if (wallets.length === 0) {
    const opt = document.createElement('option');
    opt.textContent = '(no wallets yet — create one)';
    opt.disabled = true;
    sel.appendChild(opt);
    document.getElementById('mode').value = 'new';
    onModeChange();
  } else {
    for (const w of wallets) {
      const opt = document.createElement('option');
      opt.value = w; opt.textContent = w;
      sel.appendChild(opt);
    }
  }
}

function onModeChange() {
  const isNew = document.getElementById('mode').value === 'new';
  document.getElementById('existingRow').style.display = isNew ? 'none' : '';
  document.getElementById('newNameRow').style.display = isNew ? '' : 'none';
}

function onOfflineChange() {
  document.getElementById('daemonRow').style.display = document.getElementById('offline').checked ? 'none' : '';
}

async function openWallet() {
  const isNew = document.getElementById('mode').value === 'new';
  const name = isNew ? document.getElementById('newName').value.trim() : document.getElementById('walletPicker').value;
  const password = document.getElementById('password').value;
  const network = document.getElementById('network').value;
  const offline = document.getElementById('offline').checked;
  const daemonAddress = document.getElementById('daemonAddress').value.trim();
  const errEl = document.getElementById('pickerError');
  errEl.textContent = '';

  if (!name) { errEl.textContent = 'enter a wallet name'; return; }
  if (!password) { errEl.textContent = 'enter a password'; return; }

  document.getElementById('openBtn').disabled = true;
  appLog((isNew ? 'creating' : 'opening') + ` wallet '${name}'... this can take a while on first-ever run (generating precomputed tables)`);
  const r = await pywebview.api.open_wallet(name, password, network, daemonAddress, offline, isNew);
  document.getElementById('openBtn').disabled = false;
  if (!r.ok) { errEl.textContent = r.error; appLog('open failed: ' + r.error); return; }

  document.getElementById('pickerCard').style.display = 'none';
  document.getElementById('walletCard').style.display = '';
  document.getElementById('walletName').textContent = '— ' + name;
  document.getElementById('addressBox').textContent = r.address || '(address unavailable)';
  switchTab('overview');
  document.getElementById('sendTo').value = '';
  document.getElementById('sendAmount').value = '';
  document.getElementById('sendConfirm').checked = false;
  document.getElementById('sendFeePreview').textContent = '—';
  document.getElementById('sendResult').textContent = '';
  document.getElementById('historyList').textContent = 'no transactions loaded yet';
  setStatusDot('live');
  appLog((isNew ? 'created' : 'opened') + ` wallet '${name}'`);
  startStatusPolling();

  if (isNew) {
    // force the seed-backup flow right after creation -- not skippable, per the "show once with a
    // confirm checkbox" decision. document.getElementById('password') still holds the password they
    // just used to create it, prefill the seed-reveal password field with it as a convenience.
    document.getElementById('seedPassword').value = password;
    openSeedFlow();
  }
}

function openSeedFlow() {
  document.getElementById('seedCard').style.display = '';
  document.getElementById('seedStep1').style.display = '';
  document.getElementById('seedStep2').style.display = 'none';
  document.getElementById('seedError').textContent = '';
}

async function revealSeed() {
  const password = document.getElementById('seedPassword').value;
  const errEl = document.getElementById('seedError');
  errEl.textContent = '';
  if (!password) { errEl.textContent = 'enter your password'; return; }
  document.getElementById('revealBtn').disabled = true;
  appLog('revealing seed phrase...');
  const r = await pywebview.api.reveal_seed(password);
  document.getElementById('revealBtn').disabled = false;
  if (!r.ok) { errEl.textContent = r.error; appLog('seed reveal failed: ' + r.error); return; }

  const words = r.seed.split(/\s+/);
  document.getElementById('seedWords').innerHTML = words.map((w, i) =>
    `<span><b>${i + 1}.</b>${w}</span>`).join('');
  document.getElementById('seedStep1').style.display = 'none';
  document.getElementById('seedStep2').style.display = '';
  document.getElementById('seedConfirm').checked = false;
  document.getElementById('seedDoneBtn').disabled = true;
  appLog('seed phrase revealed — back it up now');
}

function closeSeedFlow() {
  document.getElementById('seedCard').style.display = 'none';
}

async function closeWallet() {
  await pywebview.api.close_wallet();
  if (statusPollTimer) clearInterval(statusPollTimer);
  document.getElementById('walletCard').style.display = 'none';
  document.getElementById('pickerCard').style.display = '';
  document.getElementById('password').value = '';
  setStatusDot('');
  appLog('wallet closed');
  loadWalletList();
}

function switchTab(name) {
  for (const btn of document.querySelectorAll('.tab-btn')) btn.classList.toggle('active', btn.dataset.tab === name);
  document.getElementById('tabOverview').style.display = name === 'overview' ? '' : 'none';
  document.getElementById('tabSend').style.display = name === 'send' ? '' : 'none';
  document.getElementById('tabHistory').style.display = name === 'history' ? '' : 'none';
  if (name === 'history') loadHistory();
}

let feeDebounceTimer = null;

function onSendInputChange() {
  document.getElementById('sendResult').textContent = '';
  document.getElementById('sendError').textContent = '';
  updateSendButtonState();
  clearTimeout(feeDebounceTimer);
  feeDebounceTimer = setTimeout(refreshFeePreview, 500);
}

async function refreshFeePreview() {
  const to = document.getElementById('sendTo').value.trim();
  const amount = document.getElementById('sendAmount').value.trim();
  const preview = document.getElementById('sendFeePreview');
  preview.classList.remove('red');
  if (!to || !amount) { preview.textContent = '—'; return; }
  const r = await pywebview.api.estimate_fee(to, amount);
  // Confirmed live 2026-09-23 (Windows): a failed estimate used to fall back to the exact same '—' shown
  // for "nothing typed yet", with no logging anywhere -- a real, surfaced error looked identical to
  // total silence. Now it shows the actual reason (styled red) and logs it, same as every other error
  // path in this app.
  if (!r.ok) {
    preview.textContent = r.error;
    preview.classList.add('red');
    appLog('fee estimate failed: ' + r.error);
    return;
  }
  preview.textContent = `${r.fee_xel.toFixed(8)} XEL`;
}

function updateSendButtonState() {
  const to = document.getElementById('sendTo').value.trim();
  const amount = document.getElementById('sendAmount').value.trim();
  const confirmed = document.getElementById('sendConfirm').checked;
  document.getElementById('sendBtn').disabled = !(to && amount && confirmed);
}

async function sendTransaction() {
  const to = document.getElementById('sendTo').value.trim();
  const amount = document.getElementById('sendAmount').value.trim();
  const errEl = document.getElementById('sendError');
  const resultEl = document.getElementById('sendResult');
  errEl.textContent = '';
  resultEl.textContent = '';

  document.getElementById('sendBtn').disabled = true;
  appLog(`sending ${amount} XEL to ${to}...`);
  const r = await pywebview.api.send_transaction(to, amount);
  updateSendButtonState();
  if (!r.ok) { errEl.textContent = r.error; appLog('send failed: ' + r.error); return; }

  resultEl.innerHTML = `sent — fee ${r.fee_xel.toFixed(8)} XEL<br>tx hash: <span class="hash">${r.hash}</span>`;
  appLog(`sent ${amount} XEL, tx ${r.hash}`);
  document.getElementById('sendTo').value = '';
  document.getElementById('sendAmount').value = '';
  document.getElementById('sendConfirm').checked = false;
  document.getElementById('sendFeePreview').textContent = '—';
}

function fmtTimestamp(ms) {
  if (!ms) return '—';
  const d = new Date(ms);
  return d.toLocaleString();
}

async function loadHistory() {
  const listEl = document.getElementById('historyList');
  listEl.textContent = 'loading...';
  const r = await pywebview.api.get_transactions(50);
  if (!r.ok) { listEl.textContent = 'error: ' + r.error; return; }
  if (r.transactions.length === 0) { listEl.textContent = 'no transactions yet'; return; }

  const kindLabel = { incoming: 'IN', outgoing: 'OUT', coinbase: 'MINED', burn: 'BURN', other: '?' };
  const kindClass = { incoming: 'in', outgoing: 'out', coinbase: 'coinbase' };
  listEl.innerHTML = r.transactions.map(tx => `
    <div class="tx-row">
      <span class="tx-kind ${kindClass[tx.kind] || ''}">${kindLabel[tx.kind] || tx.kind}</span>
      <span class="tx-amount">${tx.amount_xel != null ? (tx.kind === 'outgoing' ? '-' : '+') + tx.amount_xel.toFixed(8) : '—'}</span>
      <span class="tx-counterparty" title="${tx.hash}">${tx.counterparty || ''}</span>
      <span class="tx-time">${fmtTimestamp(tx.timestamp)}</span>
    </div>
  `).join('');
}

function fmtXel(atomic) {
  // XEL uses 8 decimal places (confirmed via get_balance returning an atomic integer, same convention
  // documented across the Xelis RPC API for asset amounts)
  if (atomic === null || atomic === undefined) return '—';
  return (atomic / 1e8).toFixed(8);
}

function startStatusPolling() {
  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(async () => {
    const s = await pywebview.api.get_status();
    if (!s.open) { clearInterval(statusPollTimer); return; }
    // each of balance/topoheight/online now fails independently server-side (see main.py's
    // get_status) -- a benign error on one (e.g. topoheight on a brand-new wallet with no chain data
    // yet) shouldn't blank out the fields that DID succeed, so this just shows '—'/OFFLINE for
    // whichever ones are null rather than bailing out of the whole render.
    document.getElementById('sBalance').textContent = fmtXel(s.balance);
    document.getElementById('sTopo').textContent = s.topoheight ?? '—';
    document.getElementById('sOnline').textContent = s.online ? 'ONLINE' : 'OFFLINE';
  }, 5000);
}

window.addEventListener('pywebviewready', async () => {
  document.getElementById('daemonAddress').value = await pywebview.api.get_default_daemon_address();
  document.getElementById('mode').addEventListener('change', onModeChange);
  document.getElementById('offline').addEventListener('change', onOfflineChange);
  document.getElementById('openBtn').addEventListener('click', openWallet);
  document.getElementById('closeBtn').addEventListener('click', closeWallet);
  document.getElementById('showSeedBtn').addEventListener('click', () => {
    document.getElementById('seedPassword').value = '';
    openSeedFlow();
  });
  document.getElementById('revealBtn').addEventListener('click', revealSeed);
  document.getElementById('seedCancelBtn').addEventListener('click', closeSeedFlow);
  document.getElementById('seedConfirm').addEventListener('change', (e) => {
    document.getElementById('seedDoneBtn').disabled = !e.target.checked;
  });
  document.getElementById('seedDoneBtn').addEventListener('click', closeSeedFlow);
  document.getElementById('addressBox').addEventListener('click', () => {
    const addr = document.getElementById('addressBox').textContent;
    navigator.clipboard?.writeText(addr).catch(() => {});
    appLog('address copied to clipboard');
  });

  for (const btn of document.querySelectorAll('.tab-btn')) {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  }
  document.getElementById('sendTo').addEventListener('input', onSendInputChange);
  document.getElementById('sendAmount').addEventListener('input', onSendInputChange);
  document.getElementById('sendConfirm').addEventListener('change', updateSendButtonState);
  document.getElementById('sendBtn').addEventListener('click', sendTransaction);
  document.getElementById('refreshHistoryBtn').addEventListener('click', loadHistory);

  appLog('checking for the official xelis_wallet release...');
  await pywebview.api.check_or_download_wallet();
  verifyPollTimer = setInterval(async () => {
    const s = await pywebview.api.get_verify_status();
    for (; verifyLogShown < s.log.length; verifyLogShown++) appLog(s.log[verifyLogShown]);
    if (verifyDone) return;
    if (s.verified) { verifyDone = true; onVerified(s.info); clearInterval(verifyPollTimer); }
    else if (s.failed) { verifyDone = true; onVerifyFailed(s.failed); clearInterval(verifyPollTimer); }
  }, 400);
});
