// Deterministic evidence summary: timing correlation is never labeled a root cause.
(function(root) {
  function summarizeFailure(report) {
    const steps = Array.isArray(report.steps) ? report.steps : [];
    const rpcs = Array.isArray(report.runtime?.requests) ? report.runtime.requests : [];
    const failed = steps.filter(s => s.status === 'failed');
    const primary = failed.find(s => /^expect\s/.test(s.command || '')) || failed[0] || null;
    const errors = rpcs.filter(r => ['rpc_error','network_error','http_error'].includes(r.status));
    const linked = primary?.step_id ? errors.filter(r => r.step_id === primary.step_id) : [];
    const primaryIndex = steps.indexOf(primary);
    const previous = primaryIndex >= 0 ? steps.slice(Math.max(0,primaryIndex-3),primaryIndex).map(s=>s.step_id).filter(Boolean) : [];
    const nearby = errors.filter(r=>previous.includes(r.step_id));
    const headline = primary ? `Failed ${/^expect\s/.test(primary.command || '') ? 'assertion' : 'step'} at line ${primary.line}`
      : report.error || report.cleanup_error ? 'Run could not complete'
      : errors.length ? `${errors.length} RPC error${errors.length===1?'':'s'} observed`
      : report.status === 'passed' ? 'No recorded failures'
      : report.status === 'running' ? 'Run is still in progress' : 'No failure details recorded';
    return { headline, primary, failed_count:failed.length, linked, nearby,
      other:errors.filter(r=>!linked.includes(r)&&!nearby.includes(r)),
      run_error:report.error || report.cleanup_error || null,
      note: nearby.length ? 'Earlier RPC errors may be related; causation is not established.'
        : linked.length ? 'These requests started during the failed step; background traffic can overlap.'
        : errors.length && !primary ? 'RPC errors do not change the recorded assertion verdict; some flows intentionally exercise errors.'
        : primary ? 'No correlated RPC error explains this failure.' : null };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { summarizeFailure };
  else root.summarizeFailure = summarizeFailure;
})(typeof globalThis === 'undefined' ? this : globalThis);
