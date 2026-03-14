// Tiresias Dashboard — app.js
// Vanilla JS, no build step. Calls /dash/v1/* endpoints.

const API_KEY_KEY = 'tiresias_api_key';
let requestsChart = null;
let latencyChart = null;

function getApiKey() {
  return document.getElementById('api-key-input').value.trim() || localStorage.getItem(API_KEY_KEY) || '';
}

function saveKey() {
  const key = document.getElementById('api-key-input').value.trim();
  if (key) {
    localStorage.setItem(API_KEY_KEY, key);
    document.getElementById('key-status').textContent = 'Saved.';
    setTimeout(() => { document.getElementById('key-status').textContent = ''; }, 2000);
    loadAll();
  }
}

function showPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  const idx = ['overview', 'sessions', 'providers'].indexOf(name);
  document.querySelectorAll('nav button')[idx].classList.add('active');
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function apiFetch(path) {
  const key = getApiKey();
  const resp = await fetch(path, {
    headers: { 'X-Tiresias-Api-Key': key }
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

function fmtCost(v) {
  if (v == null) return '$0.000000';
  return '$' + Number(v).toFixed(6);
}

function fmtNum(v) {
  if (v == null) return '0';
  return Number(v).toLocaleString();
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ─── Overview ──────────────────────────────────────────────────────────────

async function loadSpend() {
  try {
    const data = await apiFetch('/dash/v1/spend');
    document.getElementById('card-cost').textContent = fmtCost(data.total_cost_usd);
    document.getElementById('card-requests').textContent = fmtNum(data.request_count);
    document.getElementById('card-tokens').textContent = fmtNum(data.total_tokens);
  } catch (e) {
    showError('Spend: ' + e.message);
  }
}

async function loadRequestsChart() {
  try {
    const data = await apiFetch('/dash/v1/requests');
    const labels = data.map(d => d.date);
    const counts = data.map(d => d.request_count);

    const ctx = document.getElementById('requests-chart').getContext('2d');
    if (requestsChart) requestsChart.destroy();
    requestsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Requests',
          data: counts,
          backgroundColor: 'rgba(99,102,241,0.7)',
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#94a3b8', maxRotation: 45 }, grid: { color: '#2a2d3e' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: '#2a2d3e' }, beginAtZero: true }
        }
      }
    });
  } catch (e) {
    showError('Requests chart: ' + e.message);
  }
}

async function loadLatencyChart() {
  try {
    const data = await apiFetch('/dash/v1/latency');
    if (!data.length) return;

    const labels = data.map(d => d.provider);
    const p50 = data.map(d => d.p50_ms);
    const p95 = data.map(d => d.p95_ms);
    const p99 = data.map(d => d.p99_ms);

    const ctx = document.getElementById('latency-chart').getContext('2d');
    if (latencyChart) latencyChart.destroy();
    latencyChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'p50', data: p50, backgroundColor: 'rgba(34,197,94,0.7)', borderRadius: 4 },
          { label: 'p95', data: p95, backgroundColor: 'rgba(245,158,11,0.7)', borderRadius: 4 },
          { label: 'p99', data: p99, backgroundColor: 'rgba(239,68,68,0.7)', borderRadius: 4 },
        ]
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        scales: {
          x: { ticks: { color: '#94a3b8' }, grid: { color: '#2a2d3e' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: '#2a2d3e' }, beginAtZero: true,
               title: { display: true, text: 'ms', color: '#94a3b8' } }
        }
      }
    });
  } catch (e) {
    showError('Latency chart: ' + e.message);
  }
}

// ─── Sessions ──────────────────────────────────────────────────────────────

