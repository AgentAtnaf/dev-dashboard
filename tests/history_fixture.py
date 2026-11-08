"""Temporary dashboard for browser tests; never uses the live database."""
import json
from pathlib import Path
import socket
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from run_history import RunHistory
import uvicorn
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    server.DB_PATH = str(root/'test.db')
    server.history = RunHistory(server.get_db, [root])
    server.init_db()
    server.save_flow(server.FlowSaveRequest(name='invoice-confirm', content='current definition\ndone\n'))
    server.save_flow(server.FlowSaveRequest(name='long-definition-no-runs', content=('expect visible body\n' * 160)))
    for idx, status in enumerate(['passed', 'failed']):
        report = dict(run_id=f'fixture-{status}', flow_name='invoice-confirm', status=status,
            started_at=f'2026-09-09T01:00:0{idx}Z', finished_at=f'2026-09-09T01:00:0{idx+2}Z',
            context={'requested_db':'fixture_db','task':'T26-12345','session_id':'fixture-session'},
            flow={'content':f'# historical {status}\nlogin [redacted]\ndone\n', 'sha256':'a'*64, 'complete':True,'credentials_redacted':True},
            steps=[{'step_id':f'fixture-{status}-step-1','line':3,'command':'expect value #amount 10','status':status,'duration_ms':300,
                    'error':'Expected 10; found 20' if status=='failed' else None}])
        report['runtime'] = {'requests':[{'request_id':f'fixture-{status}-rpc-1',
            'step_id':f'fixture-{status}-step-1','line':3,'model':'sale.order','method':'create_invoices',
            'endpoint':'/web/dataset/call_button','status':'rpc_error' if status=='failed' else 'ok',
            'http_status':200,'duration_ms':140,'rpc_id':17,'params':{'args':[[7]]},
            'error':{'message':'Missing account','traceback':'Traceback: custom/invoice.py:42 <script>unsafe</script>'} if status=='failed' else None}]}
        report['runtime']['requests'][0]['python_trace'] = {'status':'captured','duration_ms':12,'calls':[{'id':1,'parent_id':None,'model':'sale.order','module':'odoo.addons.custom','function':'SaleOrder.create_invoices','file':'custom/invoice.py','line':42,'duration_ms':10,'complete':True}]}
        (root/f'{status}.result.json').write_text(json.dumps(report))
        (root/f'{status}.zip').write_bytes(b'fixture zip')
        (root/f'{status}.log').write_text('fixture log')
    (root/'old-flow 2026-08-01.zip').write_bytes(b'legacy')
    sock=socket.socket(); sock.bind(('127.0.0.1',0))
    Path(sys.argv[1]).write_text(str(sock.getsockname()[1]))
    uvicorn.Server(uvicorn.Config(server.app, log_level='error')).run(sockets=[sock])
