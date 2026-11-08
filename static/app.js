// ── Tab switching ──────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'sessions' && !window._sessionsLoaded) loadSessions();
  if (name === 'databases') loadDatabases();
  if (name === 'make' && !window._makeLoaded) loadMakeTargets();
  if (name === 'board') { _boardItems = []; loadBoard(); }
  if (name === 'flows') loadFlows();
}

// ── Odoo status bar ────────────────────────────────────────────────────────────
async function refreshOdooStatus() {
  try {
    const r = await fetch('/api/odoo/status');
    const d = await r.json();
    const dot = document.getElementById('odoo-dot');
    const txt = document.getElementById('odoo-status-text');
    if (d.running) {
      dot.className = 'w-2 h-2 rounded-full dot-green';
      txt.textContent = `Odoo: ${d.db || 'running'} (PID ${d.pid})`;
    } else {
      dot.className = 'w-2 h-2 rounded-full dot-gray';
      txt.textContent = 'Odoo: not running';
    }
    // Mirror into DB tab
    const dbDot = document.getElementById('db-odoo-dot');
    const dbTxt = document.getElementById('db-odoo-status');
    if (dbDot) {
      dbDot.className = `w-2 h-2 rounded-full ${d.running ? 'dot-green' : 'dot-gray'}`;
      dbTxt.textContent = d.running ? `Running on ${d.db || '—'} (PID ${d.pid})` : 'Not running';
    }
    // Show Stop/Restart only when running; Start only when stopped
    const stopBtn = document.getElementById('stop-odoo-btn');
    if (stopBtn) stopBtn.classList.toggle('hidden', !d.running);
    const restartBtn = document.getElementById('restart-odoo-btn');
    if (restartBtn) restartBtn.classList.toggle('hidden', !d.running);
    const startBtn = document.getElementById('start-odoo-btn');
    if (startBtn) startBtn.classList.toggle('hidden', d.running);
    // Update configured-DB badge: Active (green) when running, In conf (blue) when stopped
    const activeBadge = document.getElementById('active-db-badge');
    if (activeBadge) {
      if (d.running) {
        activeBadge.textContent = 'Active';
        activeBadge.className = 'badge bg-green-900 text-green-300 text-xs';
        activeBadge.closest('.db-card')?.classList.add('odoo-running');
      } else {
        activeBadge.textContent = 'In conf';
        activeBadge.className = 'badge bg-blue-900 text-blue-300 text-xs';
        activeBadge.closest('.db-card')?.classList.remove('odoo-running');
      }
    }
  } catch {}
}
setInterval(() => { if (!document.hidden) refreshOdooStatus(); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshOdooStatus(); });
refreshOdooStatus();

// ── Sessions Tab ───────────────────────────────────────────────────────────────
let allSessions = [];

async function loadSessions() {
  document.getElementById('sessions-tbody').innerHTML =
    '<tr><td colspan="6" class="px-3 py-6 text-center text-gray-500">Loading…</td></tr>';
  try {
    const r = await fetch('/api/sessions');
    allSessions = await r.json();
    window._sessionsLoaded = true;
    renderSessions(allSessions);
  } catch (e) {
    document.getElementById('sessions-tbody').innerHTML =
      `<tr><td colspan="6" class="px-3 py-4 text-center text-red-400">Error: ${e.message}</td></tr>`;
  }
}

function taskHistoryText(s) {
  return (s.tasks || []).map(t => `${t.task_number} ${t.notes}`).join(' ');
}

function filterSessions() {
  const q = document.getElementById('session-search').value.toLowerCase();
  if (!q) { renderSessions(allSessions); return; }
  renderSessions(allSessions.filter(s =>
    (s.ai_title || '').toLowerCase().includes(q) ||
    taskHistoryText(s).toLowerCase().includes(q)
  ));
}

function taskBadges(s) {
  const seen = new Set();
  const nums = (s.tasks || [])
    .map(t => t.task_number)
    .filter(Boolean)
    .filter(n => (seen.has(n) ? false : (seen.add(n), true)));
  if (!nums.length) return `<span class="text-gray-600 text-xs">—</span>`;
  return nums.map(n => `<span class="badge bg-orange-900 text-orange-300">${escHtml(n)}</span>`).join(' ');
}

function renderSessions(sessions) {
  document.getElementById('session-count').textContent = `${sessions.length} sessions`;
  const tbody = document.getElementById('sessions-tbody');
  if (!sessions.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="px-3 py-6 text-center text-gray-500">No sessions found.</td></tr>';
    return;
  }
  tbody.innerHTML = sessions.map(s => {
    const badge = taskBadges(s);
    const titleClass = s.has_ai_title ? 'text-gray-200' : 'text-gray-500 italic';
    const projColor = s.project === 'odoo-17.0' ? 'text-blue-400' : s.project === 'odoo-19.0' ? 'text-green-400' : 'text-purple-400';
    return `<tr class="border-t border-gray-800 hover:bg-gray-800/40" id="row-${s.session_id}">
      <td class="px-3 py-2 text-xs text-gray-400 whitespace-nowrap">${escHtml(s.date)}</td>
      <td class="px-3 py-2 ${titleClass}" title="${escHtml(s.ai_title)}">${escHtml(s.ai_title.slice(0,72))}${s.ai_title.length>72?'…':''}</td>
      <td class="px-3 py-2 text-xs ${projColor}">${escHtml(s.project)}</td>
      <td class="px-3 py-2 flex flex-wrap gap-1" id="task-cell-${s.session_id}">${badge}</td>
      <td class="px-3 py-2 text-xs text-gray-400 max-w-[200px] truncate" title="${escHtml(s.notes)}">${escHtml(s.notes) || ''}</td>
      <td class="px-3 py-2">
        <button onclick="editTask('${s.session_id}')" class="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap">Edit</button>
      </td>
    </tr>`;
  }).join('');
}

