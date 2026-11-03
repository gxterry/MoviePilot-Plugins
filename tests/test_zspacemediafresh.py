"""Run with: python -m unittest discover -s tests -v.

Load the plugin's actual methods without MoviePilot's application bootstrap.
The HTTP, history and notification boundaries are replaced with test doubles.
"""
import ast
import unittest
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class RefreshTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'plugins.v2/zspacemediafresh/__init__.py'
        tree = ast.parse(source.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        cls.bases = []
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name in ('refresh', 'remote_sync', '__refresh_zspmedia')]
        for method in cls.body:
            method.decorator_list = []
        self.http = Mock()
        self.history = Mock()
        self.clock = Mock(time=Mock(return_value=0), monotonic=Mock(return_value=0),
                          strftime=Mock(return_value='test time'))
        namespace = dict(datetime=datetime, timedelta=timedelta, SimpleCookie=SimpleCookie,
                         time=self.clock, RequestUtils=self.http, TransferHistoryOper=self.history,
                         logger=Mock(), NotificationType=SimpleNamespace(Plugin='plugin'), Event=object)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), 'exec'), namespace)
        self.plugin = namespace['ZspaceMediaFresh']()
        p = self.plugin
        p._zsphost = 'http://example.invalid'
        p._zspcookie = 'zenithtoken=test-token; device_id=test-device'
        p._flushall = False
        p._notify = True
        p._notifyaggregation = False
        p._waittime = 1
        p._startswith = '/media/a/, /media/b/'
        p._unit = 'minute'
        p._timescope = 5
        p._moivelib = '电影'
        p._tvlib = ' 电视剧，电视剧 '
        p.generate_string = lambda: 'test'
        p.post_message = Mock()
        self.run_scan = p._ZspaceMediaFresh__refresh_zspmedia

    def responses(self, *responses):
        self.http.return_value.post_res.side_effect = [
            None if r is None else SimpleNamespace(json=lambda value=r: value) for r in responses]

    def scan_responses(self, *statuses):
        self.responses({'code': '200', 'data': [{'name': '电视剧', 'id': 'tv'}]},
                       {'code': '200', 'data': {'task_id': 'task'}},
                       *[{'code': '200', 'data': {'task_status': s}} for s in statuses])

    def test_tv_only_and_second_path(self):
        self.history.return_value.list_by_date.return_value = [
            SimpleNamespace(status=1, dest='/media/b/show.mkv', type='电视剧'),
            SimpleNamespace(status=0, dest='/media/a/movie.mkv', type='电影'),
            SimpleNamespace(status=1, dest='/other/movie.mkv', type='电影')]
        scan = Mock(return_value=True)
        self.plugin._ZspaceMediaFresh__refresh_zspmedia = scan
        self.assertTrue(self.plugin.refresh())
        scan.assert_called_once_with(['电视剧'])

    def test_no_history_does_not_scan(self):
        self.history.return_value.list_by_date.return_value = []
        self.plugin.refresh()
        self.http.assert_not_called()

    def test_pending_and_running_wait_for_success(self):
        self.scan_responses(1, 4, 2)
        self.assertTrue(self.run_scan(['电视剧']))
        self.assertEqual(self.clock.sleep.call_count, 2)
        self.plugin.post_message.assert_called_once()
        args = self.http.return_value.post_res.call_args_list[1].args
        self.assertEqual(args[1]['token'], 'test-token')

    def test_legacy_token(self):
        self.plugin._zspcookie = 'token=legacy; device_id=test-device'
        self.scan_responses(2)
        self.assertTrue(self.run_scan(['电视剧']))
        self.assertEqual(self.http.return_value.post_res.call_args_list[1].args[1]['token'], 'legacy')

    def test_failed_or_unknown_status_never_notifies_success(self):
        for status in (3, 99, None):
            with self.subTest(status=status):
                self.scan_responses(status)
                self.assertFalse(self.run_scan(['电视剧']))
        self.plugin.post_message.assert_not_called()

    def test_missing_cookie_does_not_request(self):
        self.plugin._zspcookie = 'device_id=test-device'
        self.assertFalse(self.run_scan(['电视剧']))
        self.http.assert_not_called()

    def test_auth_error_and_network_failure(self):
        for response in (None, {'code': 'N001208', 'data': None}):
            self.responses(response)
            self.assertFalse(self.run_scan(['电视剧']))
        self.plugin.post_message.assert_not_called()

    def test_timeout(self):
        self.scan_responses(4)
        self.clock.monotonic.side_effect = [0, 1801]
        self.assertFalse(self.run_scan(['电视剧']))
        self.plugin.post_message.assert_not_called()

    def test_missing_category(self):
        self.responses({'code': '200', 'data': []})
        self.assertFalse(self.run_scan(['电视剧']))
        self.assertEqual(self.http.return_value.post_res.call_count, 1)

    def test_remote_failure_does_not_report_completed(self):
        self.plugin.refresh = Mock(return_value=False)
        self.plugin.remote_sync(SimpleNamespace(event_data={'action': 'zsp_media_refresh'}))
        self.assertNotIn('完成', self.plugin.post_message.call_args.kwargs['title'])


if __name__ == '__main__':
    unittest.main()
