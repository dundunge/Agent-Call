from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_team_v1.server import ApiHandler
from agent_team_v1.service import ControlPlane
from agent_team_v1.store import SQLiteStore


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='aiteam-http-')
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), ApiHandler)
        self.httpd.control_plane = ControlPlane(SQLiteStore(Path(self.temp.name) / 'state.sqlite3'))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def post(self, path, body):
        request = Request(self.origin + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_every_demo_asset_has_correct_mime(self):
        for path, expected in [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/simulation.js', 'text/javascript'), ('/styles.css', 'text/css'), ('/vendor/dsh-base.css', 'text/css'), ('/vendor/dsh-design-platform.css', 'text/css'), ('/vendor/DSH-LICENSE.txt', 'text/plain')]:
            with self.subTest(path=path), urlopen(self.origin + path, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), expected)
                self.assertTrue(response.read())

    def test_vendor_route_cannot_escape_static_root(self):
        for path in ['/vendor/../../models.py', '/vendor/../../../pyproject.toml', '/vendor/']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                urlopen(self.origin + path, timeout=2)
            self.assertEqual(caught.exception.code, 404)

    def test_api_records_events_separately_from_acceptance(self):
        task = self.post('/tasks', {'taskId': 'http-demo', 'provider': 'mock', 'adapter': 'agent-call/mock', 'workspace': 'demo://workspace', 'objective': 'fixture', 'prompt': 'read fixture', 'acceptanceCriteria': ['observed', 'evidence']})
        self.assertEqual(task['state'], 'planned')
        observed = self.post('/tasks/http-demo/dispatch', {})
        self.assertEqual(observed['caller_acceptance'], 'not_run')
        accepted = self.post('/tasks/http-demo/accept', {'result': 'passed', 'evidence': ['mock output checked']})
        self.assertEqual(accepted['state'], 'accepted')
        with urlopen(self.origin + '/tasks/http-demo/events', timeout=2) as response:
            events = json.load(response)['events']
        self.assertEqual([item['eventType'] for item in events], ['task_planned', 'dispatch_result', 'caller_acceptance'])