function editTask(sid) {
  const row = document.getElementById('row-' + sid);
  const session = allSessions.find(s => s.session_id === sid);
  if (!session) return;

  // Past tasks this session has already touched (most recent first, excluding the
  // one about to be edited into the input below).
  const history = (session.tasks || []).slice(1);
  const historyHtml = history.length
    ? `<div class="text-[10px] text-gray-500 mt-1">also: ${history.map(t => escHtml(t.task_number)).filter(Boolean).join(', ')}</div>`
    : '';

  // Replace row with inline editor
  row.innerHTML = `
    <td class="px-3 py-1 text-xs text-gray-400">${escHtml(session.date)}</td>
    <td class="px-3 py-1 text-gray-200" colspan="2" title="${escHtml(session.ai_title)}">${escHtml(session.ai_title.slice(0,72))}</td>
    <td class="px-3 py-1">
      <input type="text" id="edit-task-${sid}" value="${escHtml(session.task_number || '')}"
        placeholder="T26-04156" class="w-28 text-xs py-1" maxlength="10"
        onkeydown="if(event.key==='Enter')saveTask('${sid}');if(event.key==='Escape')cancelEdit('${sid}')">
      ${historyHtml}
    </td>
    <td class="px-3 py-1" colspan="2">
      <input type="text" id="edit-notes-${sid}" value="${escHtml(session.notes || '')}"
        placeholder="notes…" class="w-44 text-xs py-1"
        onkeydown="if(event.key==='Enter')saveTask('${sid}');if(event.key==='Escape')cancelEdit('${sid}')">
      <button onclick="saveTask('${sid}')" class="ml-2 text-xs text-green-400 hover:text-green-300">Save</button>
      <button onclick="cancelEdit('${sid}')" class="ml-1 text-xs text-gray-500 hover:text-gray-300">Cancel</button>
    </td>`;
  document.getElementById('edit-task-' + sid)?.focus();
}

function cancelEdit(sid) {
  renderSessions(allSessions.filter(s => {
    const q = document.getElementById('session-search').value.toLowerCase();
    return !q || (s.ai_title||'').toLowerCase().includes(q) || taskHistoryText(s).toLowerCase().includes(q);
  }));
}

async function saveTask(sid) {
  const taskInput = document.getElementById('edit-task-' + sid);
  const notesInput = document.getElementById('edit-notes-' + sid);
  const taskNum = (taskInput?.value || '').trim().toUpperCase();
  const notes = (notesInput?.value || '').trim();

  // Auto-format: if user typed just digits, prepend T26-
  let formatted = taskNum;
  if (/^\d{5}$/.test(formatted)) formatted = 'T26-' + formatted;

  try {
    const r = await fetch(`/api/sessions/${sid}/task`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task_number: formatted, notes})
    });
    if (!r.ok) { const d = await r.json(); alert(d.detail || 'Error'); return; }
    // This appends a new history entry server-side (unless it's identical to the
    // current latest) — mirror that locally so the badge list stays in sync.
    const s = allSessions.find(s => s.session_id === sid);
    if (s) {
      s.tasks = s.tasks || [];
      const latest = s.tasks[0];
      if (!latest || latest.task_number !== formatted || latest.notes !== notes) {
        s.tasks.unshift({task_number: formatted, notes, updated_at: new Date().toISOString()});
      }
      s.task_number = formatted;
      s.notes = notes;
    }
    renderSessions(allSessions);
  } catch (e) { alert(e.message); }
}

// ── Databases Tab ──────────────────────────────────────────────────────────────
let modalResolve = null;
let odooInstalls = [];

function openModal(title, body) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').textContent = body;
  document.getElementById('modal-version-row').classList.add('hidden');
  document.getElementById('modal').classList.add('open');
  return new Promise(res => { modalResolve = res; });
}
function closeModal() { document.getElementById('modal').classList.remove('open'); if (modalResolve) modalResolve(false); }
function modalConfirm() { document.getElementById('modal').classList.remove('open'); if (modalResolve) modalResolve(true); }

async function openSwitchModal(dbName, dbVersion) {
  document.getElementById('modal-title').textContent = 'Switch Database';
  document.getElementById('modal-body').textContent =
    `Switch Odoo to "${dbName}" and restart? This will interrupt running processes.`;

  const versionRow = document.getElementById('modal-version-row');
  if (odooInstalls.length) {
    const sel = document.getElementById('modal-odoo-version');
    sel.innerHTML = odooInstalls.map(i =>
      `<option value="${i.major}">${i.label} — ${i.dir}</option>`
    ).join('');
    // Auto-select version matching the DB
    const match = odooInstalls.find(i => i.major === String(dbVersion));
    if (match) sel.value = match.major;

    const warnEl = document.getElementById('modal-version-warn');
    if (dbVersion && !match) {
      warnEl.textContent = `DB is Odoo ${dbVersion} but no matching install was found`;
      warnEl.classList.remove('hidden');
    } else if (dbVersion && sel.value !== String(dbVersion)) {
      warnEl.textContent = `DB is Odoo ${dbVersion} but selected binary is ${sel.value}`;
      warnEl.classList.remove('hidden');
    } else {
      warnEl.classList.add('hidden');
    }
    versionRow.classList.remove('hidden');
  } else {
    versionRow.classList.add('hidden');
  }

  document.getElementById('modal').classList.add('open');
  return new Promise(res => { modalResolve = res; });
}

const PROFILE_COLORS = {ryt:'bg-blue-900 text-blue-300', std:'bg-purple-900 text-purple-300',
  dk:'bg-teal-900 text-teal-300', dd:'bg-yellow-900 text-yellow-300', sme:'bg-pink-900 text-pink-300'};

// Cache of db→version, populated lazily
const dbVersionCache = {};
let loadedProfileNames = ['ryt', 'std', 'dk', 'dd', 'sme'];

async function loadDatabases() {
  document.getElementById('db-grid').innerHTML = '<div class="col-span-3 text-center text-gray-500 py-8">Loading…</div>';
  try {
    const [dbResp, profResp, installResp, addonsResp] = await Promise.all([
      fetch('/api/databases'), fetch('/api/db-profiles'),
      fetch('/api/odoo/installations'), fetch('/api/addons-profiles')
    ]);
    const d = await dbResp.json();
    const profiles = await profResp.json();
    odooInstalls = await installResp.json();
    const addonsProfiles = await addonsResp.json();
    loadedProfileNames = Object.keys(addonsProfiles);
    renderDatabases(d.databases, d.active_db, profiles);
    refreshOdooStatus();
    loadDbVersions(d.databases);
  } catch (e) {
    document.getElementById('db-grid').innerHTML = `<div class="col-span-3 text-center text-red-400 py-8">Error: ${e.message}</div>`;
  }
}

