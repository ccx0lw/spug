import json
import tempfile
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from apps.account.mfa import issue_sensitive_ticket
from apps.account.models import User
from apps.exec.models import ExecHistory, Transfer
from apps.exec.transfer import TransferView
from apps.exec.views import TaskView
from apps.host.models import Host
from apps.setting.utils import AppSetting


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'exec-mfa-tests',
    }
}


@override_settings(CACHES=TEST_CACHES)
class TaskMFAEnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username='executor',
            nickname='执行用户',
            password_hash='-',
            access_token='',
            token_expired=0,
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.host = Host.objects.create(
            name='测试主机',
            hostname='127.0.0.1',
            port=22,
            username='root',
            pkey='test-private-key',
            created_by=self.user,
        )

    def execute(self, ticket):
        request = self.factory.post(
            '/exec/do/',
            data=json.dumps({
                'host_ids': [self.host.id],
                'command': 'id',
                'interpreter': 'sh',
                'mfa_ticket': ticket,
            }),
            content_type='application/json',
        )
        request.user = self.user
        with patch('apps.exec.views.get_redis_connection'):
            response = TaskView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def transfer(self, ticket):
        request = self.factory.post(
            '/exec/transfer/',
            data={'data': json.dumps({
                'host_ids': [self.host.id],
                'dst_dir': '/tmp',
                'mfa_ticket': ticket,
            })},
        )
        request.user = self.user
        response = TransferView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def dispatch_command(self, token):
        request = self.factory.patch(
            '/exec/do/',
            data=json.dumps({'token': token}),
            content_type='application/json',
        )
        request.user = self.user
        with patch('apps.exec.views.get_redis_connection') as get_redis:
            response = TaskView.as_view()(request)
        return json.loads(response.content.decode('utf-8')), get_redis

    def dispatch_transfer(self, token):
        request = self.factory.patch(
            '/exec/transfer/',
            data=json.dumps({'token': token}),
            content_type='application/json',
        )
        request.user = self.user
        with patch('apps.exec.transfer.Thread') as thread:
            response = TransferView.as_view()(request)
        return json.loads(response.content.decode('utf-8')), thread

    def test_command_execution_is_denied_when_mfa_is_disabled(self):
        result = self.execute('invalid-ticket')

        self.assertIn('系统未开启MFA认证', result['error'])
        self.assertEqual(0, ExecHistory.objects.count())

    def test_command_execution_consumes_mfa_ticket_once(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'exec_task')

        first = self.execute(ticket)
        second = self.execute(ticket)

        self.assertFalse(first['error'])
        self.assertEqual(32, len(first['data']))
        self.assertIn('已失效或已被使用', second['error'])
        self.assertEqual(1, ExecHistory.objects.count())

    def test_command_dispatch_consumes_bound_authorization_once(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'exec_task')
        created = self.execute(ticket)

        first, get_redis = self.dispatch_command(created['data'])
        second, _ = self.dispatch_command(created['data'])

        self.assertFalse(first['error'])
        get_redis.return_value.rpush.assert_called_once()
        self.assertIn('已失效或已被使用', second['error'])

    def test_file_transfer_is_denied_when_mfa_is_disabled(self):
        result = self.transfer('invalid-ticket')

        self.assertIn('系统未开启MFA认证', result['error'])
        self.assertEqual(0, Transfer.objects.count())

    def test_file_transfer_consumes_mfa_ticket_once(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'file_transfer')

        with tempfile.TemporaryDirectory() as transfer_dir:
            with override_settings(TRANSFER_DIR=transfer_dir):
                first = self.transfer(ticket)
                second = self.transfer(ticket)

        self.assertFalse(first['error'])
        self.assertEqual(32, len(first['data']))
        self.assertIn('已失效或已被使用', second['error'])
        self.assertEqual(1, Transfer.objects.count())

    def test_file_transfer_dispatch_consumes_bound_authorization_once(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'file_transfer')

        with tempfile.TemporaryDirectory() as transfer_dir:
            with override_settings(TRANSFER_DIR=transfer_dir):
                created = self.transfer(ticket)
                first, thread = self.dispatch_transfer(created['data'])
                second, _ = self.dispatch_transfer(created['data'])

        self.assertFalse(first['error'])
        thread.return_value.start.assert_called_once()
        self.assertIn('已失效或已被使用', second['error'])
