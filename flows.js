// Flow definitions and execution history are separate: runs retain their own snapshots.
let _allFlows = [], _selectedFlow = null, _selectedRun = null;
let _flowName = null, _runOffset = 0, _runTotal = 0;
let _runRequest = 0, _detailRequest = 0;
const statusLabels = { passed: 'Passed', failed: 'Failed', running: 'Running', stale: 'No recent update', unknown: 'Unknown result' };
function fmtBytes(n) {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${units[i]}`;
}
function runTags(run) {
  let out = '';
  if (run.safe_to_delete) out += '<span class="text-xs px-1 rounded bg-amber-900/60 text-amber-200">safe to delete</span>';
  if (run.trace_purged_at) out += '<span class="text-xs px-1 rounded bg-gray-700 text-gray-300">trace removed</span>';
  return out;
}
function runBadge(status) {
  const color = { passed: 'text-green-300 bg-green-900', failed: 'text-red-300 bg-red-900', running: 'text-blue-300 bg-blue-900', stale: 'text-yellow-300 bg-yellow-900', unknown: 'text-gray-300 bg-gray-700' }[status] || 'text-gray-300 bg-gray-700';
  return `<span class="badge ${color}">${escHtml(statusLabels[status] || status)}</span>`;
}
function runDuration(ms) {
  return ms === null || ms === undefined ? '—' : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
function renderFailureSummary(report) {
  const s = summarizeFailure(report);
  const links = (rpcs, label) => rpcs.length ? `<p class="mt-2 font-medium">${label}</p>${rpcs.slice(0,5).map(r=>`<a class="block underline text-red-300" href="#rpc-${escHtml(r.request_id)}">${escHtml(r.model ? r.model+'.'+r.method : r.endpoint)}: ${escHtml(r.error?.message || r.status)}</a>${r.error?.traceback ? `<details class="text-xs my-1"><summary class="cursor-pointer">Returned Python traceback</summary><pre class="whitespace-pre-wrap break-words">${escHtml(r.error.traceback)}</pre></details>` : ''}`).join('')}${rpcs.length>5 ? `<p>${rpcs.length-5} more errors in the step details below.</p>` : ''}` : '';
  return `<section id="failure-summary" class="border border-gray-700 rounded p-3 my-3 text-sm">
    <strong>${escHtml(s.headline)}</strong>
    ${s.primary ? `<a class="block underline mt-1" href="#step-${escHtml(s.primary.step_id || s.primary.line)}">${escHtml(s.primary.command)}</a><pre class="text-red-300 whitespace-pre-wrap break-words">${escHtml(s.primary.error || 'No error message recorded')}</pre>` : ''}
    ${s.failed_count>1 ? `<p>${s.failed_count} failed steps in total.</p>` : ''}
    ${s.run_error ? `<pre class="text-red-300 whitespace-pre-wrap">${escHtml(s.run_error)}</pre>` : ''}
    ${links(s.linked, 'RPC errors during this step')}${links(s.nearby, 'Possibly related earlier RPC errors')}${links(s.other, 'Other RPC errors in this run')}
    ${s.note ? `<p class="text-gray-400 mt-2">${escHtml(s.note)}</p>` : ''}
  </section>`;
}
function renderPythonTrace(trace) {
  if (!trace) return '';
  const calls = Array.isArray(trace.calls) ? trace.calls : [];
  return `<section class="mt-3 border-t border-gray-700 pt-2"><strong>Python execution · ${escHtml(trace.status)}</strong>
    ${trace.note ? `<p class="text-yellow-300">${escHtml(trace.note)}</p>` : ''}
    ${trace.status==='partial' ? '<p class="text-yellow-300">Capture is partial; the call/time limit was reached or profiling was interrupted.</p>' : ''}
    ${calls.length ? `<p class="text-gray-400">${calls.length} calls · ${runDuration(trace.duration_ms)} · ${escHtml(trace.db || '')}. Inclusive timings include nested calls and observer overhead.</p>
      <details data-python-sequence class="mt-2"><summary class="cursor-pointer">Executed call sequence</summary><ol class="space-y-2 mt-2">${calls.map(c=>`<li class="border-l border-gray-600 pl-2"><span class="text-gray-400">#${escHtml(c.id)}${c.parent_id ? ' ← #'+escHtml(c.parent_id) : ''} · ${runDuration(c.duration_ms)}${c.complete?'':' · incomplete'}</span><p>${escHtml(c.model || c.module)} · ${escHtml(c.function)}</p><p class="text-gray-500 break-all">${escHtml(c.file)}:${escHtml(c.line)}</p></li>`).join('')}</ol></details>` : ''}
  </section>`;
}
function renderRuntimeRequests(requests, openIds = new Set()) {
  return requests.map(rpc => {
    const error = rpc.error || {};
    const failed = ['rpc_error', 'http_error', 'network_error'].includes(rpc.status);
    return `<details id="rpc-${escHtml(rpc.request_id)}" data-rpc-id="${escHtml(rpc.request_id)}" ${openIds.has(rpc.request_id) ? 'open' : ''} class="my-2 p-2 border border-gray-700 rounded">
      <summary class="cursor-pointer ${failed ? 'text-red-300' : 'text-gray-300'}">RPC · ${escHtml(rpc.model ? `${rpc.model}.${rpc.method}` : rpc.endpoint)} · ${escHtml(rpc.status)} · ${runDuration(rpc.duration_ms)}</summary>
      <p class="break-all text-gray-500 my-1">${escHtml(rpc.request_id)} · HTTP ${escHtml(rpc.http_status ?? '—')}</p>
      <p class="break-all text-gray-400">${escHtml(rpc.endpoint)} · JSON-RPC ID ${escHtml(JSON.stringify(rpc.rpc_id) ?? 'not provided')}</p>
      <details class="my-2"><summary class="cursor-pointer">Request parameters</summary><pre class="whitespace-pre-wrap break-words">${escHtml(JSON.stringify(rpc.params, null, 2))}</pre></details>
      ${error.message ? `<pre class="text-red-300 whitespace-pre-wrap break-words">${escHtml(error.name || '')} ${escHtml(error.message)}</pre>` : ''}
      ${error.traceback ? `<p class="text-gray-400 mt-2">Python traceback returned by this RPC</p><pre class="whitespace-pre-wrap break-words">${escHtml(error.traceback)}</pre>` : ''}
      ${renderPythonTrace(rpc.python_trace)}
      ${rpc.capture_note ? `<p class="text-yellow-300">${escHtml(rpc.capture_note)}</p>` : ''}
    </details>`;
  }).join('');
}

async function flowJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
async function loadFlows(quiet = false) {
  try {
    _allFlows = await flowJSON('/api/flows');
    filterFlows();
    await loadFlowRuns(false, quiet);
  } catch (error) {
    document.getElementById('flow-history-message').textContent = `Could not load history: ${error.message}`;
  }
}
function filterFlows() {
  const terms = document.getElementById('flow-search').value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const flows = _allFlows.filter(flow => {
    const hay = [flow.name, flow.task_number, flow.session_title, flow.db_name, flow.latest_run?.task_number, flow.latest_run?.db_name].join(' ').toLowerCase();
    return terms.every(term => hay.includes(term));
  });
  document.getElementById('flow-list').innerHTML = flows.length ? flows.map(flow => `
    <button class="flow-row text-left p-3 rounded-lg border ${_flowName === flow.name ? 'border-blue-500 bg-blue-950/30' : 'border-gray-700 bg-gray-800/50'}" onclick="selectFlow(${escHtml(JSON.stringify(flow.name))})">
      <span class="block font-mono text-sm break-words">${escHtml(flow.name)}</span>
      <span class="flex items-center gap-2 flex-wrap mt-1 text-xs text-gray-400">${flow.latest_run ? runBadge(flow.latest_run.status) : '<span>No runs yet</span>'}<span>${flow.run_count || 0} runs</span></span>
      <span class="block text-xs text-gray-500 mt-1">${escHtml(flow.db_name || flow.latest_run?.db_name || '')} ${escHtml(flow.task_number || '')}</span>
    </button>`).join('') : '<p class="text-xs text-gray-500 p-2">No matching flows.</p>';
}
async function selectFlow(name) {
  _flowName = name; _selectedFlow = null; _selectedRun = null; _detailRequest++;
  filterFlows();
  document.getElementById('flow-history-title').textContent = name || 'All runs';
  document.getElementById('flow-run-detail').innerHTML = '<p class="text-gray-500">Select a run to inspect its steps and captured flow.</p>';
  document.getElementById('flow-definition').classList.add('hidden');
  const entry = _allFlows.find(flow => flow.name === name);
  if (entry?.saved) {
    try {
      const flow = await flowJSON('/api/flows/' + encodeURIComponent(name));
      if (_flowName !== name) return;
      _selectedFlow = flow;
      document.getElementById('flow-preview-content').textContent = flow.content;
      document.getElementById('flow-definition').classList.remove('hidden');
    } catch (error) { document.getElementById('flow-history-message').textContent = error.message; }
  }
  await loadFlowRuns(true);
}
async function loadFlowRuns(reset = true, quiet = false) {
  const request = ++_runRequest;
  if (reset) _runOffset = 0;
  const params = new URLSearchParams({ limit: '50', offset: String(_runOffset) });
  if (_flowName !== null) params.set('flow_name', _flowName);
  const status = document.getElementById('flow-status-filter').value;
  if (status) params.set('status', status);
  try {
    const data = await flowJSON('/api/flow-runs?' + params);
    if (request !== _runRequest) return;
    _runTotal = data.total;
    document.getElementById('flow-history-message').textContent = data.total ? `${data.total} runs${_runOffset ? ` · showing ${_runOffset + 1}–${_runOffset + data.runs.length}` : ''}` : 'No runs match this selection.';
    document.getElementById('flow-run-list').innerHTML = data.runs.map(run => `
      <button class="run-row text-left p-3 rounded-lg border ${_selectedRun === run.run_id ? 'border-blue-500 bg-blue-950/30' : 'border-gray-700 bg-gray-800/50'}" onclick="selectRun(${escHtml(JSON.stringify(run.run_id))})" data-run-id="${escHtml(run.run_id)}">
        <span class="flex items-center gap-2 flex-wrap">${runBadge(run.status)}<span class="font-medium text-sm">${escHtml(run.flow_name)}</span>${runTags(run)}<span class="text-xs text-gray-400 ml-auto">${runDuration(run.duration_ms)}</span></span>
        <span class="block text-xs text-gray-400 mt-1">${escHtml(new Date(run.started_at).toLocaleString())} · ${escHtml(run.db_name || 'Database not recorded')} ${escHtml(run.task_number || '')}</span>
      </button>`).join('');
    document.getElementById('flow-runs-prev').disabled = _runOffset === 0;
    document.getElementById('flow-runs-next').disabled = _runOffset + 50 >= data.total;
    if (_selectedRun && data.runs.some(run => run.run_id === _selectedRun)) await selectRun(_selectedRun);
    refreshTagSummary();
  } catch (error) {
    if (request === _runRequest && !quiet) document.getElementById('flow-history-message').textContent = `Could not load runs: ${error.message}`;
  }
}
function pageFlowRuns(direction) { _runOffset = Math.max(0, _runOffset + direction * 50); loadFlowRuns(false); }
async function selectRun(id) {
  _selectedRun = id;
  const request = ++_detailRequest;
  document.querySelectorAll('.run-row').forEach(row => row.classList.toggle('border-blue-500', row.dataset.runId === id));
  const detail = document.getElementById('flow-run-detail');
  try {
    const run = await flowJSON('/api/flow-runs/' + encodeURIComponent(id));
    if (request !== _detailRequest) return;
    const version = JSON.stringify([run.updated_at, run.status, run.note, run.safe_to_delete, run.trace_purged_at]);
    if (detail.dataset.runId === id && detail.dataset.version === version && detail.querySelector('#failure-summary')) return;
    detail.dataset.version = version;
    const snapshotOpen = detail.dataset.runId === id && detail.querySelector('[data-flow-snapshot]')?.open;
    const openRpcIds = new Set(detail.dataset.runId === id ? [...detail.querySelectorAll('[data-rpc-id][open]')].map(el => el.dataset.rpcId) : []);
    detail.dataset.runId = id;
    const report = run.report, steps = report.steps || [], flow = report.flow;
    const rpcs = Array.isArray(report.runtime?.requests) ? report.runtime.requests : [];
    const rpcErrors = rpcs.filter(rpc => ['rpc_error', 'http_error', 'network_error'].includes(rpc.status));
    const failed = steps.filter(step => step.status === 'failed');
    const links = Object.entries(run.artifacts).map(([kind, url]) => `<a class="underline text-blue-300" href="${escHtml(url)}" target="_blank" rel="noopener">${{ trace: 'Trace ZIP', log: 'Log', result: 'Result JSON', flow: 'Flow snapshot' }[kind]}</a>`).join(' · ');
    detail.innerHTML = `
      <div class="flex gap-2 items-center flex-wrap">${runBadge(run.status)}<strong>${escHtml(run.flow_name)}</strong><span class="text-xs text-gray-400">${runDuration(run.duration_ms)}</span></div>
      <p class="text-xs text-gray-400 my-2">${escHtml(run.db_name || 'Database not recorded')} · ${escHtml(run.task_number || 'No task')} · ${escHtml(run.session_id || 'No session')}</p>
      <p class="text-xs text-gray-500 break-all">Run ${escHtml(run.run_id)}</p>
      <p class="text-sm my-3">${links}</p>
      ${run.artifacts.trace ? `<div class="border border-gray-700 rounded p-3 my-3 text-xs">
        <div class="flex items-center gap-2 flex-wrap"><span class="font-medium">Playwright Trace Viewer</span><button id="open-trace-button" type="button" onclick="openSelectedTrace()" class="bg-blue-700 rounded px-3 py-2 ml-auto">Open trace</button><button type="button" onclick="copyTraceViewerCommand()" class="bg-blue-800 rounded px-2 py-1 ml-auto">Copy open command</button></div>
        <input id="trace-viewer-command" type="text" readonly aria-label="Playwright trace viewer command" class="w-full font-mono mt-2" value="${escHtml(traceViewerCommand(run))}" onclick="this.select()">
        <p id="trace-command-status" class="text-gray-400 mt-2" role="status">Open trace launches the selected recording in your browser through your connected VS Code. The command is available as a fallback.</p>
      </div>` : ''}
      <div class="border border-gray-700 rounded p-3 my-3 text-xs">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="run-safe-delete" ${run.safe_to_delete ? 'checked' : ''} onchange="saveRunNote()">
          <span class="font-medium">Safe to delete</span>
          ${run.trace_purged_at ? `<span class="text-gray-400">· trace removed, ${fmtBytes(run.bytes_freed)} freed</span>`
            : run.artifacts.trace ? `<span class="text-gray-500 ml-auto">frees ${fmtBytes(run.trace_bytes || 0)}</span>` : ''}
        </label>
        <input id="run-note" type="text" class="w-full mt-2" placeholder="Note — why is this safe to delete?"
               value="${escHtml(run.note || '')}" onchange="saveRunNote()">
        <p id="run-note-status" class="text-gray-400 mt-1" role="status">Tagging only marks it. Traces are removed from the Flows header, and the run record is kept either way.</p>
      </div>
      ${renderFailureSummary(report)}
      ${report.runtime?.python_trace ? `<p class="text-xs text-gray-400">Python tracing: ${escHtml(report.runtime.python_trace.status)} · ${report.runtime.python_trace.matched_requests} matched requests</p>` : ''}
      ${run.status === 'stale' ? '<p class="text-yellow-300 text-sm">No update for over five minutes. This run may have been interrupted; its last recorded steps are shown below.</p>' : ''}
      ${report.note ? `<p class="text-gray-400 text-sm">${escHtml(report.note)}</p>` : ''}
      ${report.error ? `<pre class="text-red-300 whitespace-pre-wrap">${escHtml(report.error)}</pre>` : ''}
      ${failed.length ? `<p class="text-red-300 font-medium my-2">${failed.length} failed step(s)</p>` : ''}
      <p class="text-xs text-gray-400 my-2">${report.runtime ? `${rpcs.length} RPC requests · ${rpcErrors.length} RPC errors. Requests are grouped by the step active when they started; background traffic can overlap. RPC evidence does not change assertion verdicts.` : 'Runtime evidence was not captured by this runner version.'}</p>
      ${report.runtime?.dropped_requests ? `<p class="text-xs text-yellow-300">${escHtml(report.runtime.dropped_requests)} requests omitted after capture limit.</p>` : ''}
      <ol class="space-y-2 my-3">${steps.map(step => `<li id="step-${escHtml(step.step_id || step.line)}" class="border-l-2 ${step.status === 'failed' ? 'border-red-500' : 'border-gray-600'} pl-3 text-xs"><span class="text-gray-400">Line ${escHtml(step.line)} · ${escHtml(step.status)} · ${runDuration(step.duration_ms)}</span><pre class="whitespace-pre-wrap break-words">${escHtml(step.command)}</pre>${step.error ? `<pre class="whitespace-pre-wrap text-red-300">${escHtml(step.error)}</pre>` : ''}${renderRuntimeRequests(rpcs.filter(rpc => rpc.step_id === step.step_id && step.step_id), openRpcIds)}</li>`).join('')}</ol>
      ${rpcs.some(rpc => !steps.some(step => step.step_id && step.step_id === rpc.step_id)) ? `<div class="text-xs"><p>RPCs outside a recorded step</p>${renderRuntimeRequests(rpcs.filter(rpc => !steps.some(step => step.step_id && step.step_id === rpc.step_id)), openRpcIds)}</div>` : ''}
      ${flow?.content !== undefined ? `<details data-flow-snapshot ${snapshotOpen ? 'open' : ''} class="border border-gray-700 rounded p-3"><summary class="cursor-pointer text-sm">Captured flow · ${escHtml((flow.sha256 || '').slice(0,12))}</summary><p class="text-xs text-gray-500 my-2">${flow.credentials_redacted ? 'Login and cookie commands are redacted. ' : ''}${flow.complete === false ? 'Partial input captured before the run stopped.' : 'Snapshot from this run.'}</p><pre class="text-xs whitespace-pre-wrap break-words">${escHtml(flow.content)}</pre></details>` : '<p class="text-sm text-gray-500">No flow snapshot was captured for this run.</p>'}`;
  } catch (error) { if (request === _detailRequest) detail.textContent = `Could not load run: ${error.message}`; }
}
async function saveRunNote() {
  const id = document.getElementById('flow-run-detail')?.dataset.runId;
  const box = document.getElementById('run-safe-delete');
  const note = document.getElementById('run-note');
  const status = document.getElementById('run-note-status');
  if (!id || !box || !note || !status) return;
  status.textContent = 'Saving…';
  try {
    const response = await fetch('/api/flow-runs/' + encodeURIComponent(id) + '/note', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note: note.value, safe_to_delete: box.checked}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Could not save.');
    status.textContent = box.checked ? 'Tagged safe to delete.' : 'Saved.';
    await refreshTagSummary();
    await loadFlowRuns(false, true);
  } catch (error) { status.textContent = 'Could not save: ' + error.message; }
}

async function refreshTagSummary() {
  const el = document.getElementById('flow-tag-summary');
  const button = document.getElementById('flow-purge-button');
  if (!el) return;
  try {
    const data = await flowJSON('/api/flow-runs/tagged');
    if (!data.pending_count) {
      el.textContent = data.runs.length ? `${data.runs.length} tagged · traces already removed` : '';
      if (button) button.classList.add('hidden');
      return;
    }
    el.textContent = `${data.pending_count} tagged · ${fmtBytes(data.reclaimable_bytes)} reclaimable`;
    if (button) { button.classList.remove('hidden'); button.dataset.bytes = data.reclaimable_bytes; button.dataset.count = data.pending_count; }
  } catch { el.textContent = ''; }
}

async function purgeTaggedTraces() {
  const button = document.getElementById('flow-purge-button');
  const el = document.getElementById('flow-tag-summary');
  if (!button || button.disabled) return;
  const count = button.dataset.count, size = fmtBytes(Number(button.dataset.bytes || 0));
  if (!confirm(`Delete the trace ZIP of ${count} tagged run(s)? This frees ${size} and cannot be undone.\n\nThe run records, logs and results are kept — only the .zip is removed.`)) return;
  button.disabled = true;
  button.textContent = 'Deleting…';
  try {
    const response = await fetch('/api/flow-runs/purge-tagged', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Could not delete.');
    el.textContent = `Removed ${result.removed} trace(s), freed ${fmtBytes(result.bytes_freed)}` +
      (result.skipped.length ? ` · ${result.skipped.length} skipped` : '');
    await loadFlowRuns(false, true);
    if (_selectedRun) await selectRun(_selectedRun);
  } catch (error) { el.textContent = 'Could not delete: ' + error.message; }
  finally { button.disabled = false; button.textContent = 'Delete tagged traces'; await refreshTagSummary(); }
}

async function openSelectedTrace() {
  const button = document.getElementById('open-trace-button');
  const status = document.getElementById('trace-command-status');
  const id = document.getElementById('flow-run-detail')?.dataset.runId;
  if (!button || !status || !id || button.disabled) return;
  button.disabled = true;
  button.textContent = 'Opening…';
  status.textContent = 'Starting Playwright and asking VS Code to open this trace…';
  try {
    const response = await fetch('/api/flow-runs/' + encodeURIComponent(id) + '/open-trace', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Could not open trace.');
    status.textContent = result.message;
  } catch (error) {
    status.textContent = 'Could not open trace: ' + error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Open trace';
  }
}

function traceViewerCommand(run) {
  if (!run.artifacts?.trace) return '';
  // Keep the trace URL reachable by the browser as well as the server.
  const url = new URL('/api/flow-runs/' + encodeURIComponent(run.run_id) + '/artifacts/trace', location.origin);
  return "python3 /home/server/odoo-trace-kit/open-trace.py '" + url.href.replace(/'/g, "%27") + "'";
}
async function copyTraceViewerCommand() {
  const input = document.getElementById('trace-viewer-command');
  const status = document.getElementById('trace-command-status');
  if (!input || !status) return;
  let copied = false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(input.value);
      copied = true;
    }
  } catch { /* Plain HTTP or denied clipboard access: use selected text below. */ }
  if (!copied) {
    input.focus(); input.select(); input.setSelectionRange(0, input.value.length);
    try { copied = document.execCommand('copy'); } catch {}
  }
  status.textContent = copied ? 'Copied — paste into a VS Code terminal on this machine.' : 'Command selected — press Ctrl+C or ⌘C to copy.';
}

function copyFlowContent() { if (_selectedFlow) navigator.clipboard.writeText(_selectedFlow.content); }
function saveFlowToFile() {
  if (!_selectedFlow) return;
  const url = URL.createObjectURL(new Blob([_selectedFlow.content], { type: 'text/plain' }));
  const link = document.createElement('a'); link.href = url; link.download = _selectedFlow.name + '.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function deleteSelectedFlow() {
  if (!_selectedFlow) return;
  const name = _selectedFlow.name;
  if (!await openModal('Delete saved flow', `Delete the saved definition of "${name}"? Its run history will remain available.`)) return;
  try {
    const response = await fetch('/api/flows/' + encodeURIComponent(name), { method: 'DELETE' });
    if (!response.ok) throw new Error(`Delete failed (${response.status})`);
    _selectedFlow = null; document.getElementById('flow-definition').classList.add('hidden');
    await loadFlows();
  } catch (error) { document.getElementById('flow-history-message').textContent = error.message; }
}
setInterval(() => {
  if (!document.hidden && document.getElementById('panel-flows').classList.contains('active')) loadFlows(true);
}, 5000);

// Summary links expose the evidence they jump to, including collapsed RPCs.
document.addEventListener('click', event => {
  const link = event.target.closest?.('#failure-summary a[href^="#rpc-"]');
  if (!link) return;
  const target = document.getElementById(link.getAttribute('href').slice(1));
  if (target?.tagName === 'DETAILS') target.open = true;
});