async function loadDbVersions(dbs) {
  for (const db of dbs) {
    if (dbVersionCache[db]) continue;
    try {
      const r = await fetch(`/api/databases/${db}/version`);
      const data = await r.json();
      if (data.version) {
        dbVersionCache[db] = data.version;
        const badge = document.getElementById(`ver-${db}`);
        if (badge) {
          badge.textContent = `v${data.version}`;
          badge.classList.remove('hidden');
          badge.className = `badge text-xs ${data.version === '14' ? 'bg-orange-900 text-orange-300' : 'bg-indigo-900 text-indigo-300'}`;
        }
      }
    } catch {}
  }
}

function renderDatabases(dbs, activeDb, profiles) {
  if (!dbs.length) {
    document.getElementById('db-grid').innerHTML = '<div class="col-span-3 text-center text-gray-500 py-8">No dv_* databases found.</div>';
    return;
  }
  document.getElementById('db-grid').innerHTML = dbs.map(db => {
    const isActive = db === activeDb;
    const prof = profiles[db] || '';
    const profColor = PROFILE_COLORS[prof] || 'bg-gray-700 text-gray-400';
    const cached = dbVersionCache[db];
    const verColor = cached === '14' ? 'bg-orange-900 text-orange-300' : 'bg-indigo-900 text-indigo-300';
    const opts = ['', ...loadedProfileNames].map(p =>
      `<option value="${p}"${p===prof?' selected':''}>${p || '(none)'}</option>`).join('');
    return `<div class="db-card bg-gray-800 border-2 ${isActive ? 'active-db' : 'border-gray-700'} rounded-lg p-3 flex flex-col gap-2">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="font-mono text-sm font-semibold flex-1">${escHtml(db)}</span>
        ${isActive ? '<span id="active-db-badge" class="badge bg-blue-900 text-blue-300 text-xs">In conf</span>' : ''}
        <span id="ver-${db}" class="badge text-xs ${cached ? verColor : 'hidden'}">${cached ? 'v'+cached : ''}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-500">path:</span>
        <select class="text-xs py-0 h-6 flex-1" onchange="saveDbProfile('${db}', this.value)" onclick="event.stopPropagation()">
          ${opts}
        </select>
        ${prof ? `<span class="badge ${profColor} text-xs">${escHtml(prof)}</span>` : ''}
      </div>
      <button class="text-xs text-left text-gray-500 hover:text-blue-400" onclick="switchDb('${db}')">Switch →</button>
    </div>`;
  }).join('');
}

