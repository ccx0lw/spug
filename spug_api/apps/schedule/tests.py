import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.account.models import User
from apps.schedule.executors import schedule_worker_handler
from apps.schedule.models import History, Task
from apps.schedule.views import Schedule


class ScheduleHostScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='schedule-admin',
            nickname='任务管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )

    def test_out_of_scope_target_is_rejected_before_save(self):
        request = self.factory.post(
            '/api/schedule/',
            data=json.dumps({
                'type': 'security-test',
                'name': '越权目标测试',
                'interpreter': 'sh',
                'command': 'id',
                'rst_notify': {'mode': '0'},
                'targets': [999],
                'trigger': 'interval',
                'trigger_args': '60',
            }),
            content_type='application/json',
        )
        request.user = SimpleNamespace(
            is_supper=False,
            group_perms=[],
            has_perms=lambda codes: True,
        )

        response = Schedule.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertEqual('无权访问目标主机', result['error'])
        self.assertEqual(0, Task.objects.count())

    @patch('apps.schedule.executors.dispatch_job')
    @patch('apps.schedule.executors.task_targets_allowed', return_value=False)
    def test_worker_rechecks_scope_before_ssh(
            self, targets_allowed, dispatch_job):
        task = Task.objects.create(
            name='执行期复核',
            type='security-test',
            interpreter='sh',
            command='id',
            targets='[999]',
            trigger='interval',
            trigger_args='60',
            is_active=True,
            rst_notify='{"mode": "0"}',
            created_by=self.creator,
        )
        history = History.objects.create(
            task_id=task.id,
            status=0,
            run_time='2026-07-23 10:00:00',
            output='{"999": null}',
        )

        schedule_worker_handler(json.dumps([history.id, 999]))

        dispatch_job.assert_not_called()
        history.refresh_from_db()
        self.assertEqual(2, history.status)
        self.assertEqual(
            'target host permission denied',
            json.loads(history.output)['999'][2],
        )
