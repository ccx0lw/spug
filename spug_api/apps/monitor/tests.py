import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.monitor.executors import ping_check
from apps.monitor.views import run_test


class PingTargetSecurityTests(SimpleTestCase):
    @patch('apps.monitor.executors.subprocess.run')
    def test_valid_hostname_is_passed_as_a_single_argument(self, run):
        run.return_value.returncode = 0

        result = ping_check('api.internal.example')

        self.assertEqual((True, 'Ping检测正常'), result)
        args, kwargs = run.call_args
        self.assertEqual('api.internal.example', args[0][-1])
        self.assertIs(False, kwargs['shell'])

    @patch('apps.monitor.executors.subprocess.run')
    def test_shell_syntax_is_rejected_before_process_start(self, run):
        result = ping_check('127.0.0.1; touch /tmp/spug-ping-probe')

        self.assertEqual((False, 'Ping地址格式错误'), result)
        run.assert_not_called()


class MonitorHostScopeTests(SimpleTestCase):
    @patch('apps.monitor.views.dispatch')
    def test_out_of_scope_command_monitor_is_rejected_before_ssh(
            self, dispatch):
        request = RequestFactory().post(
            '/api/monitor/test/',
            data=json.dumps({
                'type': '4',
                'targets': [999],
                'extra': 'id',
            }),
            content_type='application/json',
        )
        request.user = SimpleNamespace(
            is_supper=False,
            group_perms=[],
            has_perms=lambda codes: True,
        )

        response = run_test(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertEqual('无权访问目标主机', result['error'])
        dispatch.assert_not_called()