async function saveDbProfile(dbName, profile) {
  try {
    await fetch(`/api/db-profiles/${dbName}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile})
    });
    // Refresh to update badge colors
    loadDatabases();
  } catch (e) { alert(e.message); }
}

async function switchDb(dbName) {
  const dbVersion = dbVersionCache[dbName] || '';
  const confirmed = await openSwitchModal(dbName, dbVersion);
  if (!confirmed) return;
  const chosenVersion = document.getElementById('modal-odoo-version')?.value || null;

  // Show spinner on all cards
  document.getElementById('db-grid').querySelectorAll('.db-card').forEach(c => c.style.opacity = '0.5');

  const dot = document.getElementById('odoo-dot');
  const txt = document.getElementById('odoo-status-text');
  dot.className = 'w-2 h-2 rounded-full dot-yellow';
  txt.textContent = `Switching to ${dbName}…`;

  try {
    const r = await fetch('/api/databases/switch', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({db_name: dbName, odoo_version: chosenVersion})
    });
    if (!r.ok) { const d = await r.json(); alert(d.detail || 'Switch failed'); loadDatabases(); return; }

    // Poll until Odoo is running with new DB
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      if (attempts > 30) { clearInterval(poll); loadDatabases(); return; }
      try {
        const sr = await fetch('/api/odoo/status');
        const sd = await sr.json();
        if (sd.running && sd.db === dbName) {
          clearInterval(poll);
          loadDatabases();
          refreshOdooStatus();
        }
      } catch {}
    }, 2000);
  } catch (e) {
    alert(e.message);
    loadDatabases();
  }
}

// ── Make output panel resize ───────────────────────────────────────────────────
(function() {
  const STORAGE_KEY = 'make-output-width';
  function initMakeResize() {
    const handle = document.getElementById('make-resize-handle');
    const panel  = document.getElementById('make-output-panel');
    if (!handle || !panel) return;
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) panel.style.width = saved + 'px';
    let dragging = false, startX = 0, startW = 0;
    handle.addEventListener('mousedown', e => {
      dragging = true;
      startX = e.clientX;
      startW = panel.offsetWidth;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
      if (!dragging) return;
      const delta = startX - e.clientX;   // drag left = wider
      const newW = Math.min(Math.max(startW + delta, 200), window.innerWidth * 0.8);
      panel.style.width = newW + 'px';
    });
    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem(STORAGE_KEY, panel.offsetWidth);
    });
  }
  document.addEventListener('DOMContentLoaded', initMakeResize);
})();

// ── Makefile Tab ───────────────────────────────────────────────────────────────
async function loadMakeTargets() {
  window._makeLoaded = true;
  try {
    const r = await fetch('/api/make/targets');
    const groups = await r.json();
    renderMakeTargets(groups);
  } catch (e) {
    document.getElementById('make-targets').innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
  }
}

function renderMakeTargets(groups) {
  document.getElementById('make-targets').innerHTML = groups.map(group => `
    <div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <div class="px-3 py-2 bg-gray-750 border-b border-gray-700 font-medium text-sm text-gray-300">${escHtml(group.group)}</div>
      <div class="divide-y divide-gray-700/50">
        ${group.targets.map(t => renderTargetRow(t)).join('')}
      </div>
    </div>
  `).join('');
}

function renderTargetRow(target) {
  const paramInputs = target.params.map(p => {
    const id = `param-${target.name}-${p.name}`;
    if (p.type === 'select') {
      const opts = p.options.map(o => `<option value="${o}"${o===p.default?' selected':''}>${o}</option>`).join('');
      return `<span class="text-xs text-gray-500">${p.name}=</span><select id="${id}" class="text-xs py-0.5 px-1 h-7 min-w-[80px]">${opts}</select>`;
    }
    return `<span class="text-xs text-gray-500">${p.name}=</span><input type="text" id="${id}" placeholder="${escHtml(p.placeholder||'')}" value="${escHtml(p.default||'')}" class="text-xs py-0.5 w-24 h-7" ${p.required?'required':''}>`;
  }).join('');

  // These run interactively / indefinitely and can't stream over the dashboard — use a terminal
  const TERMINAL_ONLY = new Set(['log', 'shell']);
  const isTerminalOnly = TERMINAL_ONLY.has(target.name);
  const isPrimary = target.name === 'update';
  const btnClass = isPrimary
    ? 'px-3 py-1 bg-blue-700 hover:bg-blue-600 rounded text-xs font-semibold'
    : 'px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs';

  const paramsJson = JSON.stringify(target.params.map(p => p.name)).replace(/"/g, '&quot;');
  const action = isTerminalOnly
    ? `<span class="text-xs text-gray-600 italic px-3 py-1" title="Runs indefinitely / needs a TTY — run in a terminal: make ${escHtml(target.name)}">terminal only</span>`
    : `<button class="${btnClass}" onclick="runMakeTarget('${escHtml(target.name)}', ${paramsJson})">Run</button>`;

  return `<div class="flex items-center gap-2 px-3 py-2 flex-wrap${isTerminalOnly ? ' opacity-60' : ''}">
    <span class="font-mono text-sm font-medium w-28 shrink-0 text-gray-200">${escHtml(target.name)}</span>
    <span class="text-xs text-gray-500 flex-1 min-w-[120px]">${escHtml(target.description)}</span>
    ${paramInputs ? `<div class="flex items-center gap-1 flex-wrap">${paramInputs}</div>` : ''}
    ${action}
  </div>`;
}

async function runMakeTarget(targetName, paramNames) {
  const params = {};
  for (const name of paramNames) {
    const el = document.getElementById(`param-${targetName}-${name}`);
    if (el && el.value.trim()) params[name] = el.value.trim();
  }

  const outputEl = document.getElementById('make-output-text');
  const headerEl = document.getElementById('make-output-header');
  const scrollEl = document.getElementById('make-output-scroll');
  outputEl.textContent = '';
  headerEl.style.borderColor = '';

  try {
    const resp = await fetch('/api/make/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({target: targetName, params})
    });

    if (!resp.ok) {
      const d = await resp.json();
      outputEl.textContent = 'Error: ' + (d.detail || 'Unknown error');
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let lineBuffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      lineBuffer += decoder.decode(value, {stream: true});
      const lines = lineBuffer.split('\n');
      lineBuffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'start') {
            document.getElementById('make-output-cmd').textContent = evt.cmd;
          } else if (evt.type === 'output') {
            outputEl.textContent += evt.text;
            scrollEl.scrollTop = scrollEl.scrollHeight;
          } else if (evt.type === 'done') {
            const ok = evt.exit_code === 0;
            headerEl.style.borderBottomColor = ok ? '#22c55e' : '#ef4444';
            outputEl.textContent += `\n[exit ${evt.exit_code}]`;
            scrollEl.scrollTop = scrollEl.scrollHeight;
          } else if (evt.type === 'error') {
            outputEl.textContent += '\nError: ' + evt.text;
          }
        } catch {}
      }
    }
  } catch (e) {
    outputEl.textContent = 'Fetch error: ' + e.message;
  }
}

function copyMakeOutput() {
  navigator.clipboard.writeText(document.getElementById('make-output-text').textContent);
}
function clearMakeOutput() {
  document.getElementById('make-output-text').textContent = 'Run a make target to see output here.';
  document.getElementById('make-output-cmd').textContent = 'Output';
  document.getElementById('make-output-header').style.borderBottomColor = '';
}

// ── Addons Profile Editor ──────────────────────────────────────────────────────
let allProfiles = {};
let currentEditProfile = '';

async function openProfileModal() {
  const r = await fetch('/api/addons-profiles');
  allProfiles = await r.json();
  renderProfileTabs();
  const firstProfile = Object.keys(allProfiles)[0] || 'ryt';
  selectProfileTab(firstProfile);
  document.getElementById('profile-modal').style.display = 'flex';
}

function closeProfileModal() {
  document.getElementById('profile-modal').style.display = 'none';
}

const BUILTIN_PROFILES = new Set(['ryt', 'std', 'dk', 'dd', 'sme']);

function renderProfileTabs() {
  const profileColors = {ryt:'text-blue-400', std:'text-purple-400', dk:'text-teal-400', dd:'text-yellow-400', sme:'text-pink-400'};
  const tabs = Object.keys(allProfiles).map(name => {
    const col = profileColors[name] || 'text-gray-300';
    const isCustom = !BUILTIN_PROFILES.has(name);
    return `<div class="flex items-center gap-1 group" id="ptab-row-${name}">
      <button id="ptab-${name}" onclick="selectProfileTab('${escHtml(name)}')"
        class="flex-1 text-left px-2 py-1.5 rounded text-sm font-mono ${col} hover:bg-gray-700">${escHtml(name)}</button>
      ${isCustom ? `<button onclick="deleteProfile('${escHtml(name)}')" title="Delete"
        class="hidden group-hover:block text-xs text-gray-600 hover:text-red-400 px-1">✕</button>` : ''}
    </div>`;
  }).join('');
  document.getElementById('profile-tabs').innerHTML = tabs +
    `<button onclick="createNewProfile()" id="new-profile-btn"
      class="text-left px-2 py-1.5 rounded text-xs text-gray-400 hover:bg-gray-700 border border-dashed border-gray-600 mt-auto">+ New profile</button>`;
}

function selectProfileTab(name) {
  currentEditProfile = name;
  // Highlight active tab
  document.querySelectorAll('[id^="ptab-"]').forEach(b => b.classList.remove('bg-gray-700', 'ring-1', 'ring-gray-500'));
  const btn = document.getElementById('ptab-' + name);
  if (btn) btn.classList.add('bg-gray-700', 'ring-1', 'ring-gray-500');

  document.getElementById('profile-editor-title').textContent = name;
  document.getElementById('profile-save-status').classList.add('hidden');
  renderProfilePaths(allProfiles[name] || []);
}

function renderProfilePaths(paths) {
  document.getElementById('profile-paths-list').innerHTML = paths.map((p, i) => `
    <div class="flex items-center gap-2 group" id="path-row-${i}">
      <span class="text-xs text-gray-500 w-4 text-right shrink-0">${i + 1}</span>
      <input type="text" value="${escHtml(p)}" id="path-input-${i}"
        class="flex-1 text-xs py-0.5 font-mono"
        onchange="updateLocalPath(${i}, this.value)">
      <button onclick="movePathUp(${i})" class="text-gray-600 hover:text-gray-300 text-xs ${i===0?'invisible':''}">↑</button>
      <button onclick="movePathDown(${i})" class="text-gray-600 hover:text-gray-300 text-xs ${i===paths.length-1?'invisible':''}">↓</button>
      <button onclick="removePath(${i})" class="text-gray-600 hover:text-red-400 text-xs">✕</button>
    </div>`).join('');
}

function updateLocalPath(i, value) {
  allProfiles[currentEditProfile][i] = value;
}

function movePathUp(i) {
  const paths = allProfiles[currentEditProfile];
  if (i === 0) return;
  [paths[i-1], paths[i]] = [paths[i], paths[i-1]];
  renderProfilePaths(paths);
}

function movePathDown(i) {
  const paths = allProfiles[currentEditProfile];
  if (i >= paths.length - 1) return;
  [paths[i], paths[i+1]] = [paths[i+1], paths[i]];
  renderProfilePaths(paths);
}

function removePath(i) {
  allProfiles[currentEditProfile].splice(i, 1);
  renderProfilePaths(allProfiles[currentEditProfile]);
}

function addProfilePath() {
  const input = document.getElementById('new-path-input');
  const val = input.value.trim();
  if (!val) return;
  allProfiles[currentEditProfile] = allProfiles[currentEditProfile] || [];
  allProfiles[currentEditProfile].push(val);
  renderProfilePaths(allProfiles[currentEditProfile]);
  input.value = '';
}

async function saveCurrentProfile() {
  const paths = allProfiles[currentEditProfile] || [];
  const r = await fetch(`/api/addons-profiles/${currentEditProfile}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paths})
  });
  if (r.ok) {
    const status = document.getElementById('profile-save-status');
    status.classList.remove('hidden');
    setTimeout(() => status.classList.add('hidden'), 2000);
  } else {
    const d = await r.json();
    alert(d.detail || 'Save failed');
  }
}

