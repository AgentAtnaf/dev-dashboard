from unittest.mock import patch
import subprocess
from test_run_history import HistoryTests

import unittest

class TraceLaunchTests(unittest.TestCase):
    setUp = HistoryTests.setUp
    report = HistoryTests.report
    # Do not repeat the parent suite; share only its fixture helpers.
    def test_launch_validation_and_execution(self):
        import server
        with patch.object(server.subprocess, 'run') as launch:
            self.assertEqual(self.client.post('/api/flow-runs/missing/open-trace').status_code, 404)
            self.report()
            self.assertEqual(self.client.post('/api/flow-runs/run-one/open-trace').status_code, 404)
            launch.assert_not_called()
            (self.root/'run-one.zip').write_bytes(b'PK\x03\x04fixture')
            launch.return_value = subprocess.CompletedProcess([], 0, 'opened', '')
            response = self.client.post('/api/flow-runs/run-one/open-trace')
            self.assertEqual(response.status_code, 200)
            args, kwargs = launch.call_args
            self.assertEqual(args[0][1], '/home/server/odoo-trace-kit/open-trace.py')
            self.assertTrue(args[0][2].endswith('/api/flow-runs/run-one/artifacts/trace'))
            self.assertNotIn('shell', kwargs)
            launch.return_value = subprocess.CompletedProcess([], 1, '', 'VS Code disconnected')
            self.assertEqual(self.client.post('/api/flow-runs/run-one/open-trace').status_code, 503)
            launch.side_effect = subprocess.TimeoutExpired([], 30)
            self.assertEqual(self.client.post('/api/flow-runs/run-one/open-trace').status_code, 504)
            launch.reset_mock();launch.side_effect=None
            (self.root/'run-one.zip').unlink()
            outside = self.root.parent/'outside.zip';outside.write_bytes(b'PK\x03\x04')
            (self.root/'run-one.zip').symlink_to(outside)
            self.assertEqual(self.client.post('/api/flow-runs/run-one/open-trace').status_code, 404)
            launch.assert_not_called()
