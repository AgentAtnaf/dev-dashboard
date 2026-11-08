"""Index local trace artifacts without inferring success or using current flow text."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone


def legacy_name(path):
    label = path.name.removesuffix('.result.json').removesuffix('.zip')
    task = re.match(r'^(T\d{2}-\d+)\s+', label)
    if task:
        label = label[task.end():]
    label = re.sub(r'\s+\d{4}-\d{2}-\d{2}.*$', '', label)
    return label, task.group(1) if task else ''


class RunHistory:
    def __init__(self, connect, roots):
        self.connect = connect
        self.roots = tuple(Path(root).resolve() for root in roots)
        self.lock = threading.Lock()
        self.last_scan = 0
        self.fingerprints = {}

    @staticmethod
    def init_schema(conn):
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS flow_runs (
                run_id TEXT PRIMARY KEY, flow_name TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT, duration_ms REAL,
                task_number TEXT, session_id TEXT, db_name TEXT,
                flow_hash TEXT, report_json TEXT NOT NULL,
                result_path TEXT, trace_path TEXT, log_path TEXT,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS flow_runs_name_date ON flow_runs(flow_name, started_at DESC);
            -- Kept out of flow_runs on purpose: that table is a derived index and every
            -- rescan rewrites each row positionally with INSERT OR REPLACE, which would
            -- silently discard anything a human typed. These rows are the source of truth.
            CREATE TABLE IF NOT EXISTS flow_run_notes (
                run_id TEXT PRIMARY KEY,
                note TEXT NOT NULL DEFAULT '',
                safe_to_delete INTEGER NOT NULL DEFAULT 0,
                trace_purged_at REAL,
                bytes_freed INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS flow_run_notes_safe ON flow_run_notes(safe_to_delete);
        ''')

    def allowed(self, path):
        resolved = Path(path).resolve()
        return any(resolved.is_relative_to(root) for root in self.roots)

    def refresh(self, force=False):
        with self.lock:
            if not force and time.monotonic() - self.last_scan < 2:
                return
            conn = self.connect()
            try:
                for root in self.roots:
                    if not root.is_dir():
                        continue
                    for path in root.rglob('*.result.json'):
                        self._index_result(conn, path)
                    # Old ZIPs have no trustworthy verdict or historical flow snapshot.
                    for path in root.rglob('*.zip'):
                        if not path.with_name(path.stem + '.result.json').exists():
                            self._index_legacy(conn, path)
                conn.commit()
                self.last_scan = time.monotonic()
            finally:
                conn.close()

    def _changed(self, path):
        if not self.allowed(path) or not path.is_file():
            return None
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        if self.fingerprints.get(str(path)) == key:
            return None
        return stat, key

    def _index_result(self, conn, path):
        try:
            changed = self._changed(path)
            if not changed:
                return
            stat, key = changed
            if stat.st_size > 32 * 1024 * 1024:
                return
            report = json.loads(path.read_text())
            if not isinstance(report, dict) or not isinstance(report.get('status'), str) or not isinstance(report.get('steps', []), list):
                return
            inferred_name, inferred_task = legacy_name(path)
            run_id = report.get('run_id') or 'report-' + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
            if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run_id):
                return
            context = report.get('context') or {}
            flow = report.get('flow') or {}
            verified = context.get('verified_session') or {}
            if not all(isinstance(value, dict) for value in (context, flow, verified)):
                return
            if any(not isinstance(step, dict) for step in report.get('steps', [])):
                return
            fields = [report.get('flow_name'), report.get('started_at'), report.get('finished_at'),
                      context.get('task'), context.get('session_id'), context.get('requested_db'),
                      verified.get('db'), flow.get('sha256'), flow.get('content')]
            if any(value is not None and not isinstance(value, str) for value in fields):
                return
            status = report.get('status', 'unknown')
            if status not in ('passed', 'failed', 'running', 'unknown'):
                status = 'unknown'
            started = report.get('started_at') or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            duration = None
            if report.get('finished_at'):
                try:
                    duration = max(0, (datetime.fromisoformat(report['finished_at'].replace('Z', '+00:00')) - datetime.fromisoformat(started.replace('Z', '+00:00'))).total_seconds() * 1000)
                except (ValueError, TypeError):
                    pass
            stem = path.name.removesuffix('.result.json')
            trace = path.with_name(stem + '.zip')
            log = path.with_name(stem + '.log')
            # If a result appears later, it supersedes the unknown legacy entry.
            conn.execute("DELETE FROM flow_runs WHERE run_id LIKE 'legacy-%' AND trace_path=?", (str(trace.resolve()),))
            conn.execute('''INSERT OR REPLACE INTO flow_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                run_id, report.get('flow_name') or inferred_name, status, started, duration,
                context.get('task') or inferred_task, context.get('session_id') or '',
                verified.get('db') or context.get('requested_db') or '', flow.get('sha256') or '',
                json.dumps(report), str(path.resolve()), str(trace.resolve()), str(log.resolve()), stat.st_mtime,
            ))
            self.fingerprints[str(path)] = key
        except (OSError, ValueError, TypeError, AttributeError):
            # An interrupted write or malformed report must not hide other runs.
            return

    def _index_legacy(self, conn, path):
        try:
            changed = self._changed(path)
            if not changed:
                return
            stat, key = changed
            name, task = legacy_name(path)
            report = {'status': 'unknown', 'steps': [], 'legacy': True,
                      'note': 'Legacy trace: no result report or captured flow is available.'}
            conn.execute('''INSERT OR IGNORE INTO flow_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                'legacy-' + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24],
                name, 'unknown', datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                None, task, '', '', '', json.dumps(report), '', str(path.resolve()),
                str(path.with_suffix('.log').resolve()), stat.st_mtime,
            ))
            self.fingerprints[str(path)] = key
        except OSError:
            return

    def runs(self, flow_name=None, status=None):
        self.refresh()
        conn = self.connect()
        try:
            sql = ('SELECT r.run_id,r.flow_name,r.status,r.started_at,r.duration_ms,r.task_number,'
                   'r.session_id,r.db_name,r.flow_hash,r.updated_at,'
                   "COALESCE(n.note,'') AS note, COALESCE(n.safe_to_delete,0) AS safe_to_delete,"
                   'n.trace_purged_at FROM flow_runs r LEFT JOIN flow_run_notes n ON n.run_id=r.run_id')
            params = ()
            if flow_name is not None:
                sql += ' WHERE r.flow_name=?'
                params = (flow_name,)
            rows = [dict(row) for row in conn.execute(sql + ' ORDER BY r.started_at DESC, r.run_id DESC', params)]
        finally:
            conn.close()
        for row in rows:
            if row['status'] == 'running' and time.time() - row['updated_at'] > 300:
                row['status'] = 'stale'
        return [row for row in rows if status is None or row['status'] == status]

    def get(self, run_id):
        self.refresh()
        conn = self.connect()
        try:
            row = conn.execute('SELECT * FROM flow_runs WHERE run_id=?', (run_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        data = dict(row)
        data['report'] = json.loads(data.pop('report_json'))
        if data['status'] == 'running' and time.time() - data['updated_at'] > 300:
            data['status'] = 'stale'
        data['artifacts'] = {}
        for kind, column in [('trace', 'trace_path'), ('log', 'log_path')]:
            p = data[column]
            if p and self.allowed(p) and Path(p).is_file():
                data['artifacts'][kind] = f'/api/flow-runs/{run_id}/artifacts/{kind}'
        if (data['report'].get('flow') or {}).get('content') is not None:
            data['artifacts']['flow'] = f'/api/flow-runs/{run_id}/artifacts/flow'
        data['artifacts']['result'] = f'/api/flow-runs/{run_id}/artifacts/result'
        data.update(self.note_for(run_id))
        data['trace_bytes'] = self._trace_bytes(data.get('trace_path'))
        return data

    def note_for(self, run_id):
        conn = self.connect()
        try:
            row = conn.execute('SELECT note,safe_to_delete,trace_purged_at,bytes_freed '
                               'FROM flow_run_notes WHERE run_id=?', (run_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return {'note': '', 'safe_to_delete': 0, 'trace_purged_at': None, 'bytes_freed': 0}
        return dict(row)

    def set_note(self, run_id, note=None, safe_to_delete=None):
        # Upsert without clobbering the field the caller did not send, so ticking the
        # box from the list view cannot wipe a note typed in the detail view.
        conn = self.connect()
        try:
            with conn:
                conn.execute('INSERT OR IGNORE INTO flow_run_notes(run_id,updated_at) VALUES(?,?)',
                             (run_id, time.time()))
                if note is not None:
                    conn.execute('UPDATE flow_run_notes SET note=?,updated_at=? WHERE run_id=?',
                                 (note[:2000], time.time(), run_id))
                if safe_to_delete is not None:
                    conn.execute('UPDATE flow_run_notes SET safe_to_delete=?,updated_at=? WHERE run_id=?',
                                 (1 if safe_to_delete else 0, time.time(), run_id))
        finally:
            conn.close()
        return self.note_for(run_id)

    def tagged(self):
        """Runs marked safe to delete, with the trace bytes each one would reclaim."""
        self.refresh()
        conn = self.connect()
        try:
            rows = conn.execute(
                'SELECT r.run_id,r.flow_name,r.status,r.started_at,r.task_number,r.db_name,'
                'r.trace_path,n.note,n.trace_purged_at FROM flow_runs r '
                'JOIN flow_run_notes n ON n.run_id=r.run_id WHERE n.safe_to_delete=1 '
                'ORDER BY r.started_at DESC').fetchall()
        finally:
            conn.close()
        out = []
        for row in rows:
            item = dict(row)
            item['bytes'] = self._trace_bytes(item.pop('trace_path'))
            item['safe_to_delete'] = 1  # every row here is tagged, by definition of the query
            out.append(item)
        return out

    def _trace_bytes(self, path):
        # Only ever report a file this history owns, and only a trace zip.
        if not path or not self.allowed(path) or not path.endswith('.zip'):
            return 0
        try:
            return Path(path).stat().st_size
        except OSError:
            return 0

    def purge_trace(self, run_id):
        """Delete only the .zip for a tagged run. The row, report and log stay."""
        conn = self.connect()
        try:
            row = conn.execute(
                'SELECT r.trace_path, COALESCE(n.safe_to_delete,0) AS safe FROM flow_runs r '
                'LEFT JOIN flow_run_notes n ON n.run_id=r.run_id WHERE r.run_id=?', (run_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return {'ok': False, 'reason': 'unknown run'}
        if not row['safe']:
            return {'ok': False, 'reason': 'not tagged safe to delete'}
        path = row['trace_path']
        size = self._trace_bytes(path)
        if not size:
            # Nothing to remove, or the path is outside our roots / not a zip.
            return {'ok': False, 'reason': 'no trace file to remove'}
        try:
            Path(path).unlink()
        except OSError as error:
            return {'ok': False, 'reason': str(error)}
        conn = self.connect()
        try:
            with conn:
                conn.execute('UPDATE flow_run_notes SET trace_purged_at=?,bytes_freed=?,updated_at=? '
                             'WHERE run_id=?', (time.time(), size, time.time(), run_id))
        finally:
            conn.close()
        self.fingerprints.pop(path, None)
        return {'ok': True, 'bytes': size}