function createNewProfile() {
  if (document.getElementById('new-profile-input-row')) {
    document.getElementById('new-profile-input').focus();
    return;
  }
  const tabs = document.getElementById('profile-tabs');
  const btn = document.getElementById('new-profile-btn');
  const row = document.createElement('div');
  row.id = 'new-profile-input-row';
  row.className = 'flex flex-col gap-1 px-1 py-1';
  row.innerHTML = `
    <input type="text" id="new-profile-input" placeholder="profile name…"
      class="text-xs py-0.5 w-full font-mono" maxlength="20" autocomplete="off"
      onkeydown="if(event.key==='Enter')confirmNewProfile();if(event.key==='Escape')cancelNewProfile()">
    <div class="flex gap-1">
      <button onclick="confirmNewProfile()" class="text-xs px-2 py-0.5 bg-blue-700 hover:bg-blue-600 rounded flex-1">Add</button>
      <button onclick="cancelNewProfile()" class="text-xs px-2 py-0.5 bg-gray-700 hover:bg-gray-600 rounded">✕</button>
    </div>`;
  if (btn) tabs.insertBefore(row, btn); else tabs.appendChild(row);
  document.getElementById('new-profile-input').focus();
}

function cancelNewProfile() {
  document.getElementById('new-profile-input-row')?.remove();
}

function confirmNewProfile() {
  const input = document.getElementById('new-profile-input');
  if (!input) return;
  const name = input.value.toLowerCase().replace(/[^a-z0-9_]/g, '');
  if (!name) { input.focus(); return; }
  cancelNewProfile();
  if (allProfiles[name]) { selectProfileTab(name); return; }
  allProfiles[name] = [];
  renderProfileTabs();
  selectProfileTab(name);
}

async function deleteProfile(name) {
  if (!confirm(`Delete profile "${name}"? This cannot be undone.`)) return;
  const r = await fetch(`/api/addons-profiles/${name}`, {method: 'DELETE'});
  if (r.ok) {
    delete allProfiles[name];
    renderProfileTabs();
    const remaining = Object.keys(allProfiles);
    if (remaining.length) selectProfileTab(remaining[0]);
  } else {
    const d = await r.json();
    alert(d.detail || 'Delete failed');
  }
}