async function loadSessions() {
  try {
    const data = await apiFetch('/dash/v1/sessions/top?limit=25');
    const tbody = document.getElementById('sessions-tbody');
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No sessions found.</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(s => `
      <tr>
        <td style="font-family:monospace;font-size:12px">${s.session_id}</td>
        <td>${fmtCost(s.total_cost_usd)}</td>
        <td>${fmtNum(s.request_count)}</td>
        <td>${fmtNum(s.total_tokens)}</td>
        <td>${fmtDate(s.last_request_at)}</td>
        <td><button onclick="openReplay('${s.session_id}')" style="background:var(--accent);border:none;color:#fff;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px">Replay</button></td>
      </tr>
    `).join('');
  } catch (e) {
    showError('Sessions: ' + e.message);
  }
}

// ─── Providers ─────────────────────────────────────────────────────────────

async function loadProviders() {
  try {
    const data = await apiFetch('/dash/v1/providers/health');
    const cards = document.getElementById('health-cards');
    cards.innerHTML = (data.providers || []).map(p => `
      <div class="card">
        <div class="label">${p.name}</div>
        <div class="value" style="font-size:18px">
          <span class="badge badge-${p.status}">${p.status.toUpperCase()}</span>
        </div>
        <div style="color:var(--muted);font-size:11px;margin-top:6px">${p.consecutive_errors} consecutive errors</div>
      </div>
    `).join('');
  } catch (e) {
    showError('Provider health: ' + e.message);
    document.getElementById('health-cards').textContent = 'Error loading health.';
  }
}

async function loadErrors() {
  try {
    const data = await apiFetch('/dash/v1/errors');
    const tbody = document.getElementById('errors-tbody');
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">No data.</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(r => `
      <tr>
        <td>${r.provider}</td>
        <td>${fmtNum(r.total_requests)}</td>
        <td>${fmtNum(r.error_count)}</td>
        <td>${(r.error_rate * 100).toFixed(2)}%</td>
        <td style="font-family:monospace;font-size:12px">${JSON.stringify(r.status_codes)}</td>
      </tr>
    `).join('');
  } catch (e) {
    showError('Error rates: ' + e.message);
  }
}

// ─── Session Replay ────────────────────────────────────────────────────────

async function openReplay(sessionId) {
  document.getElementById('replay-title').textContent = 'Session Replay: ' + sessionId;
  document.getElementById('replay-turns').innerHTML = 'Loading...';
  document.getElementById('replay-modal').classList.add('open');

  try {
    const turns = await apiFetch(`/dash/v1/sessions/${encodeURIComponent(sessionId)}/replay`);
    if (!turns.length) {
      document.getElementById('replay-turns').innerHTML = '<p style="color:var(--muted)">No turns found.</p>';
      return;
    }
    document.getElementById('replay-turns').innerHTML = turns.map((t, i) => `
      <div class="turn">
        <div class="meta">
          Turn ${i + 1} &bull; ${t.model || '—'} &bull; ${t.provider || '—'} &bull; ${fmtNum(t.token_count)} tokens &bull; ${fmtCost(t.cost_usd)} &bull; ${fmtDate(t.created_at)}
        </div>
        ${t.prompt != null ? `<div class="prompt-label">PROMPT</div><pre>${escHtml(t.prompt)}</pre>` : ''}
        ${t.completion != null ? `<div class="completion-label">COMPLETION</div><pre>${escHtml(t.completion)}</pre>` : ''}
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('replay-turns').innerHTML = `<p style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

function closeModal() {
  document.getElementById('replay-modal').classList.remove('open');
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ─── Bootstrap ─────────────────────────────────────────────────────────────

function loadAll() {
  loadSpend();
  loadRequestsChart();
  loadLatencyChart();
  loadSessions();
  loadProviders();
  loadErrors();
}

window.addEventListener('DOMContentLoaded', () => {
  const stored = localStorage.getItem(API_KEY_KEY);
  if (stored) {
    document.getElementById('api-key-input').value = stored;
    document.getElementById('key-status').textContent = 'Key loaded from storage.';
  }
  loadAll();
});

// Close modal on overlay click
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('replay-modal').addEventListener('click', function(e) {
    if (e.target === this) closeModal();
  });
});
