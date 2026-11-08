"""Exercise history through HTTP against temporary artifacts and SQLite."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from run_history import RunHistory

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'artifacts'
        self.root.mkdir()
        server.DB_PATH = str(Path(self.tmp.name) / 'test.db')
        server.history = RunHistory(server.get_db, [self.root])
        server.init_db()
        server.init_db()
        self.client = TestClient(server.app)

    def report(self, id='run-one', status='passed', content='done\n'):
        report = dict(run_id=id, flow_name='example', status=status,
                      started_at='2026-09-09T01:00:00Z',
                      finished_at='2026-09-09T01:00:02Z' if status != 'running' else None,
                      context={'task': 'T26-12345', 'session_id': 'chosen', 'requested_db': 'fixture'},
                      flow={'content': content, 'sha256': 'abc', 'complete': True},
                      steps=[{'line': 1, 'command': 'done', 'status': status, 'duration_ms': 20}])
        p = self.root / (id + '.result.json')
        p.write_text(json.dumps(report))
        server.history.refresh(force=True)
        return p

    def test_history_snapshot_and_definition_independence(self):
        self.report()
        self.report('run-two', 'failed', 'clickbtn Missing\n')
        server.save_flow(server.FlowSaveRequest(name='example', content='new definition'))
        listing = self.client.get('/api/flows').json()
        self.assertEqual(listing[0]['run_count'], 2)
        detail = self.client.get('/api/flow-runs/run-one').json()
        self.assertEqual(detail['duration_ms'], 2000)
        self.assertEqual(detail['report']['flow']['content'], 'done\n')
        self.assertEqual(detail['session_id'], 'chosen')
        self.assertNotIn('result_path', detail)
        self.assertEqual(self.client.delete('/api/flows/example').status_code, 200)
        self.assertFalse(self.client.get('/api/flows').json()[0]['saved'])
        self.assertEqual(self.client.get('/api/flow-runs').json()['total'], 2)
        self.assertEqual(self.client.get('/api/flow-runs?status=failed&flow_name=example').json()['total'], 1)
        self.assertEqual(len(self.client.get('/api/flow-runs?limit=1&offset=1').json()['runs']), 1)
        self.assertEqual(self.client.get('/api/flow-runs?status=bogus').status_code, 400)

    def test_live_update_stale_and_final_verdict(self):
        p = self.report(status='running')
        os.utime(p, (time.time()-360, time.time()-360))
        server.history.refresh(force=True)
        self.assertEqual(self.client.get('/api/flow-runs/run-one').json()['status'], 'stale')
        self.assertEqual(self.client.get('/api/flow-runs?status=stale').json()['total'], 1)
        self.report(status='passed')
        self.assertEqual(self.client.get('/api/flow-runs/run-one').json()['status'], 'passed')
        self.assertEqual(self.client.get('/api/flow-runs').json()['total'], 1)

    def test_legacy_and_malformed_reports(self):
        (self.root/'T26-12345 old-flow 2026-08-01.zip').write_bytes(b'legacy')
        for n, value in enumerate(['broken', '[]', '{"context": []}', '{"flow_name": []}', '{"flow": {"content": []}}', '{"steps": [null]}']):
            (self.root/f'bad{n}.result.json').write_text(value)
        server.history.refresh(force=True)
        runs = self.client.get('/api/flow-runs').json()['runs']
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]['flow_name'], runs[0]['status']), ('old-flow', 'unknown'))
        detail = self.client.get('/api/flow-runs/'+runs[0]['run_id']).json()
        self.assertNotIn('flow', detail['artifacts'])
        self.assertIn('trace', detail['artifacts'])

    def test_artifacts_and_path_boundary(self):
        p = self.report()
        (self.root/'run-one.zip').write_bytes(b'zip bytes')
        (self.root/'run-one.log').write_text('log text')
        base = '/api/flow-runs/run-one/artifacts/'
        self.assertEqual(self.client.get(base+'trace').content, b'zip bytes')
        self.assertEqual(self.client.get(base+'log').text, 'log text')
        self.assertEqual(self.client.get(base+'flow').text, 'done\n')
        outside = Path(self.tmp.name)/'outside.txt'; outside.write_text('private')
        (self.root/'run-one.log').unlink()
        (self.root/'run-one.log').symlink_to(outside)
        self.assertEqual(self.client.get(base+'log').status_code, 404)
        self.assertEqual(self.client.get(base+'other').status_code, 404)
        p.unlink()
        self.assertEqual(self.client.get(base+'result').json()['run_id'], 'run-one')
        self.assertEqual(self.client.get(base+'flow').text, 'done\n')

if __name__ == '__main__':
    unittest.main()