async function resetProfileToDefault() {
  const defaults = {
    std: ['/home/server/odoo-17.0/addons','/home/server/odoo-17.0/std-odoo17c/std_bs_apps','/home/server/odoo-17.0/std-odoo17c/std_third_apps_free','/home/server/odoo-17.0/std-odoo17c/std_third_apps_license'],
    ryt: ['/home/server/odoo-17.0/addons','/home/server/odoo-17.0/std-odoo17c/std_bs_apps','/home/server/odoo-17.0/std-odoo17c/std_third_apps_free','/home/server/odoo-17.0/std-odoo17c/std_third_apps_license','/home/server/odoo-17.0/ryt-odoo17c/spc_bs_apps','/home/server/odoo-17.0/ryt-odoo17c/spc_third_apps_free','/home/server/odoo-17.0/ryt-odoo17c/spc_third_apps_license'],
    dk: ['/home/server/odoo-17.0/addons','/home/server/odoo-17.0/std-odoo17c/std_bs_apps','/home/server/odoo-17.0/std-odoo17c/std_third_apps_free','/home/server/odoo-17.0/std-odoo17c/std_third_apps_license','/home/server/odoo-17.0/dk-odoo17c/spc_bs_apps','/home/server/odoo-17.0/dk-odoo17c/spc_third_apps_free','/home/server/odoo-17.0/dk-odoo17c/spc_third_apps_license'],
    dd: ['/home/server/odoo-17.0/addons','/home/server/odoo-17.0/std-odoo17c/std_bs_apps','/home/server/odoo-17.0/std-odoo17c/std_third_apps_free','/home/server/odoo-17.0/std-odoo17c/std_third_apps_license','/home/server/odoo-17.0/dd-odoo17c/std_bs_apps','/home/server/odoo-17.0/dd-odoo17c/std_third_apps_free','/home/server/odoo-17.0/dd-odoo17c/std_third_apps_license','/home/server/odoo-17.0/dd-odoo17c/spc_bs_apps','/home/server/odoo-17.0/dd-odoo17c/spc_third_apps_free','/home/server/odoo-17.0/dd-odoo17c/spc_third_apps_license'],
    sme: ['/home/server/odoo-17.0/addons','/home/server/odoo-17.0/std-odoo17c/std_bs_apps','/home/server/odoo-17.0/std-odoo17c/std_third_apps_free','/home/server/odoo-17.0/std-odoo17c/std_third_apps_license','/home/server/odoo-17.0/sme-odoo17c/spc_bs_apps','/home/server/odoo-17.0/sme-odoo17c/spc_third_apps_free','/home/server/odoo-17.0/sme-odoo17c/spc_third_apps_license'],
  };
  if (defaults[currentEditProfile]) {
    allProfiles[currentEditProfile] = [...defaults[currentEditProfile]];
    renderProfilePaths(allProfiles[currentEditProfile]);
  }
}

// ── LINE Log ───────────────────────────────────────────────────────────────────
let lineLogReader = null;

function toggleLineLog() {
  const panel = document.getElementById('line-log-panel');
  const isHidden = panel.classList.contains('hidden');
  if (isHidden) {
    panel.classList.remove('hidden');
    restartLineLog();
  } else {
    panel.classList.add('hidden');
    stopLineLog();
  }
}

function stopLineLog() {
  if (lineLogReader) { try { lineLogReader.cancel(); } catch {} lineLogReader = null; }
}

async function restartLineLog() {
  stopLineLog();
  const source = document.getElementById('line-log-source').value;
  const el = document.getElementById('line-log-text');
  const scroll = document.getElementById('line-log-scroll');
  el.textContent = '';
  try {
    const resp = await fetch(`/api/line/log?source=${source}`);
    const reader = resp.body.getReader();
    lineLogReader = reader;
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.text) {
            el.textContent += evt.text;
            scroll.scrollTop = scroll.scrollHeight;
          }
        } catch {}
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') el.textContent += `\n[Error: ${e.message}]`;
  }
}

// ── Odoo Stop + Log ────────────────────────────────────────────────────────────
let odooLogReader = null;

function toggleOdooLog() {
  const panel = document.getElementById('odoo-log-panel');
  const isHidden = panel.classList.contains('hidden');
  if (isHidden) {
    panel.classList.remove('hidden');
    restartOdooLog();
  } else {
    panel.classList.add('hidden');
    stopOdooLog();
  }
}

function stopOdooLog() {
  if (odooLogReader) { try { odooLogReader.cancel(); } catch {} odooLogReader = null; }
}

async function restartOdooLog() {
  stopOdooLog();
  const el = document.getElementById('odoo-log-text');
  const scroll = document.getElementById('odoo-log-scroll');
  el.textContent = '';
  try {
    const resp = await fetch('/api/odoo/log');
    const reader = resp.body.getReader();
    odooLogReader = reader;
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.text) {
            el.textContent += evt.text;
            scroll.scrollTop = scroll.scrollHeight;
          }
        } catch {}
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') el.textContent += `\n[Error: ${e.message}]`;
  }
}

