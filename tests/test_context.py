"""Context propagation against a temporary SQLite DB; no live dashboard writes."""
import importlib.util
import os
import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

sys.path.insert(0, str(ROOT))
cli = load('dashboard_cli_test', 'cli.py')
server = load('dashboard_server_test', 'server.py')

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        server.DB_PATH = str(Path(self.temp.name) / 'test.db')
        # Simulate the schema from before this change, with a saved flow.
        with sqlite3.connect(server.DB_PATH) as conn:
            conn.execute('CREATE TABLE flows (name TEXT PRIMARY KEY, content TEXT NOT NULL, session_id TEXT, session_title TEXT, task_number TEXT, created_at TEXT, updated_at TEXT)')
            conn.execute("INSERT INTO flows VALUES ('old', 'done', '', '', '', '', '')")
        server.history.roots = ()
        server.init_db()
        server.init_db()  # migration must be idempotent

    def test_migration_and_roundtrip(self):
        self.assertEqual(server.get_flow('old')['db_name'], '')
        server.save_flow(server.FlowSaveRequest(name='new', content='done', db_name='fixture', session_id='chosen', task_number='T26-12345'))
        flow = server.get_flow('new')
        self.assertEqual((flow['db_name'], flow['session_id'], flow['task_number']), ('fixture','chosen','T26-12345'))
        self.assertIn('db_name', server.list_flows()[0])

    def test_exact_session_and_no_guessing(self):
        server.record_task(server.RecordTaskRequest(task_number='T26-12345', session_id='chosen'))
        server.record_task(server.RecordTaskRequest(task_number='T26-99999', session_id='other'))
        self.assertEqual(server.get_session_context('chosen')['task_number'], 'T26-12345')
        self.assertEqual(server.get_session_context('unknown')['task_number'], '')
        self.assertEqual(server.record_task(server.RecordTaskRequest(task_number='T26-12345')).status_code, 422)
        self.assertIsNone(cli._get_session_id())
        with self.assertRaises(SystemExit) as error:
            cli.cmd_task(['T26-12345'])
        self.assertEqual(error.exception.code, 2)

    def test_flow_cli_explicit_flags_override_environment(self):
        flow = Path(self.temp.name) / 'flow.txt'
        flow.write_text('done\n')
        with patch.dict(os.environ, {'ODOO_TASK':'T26-99999', 'ODOO_SESSION_ID':'other', 'ODOO_DB':'other'}):
            with patch.object(cli, '_post', return_value={'ok':True}) as post:
                cli.cmd_flow(['save','example',str(flow),'--task','T26-12345','--session-id','chosen','--db','fixture'])
                payload = post.call_args.args[1]
                self.assertEqual((payload['task_number'],payload['session_id'],payload['db_name']),('T26-12345','chosen','fixture'))

    def test_environment_and_task_board_visual_context(self):
        with patch.dict(os.environ, {'ODOO_TASK':'T26-12345','ODOO_SESSION_ID':'chosen','ODOO_DB':'fixture'}):
            with patch.object(cli, '_post', return_value={'ok':True}) as post:
                cli.cmd_task([])
                self.assertEqual(post.call_args.args[1], {'task_number':'T26-12345','session_id':'chosen'})
                cli.cmd_board(['Title','markdown','Content'])
                self.assertEqual(post.call_args.args[1]['task_number'], 'T26-12345')
                self.assertEqual(post.call_args.args[1]['session_id'], 'chosen')
                # was cmd_flowviz; Flow Visuals was removed 2026-11-08. cmd_flow save
                # posts db_name the same way, so the context-propagation check stands.
                flow = Path(self.temp.name) / 'flow.txt'; flow.write_text('login admin secret')
                cli.cmd_flow(['save','Title',str(flow)])
                self.assertEqual(post.call_args.args[1]['db_name'],'fixture')

    def test_invalid_flags_fail(self):
        for args in (['--session-id'], ['--typo','value'], ['--task','invalid']):
            with self.assertRaises(SystemExit) as error:
                cli._context_args(args)
            self.assertEqual(error.exception.code,2)

    def test_unreachable_dashboard_fails(self):
        with patch.object(cli.urllib.request, 'urlopen', side_effect=cli.urllib.error.URLError('fixture offline')):
            with self.assertRaises(SystemExit) as error:
                cli._post('/api/flows', {})
            self.assertEqual(error.exception.code,1)

if __name__ == '__main__':
    unittest.main()