async function startOdoo() {
  const dot = document.getElementById('odoo-dot');
  const txt = document.getElementById('odoo-status-text');
  const startBtn = document.getElementById('start-odoo-btn');
  dot.className = 'w-2 h-2 rounded-full dot-yellow';
  txt.textContent = 'Starting Odoo…';
  if (startBtn) startBtn.disabled = true;
  try {
    const r = await fetch('/api/odoo/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    const d = await r.json();
    if (d.status === 'already_running') {
      if (startBtn) startBtn.disabled = false;
      refreshOdooStatus();
      return;
    }
    if (d.status === 'error') {
      txt.textContent = `Start failed: ${d.detail || 'unknown error'}`;
      dot.className = 'w-2 h-2 rounded-full dot-gray';
      if (startBtn) startBtn.disabled = false;
      return;
    }
    // Poll until running (max 40s)
    const start = Date.now();
    const poll = setInterval(async () => {
      const elapsed = ((Date.now() - start) / 1000).toFixed(0);
      txt.textContent = `Starting… ${elapsed}s`;
      const st = await fetch('/api/odoo/status').then(x => x.json()).catch(() => null);
      if (st && st.running) {
        clearInterval(poll);
        if (startBtn) startBtn.disabled = false;
        refreshOdooStatus();
        loadDatabases();
      } else if (Date.now() - start > 40000) {
        clearInterval(poll);
        txt.textContent = 'Start timed out — check log';
        if (startBtn) startBtn.disabled = false;
        refreshOdooStatus();
      }
    }, 800);
  } catch (e) {
    alert(e.message);
    refreshOdooStatus();
    if (startBtn) startBtn.disabled = false;
  }
}

async function restartOdoo() {
  const confirmed = await openModal('Restart Odoo', 'Restart the Odoo service? It will reload with the same database and config.');
  if (!confirmed) return;
  const dot = document.getElementById('odoo-dot');
  const txt = document.getElementById('odoo-status-text');
  const restartBtn = document.getElementById('restart-odoo-btn');
  const stopBtn = document.getElementById('stop-odoo-btn');
  dot.className = 'w-2 h-2 rounded-full dot-yellow';
  txt.textContent = 'Restarting Odoo…';
  if (restartBtn) restartBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
  try {
    const r = await fetch('/api/odoo/restart', {method: 'POST'});
    const d = await r.json();
    if (d.status === 'not_running') {
      refreshOdooStatus();
      if (restartBtn) restartBtn.disabled = false;
      if (stopBtn) stopBtn.disabled = false;
      return;
    }
    // Poll: wait for it to stop, then wait for it to come back up
    let phase = 'stopping';
    const start = Date.now();
    const poll = setInterval(async () => {
      const elapsed = ((Date.now() - start) / 1000).toFixed(0);
      const st = await fetch('/api/odoo/status').then(x => x.json()).catch(() => null);
      if (phase === 'stopping') {
        txt.textContent = `Stopping… ${elapsed}s`;
        if (st && !st.running) phase = 'starting';
      } else {
        txt.textContent = `Starting… ${elapsed}s`;
        if (st && st.running) {
          clearInterval(poll);
          if (restartBtn) restartBtn.disabled = false;
          if (stopBtn) stopBtn.disabled = false;
          refreshOdooStatus();
          loadDatabases();
          return;
        }
      }
      if (Date.now() - start > 40000) {
        clearInterval(poll);
        if (restartBtn) restartBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = false;
        refreshOdooStatus();
      }
    }, 800);
  } catch (e) {
    alert(e.message);
    refreshOdooStatus();
    if (restartBtn) restartBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = false;
  }
}

async function stopOdoo() {
  const confirmed = await openModal('Stop Odoo', 'Stop the Odoo service? Use the ▶ Start Odoo button to bring it back up.');
  if (!confirmed) return;
  const dot = document.getElementById('odoo-dot');
  const txt = document.getElementById('odoo-status-text');
  dot.className = 'w-2 h-2 rounded-full dot-yellow';
  txt.textContent = 'Sending stop signal…';
  const stopBtn = document.getElementById('stop-odoo-btn');
  if (stopBtn) stopBtn.disabled = true;
  try {
    const r = await fetch('/api/odoo/stop', {method: 'POST'});
    const d = await r.json();
    if (d.status === 'not_running') {
      refreshOdooStatus();
      if (stopBtn) stopBtn.disabled = false;
      return;
    }
    // Poll until process is gone (max 15s), showing elapsed time
    txt.textContent = 'Stopping Odoo…';
    const start = Date.now();
    const poll = setInterval(async () => {
      const elapsed = ((Date.now() - start) / 1000).toFixed(0);
      txt.textContent = `Stopping Odoo… ${elapsed}s`;
      const st = await fetch('/api/odoo/status').then(x => x.json()).catch(() => null);
      if (!st || !st.running) {
        clearInterval(poll);
        if (stopBtn) stopBtn.disabled = false;
        refreshOdooStatus();
        loadDatabases();
      } else if (Date.now() - start > 12000) {
        // Force-kill after 12s
        clearInterval(poll);
        txt.textContent = 'Force-killing…';
        await fetch('/api/odoo/stop', {method: 'POST'}).catch(() => {});
        setTimeout(() => { refreshOdooStatus(); loadDatabases(); if (stopBtn) stopBtn.disabled = false; }, 1500);
      }
    }, 600);
  } catch (e) {
    alert(e.message);
    refreshOdooStatus();
    if (stopBtn) stopBtn.disabled = false;
  }
}

// ── Board Tab ──────────────────────────────────────────────────────────────────
const TYPE_COLORS = { mermaid: 'bg-purple-700 text-purple-200', markdown: 'bg-blue-800 text-blue-200', table: 'bg-teal-800 text-teal-200' };
const TYPE_LABELS = { mermaid: 'Mermaid', markdown: 'Markdown', table: 'Table' };

async function loadBoard() {
  const grid = document.getElementById('board-grid');
  grid.innerHTML = '<div class="text-center text-gray-500 py-12 col-span-full">Loading…</div>';
  const r = await fetch('/api/board');
  const items = await r.json();
  _boardItems = items;
  if (!items.length) {
    grid.innerHTML = '<div class="text-center text-gray-500 py-12 col-span-full">No explanations yet — click + New Explanation to add one.</div>';
    return;
  }
  grid.innerHTML = items.map(item => `
    <div class="bg-gray-800 border border-gray-700 rounded-xl flex flex-col overflow-hidden hover:border-gray-500 transition-colors">
      <div class="flex items-start gap-2 px-4 pt-4 pb-2">
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-sm truncate">${escHtml(item.title)}</div>
          ${item.task_number ? `<div class="text-xs text-orange-400 mt-0.5">📋 ${escHtml(item.task_number)}</div>` : ''}
          ${item.session_title ? `<div class="text-xs text-gray-500 truncate mt-0.5">${escHtml(item.session_title)}</div>` : ''}
        </div>
        <span class="shrink-0 text-xs px-2 py-0.5 rounded-full ${TYPE_COLORS[item.content_type] || TYPE_COLORS.markdown}">${TYPE_LABELS[item.content_type] || item.content_type}</span>
      </div>
      <div class="px-4 pb-3 flex-1 overflow-hidden" style="max-height:160px">
        ${item.content_type === 'mermaid'
          ? `<pre class="text-xs text-purple-300 font-mono overflow-hidden" style="max-height:120px">${escHtml(item.content.slice(0, 300))}${item.content.length > 300 ? '…' : ''}</pre>`
          : `<div class="text-xs text-gray-400 font-mono overflow-hidden" style="max-height:120px">${escHtml(item.content.slice(0, 400))}${item.content.length > 400 ? '…' : ''}</div>`}
      </div>
      <div class="flex items-center gap-2 px-4 py-2 border-t border-gray-700 bg-gray-900 shrink-0">
        <span class="text-xs text-gray-600">${item.created_at ? item.created_at.slice(0,10) : ''}</span>
        <button onclick="expandBoardItem(${item.id})" class="ml-auto text-xs text-blue-400 hover:text-blue-300">Expand</button>
        <button onclick="openEditBoardModal(${item.id})" class="text-xs text-gray-400 hover:text-gray-200">Edit</button>
        <button onclick="deleteBoardItem(${item.id})" class="text-xs text-gray-600 hover:text-red-400">Delete</button>
      </div>
    </div>`).join('');
}

let _boardItems = [];

let _boardZoom = 1.0;

function boardZoom(delta) {
  _boardZoom = Math.min(Math.max(_boardZoom + delta, 0.2), 4.0);
  _applyBoardZoom();
}

function boardZoomFit() {
  _boardZoom = 1.0;
  _applyBoardZoom();
}

function _applyBoardZoom() {
  const cont = document.getElementById('board-expand-content');
  cont.style.transform = `scale(${_boardZoom})`;
  document.getElementById('board-zoom-label').textContent = Math.round(_boardZoom * 100) + '%';
}

async function expandBoardItem(id) {
  if (!_boardItems.length) {
    const r = await fetch('/api/board');
    _boardItems = await r.json();
  }
  const item = _boardItems.find(i => i.id === id);
  if (!item) return;
  document.getElementById('board-expand-title').textContent = item.title;
  const badge = document.getElementById('board-expand-type-badge');
  badge.textContent = TYPE_LABELS[item.content_type] || item.content_type;
  badge.className = 'text-xs px-2 py-0.5 rounded-full ' + (TYPE_COLORS[item.content_type] || TYPE_COLORS.markdown);
  document.getElementById('board-expand-session').textContent = item.session_title ? '💬 ' + item.session_title : '';
  document.getElementById('board-expand-task').textContent = item.task_number ? '📋 ' + item.task_number : '';
  document.getElementById('board-expand-date').textContent = item.created_at ? item.created_at.slice(0,16).replace('T',' ') : '';
  const cont = document.getElementById('board-expand-content');
  const isMermaid = item.content_type === 'mermaid';
  // Reset zoom
  _boardZoom = 1.0;
  cont.style.transform = 'scale(1)';
  cont.style.transformOrigin = 'top left';
  document.getElementById('board-zoom-controls').classList.toggle('hidden', !isMermaid);
  document.getElementById('board-zoom-label').textContent = '100%';
  if (isMermaid) {
    cont.innerHTML = `<pre class="mermaid">${escHtml(item.content)}</pre>`;
    mermaid.run({ nodes: cont.querySelectorAll('.mermaid') });
  } else {
    cont.innerHTML = DOMPurify.sanitize(marked.parse(item.content));
  }
  document.getElementById('board-expand-modal').style.display = 'flex';
  // Scroll-to-zoom for mermaid
  const scroll = document.getElementById('board-expand-scroll');
  scroll.onwheel = isMermaid ? (e => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    boardZoom(e.deltaY < 0 ? 0.1 : -0.1);
  }) : null;
  if (isMermaid) scroll.style.cursor = 'zoom-in';
  else scroll.style.cursor = 'default';
}

function closeBoardExpandModal() {
  document.getElementById('board-expand-modal').style.display = 'none';
  document.getElementById('board-expand-scroll').onwheel = null;
}

document.addEventListener('keydown', e => {
  const modal = document.getElementById('board-expand-modal');
  if (modal.style.display === 'none') return;
  if (e.key === 'Escape') { closeBoardExpandModal(); return; }
  if (e.key === '+' || e.key === '=') { e.preventDefault(); boardZoom(+0.2); }
  if (e.key === '-') { e.preventDefault(); boardZoom(-0.2); }
  if (e.key === '0') { e.preventDefault(); boardZoomFit(); }
});

async function deleteBoardItem(id) {
  if (!confirm('Delete this explanation?')) return;
  await fetch('/api/board/' + id, { method: 'DELETE' });
  _boardItems = _boardItems.filter(i => i.id !== id);
  loadBoard();
}

let _editingBoardId = null;

function openAddBoardModal() {
  _editingBoardId = null;
  document.getElementById('board-modal-title').textContent = 'New Explanation';
  document.getElementById('board-new-title').value = '';
  document.getElementById('board-new-task').value = '';
  document.getElementById('board-new-content').value = '';
  document.getElementById('board-new-type').value = 'mermaid';
  document.getElementById('board-preview-wrap').classList.add('hidden');
  updateBoardTypeHint();
  document.getElementById('board-add-modal').style.display = 'flex';
}

function openEditBoardModal(id) {
  const item = _boardItems.find(i => i.id === id);
  if (!item) return;
  _editingBoardId = id;
  document.getElementById('board-modal-title').textContent = 'Edit Explanation';
  document.getElementById('board-new-title').value = item.title || '';
  document.getElementById('board-new-task').value = item.task_number || '';
  document.getElementById('board-new-content').value = item.content || '';
  document.getElementById('board-new-type').value = item.content_type === 'mermaid' ? 'mermaid' : 'markdown';
  document.getElementById('board-preview-wrap').classList.add('hidden');
  updateBoardTypeHint();
  document.getElementById('board-add-modal').style.display = 'flex';
}

function closeBoardAddModal() {
  document.getElementById('board-add-modal').style.display = 'none';
  _editingBoardId = null;
}

function updateBoardTypeHint() {
  const t = document.getElementById('board-new-type').value;
  const hint = document.getElementById('board-type-hint');
  hint.textContent = t === 'mermaid' ? '(flowchart TD, sequenceDiagram, classDiagram, erDiagram…)' : '(GitHub Flavored Markdown — tables, headings, lists…)';
}

function previewBoardContent() {
  const type = document.getElementById('board-new-type').value;
  const content = document.getElementById('board-new-content').value;
  const wrap = document.getElementById('board-preview-wrap');
  const cont = document.getElementById('board-preview-content');
  wrap.classList.remove('hidden');
  if (type === 'mermaid') {
    const id = 'mermaid-prev-' + Date.now();
    cont.innerHTML = `<pre class="mermaid" id="${id}">${escHtml(content)}</pre>`;
    mermaid.run({ nodes: [cont.querySelector('.mermaid')] });
  } else {
    cont.innerHTML = DOMPurify.sanitize(marked.parse(content));
  }
}

async function saveBoardItem() {
  const title = document.getElementById('board-new-title').value.trim();
  const content = document.getElementById('board-new-content').value.trim();
  const content_type = document.getElementById('board-new-type').value;
  const task_number = document.getElementById('board-new-task').value.trim();
  if (!title) { alert('Please enter a title.'); return; }
  if (!content) { alert('Please enter content.'); return; }
  const editing = _editingBoardId !== null;
  const r = await fetch(editing ? '/api/board/' + _editingBoardId : '/api/board', {
    method: editing ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content, content_type, task_number })
  });
  if (r.ok) {
    closeBoardAddModal();
    loadBoard();
  } else {
    alert('Save failed.');
  }
}

// ── Utility ────────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ───────────────────────────────────────────────────────────────────────
loadSessions();
