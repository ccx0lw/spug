import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from apps.account.mfa import issue_sensitive_ticket
from apps.account.models import Role, User
from apps.exec.models import ExecHistory, Transfer
from apps.exec.transfer import (
    TransferView,
    _dispatch_sync,
    _make_rsync_command,
    _make_sshfs_command,
    _remote_is_dir_command,
)
from apps.exec.views import TaskView
from apps.host.models import Group, Host
from apps.setting.utils import AppSetting


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'exec-mfa-tests',
    }
}


class TransferCommandBoundaryTests(TestCase):
    def test_remote_source_path_is_shell_quoted(self):
        command = _remote_is_dir_command(
            '/srv/releases; touch /tmp/spug-transfer-probe'
        )

        self.assertEqual(
            "[ -d '/srv/releases; touch /tmp/spug-transfer-probe' ]",
            command,
        )

    def test_sshfs_uses_argument_array(self):
        host = SimpleNamespace(
            username='deploy',
            hostname='host.internal',
            port=22,
        )

        command = _make_sshfs_command(
            host,
            '/srv/releases; touch /tmp/probe',
            '/tmp/private-key',
            '/tmp/mount-point',
        )

        self.assertIsInstance(command, list)
        self.assertEqual(
            'deploy@host.internal:/srv/releases; touch /tmp/probe',
            command[-2],
        )

    def test_rsync_protects_remote_path_arguments(self):
        task = SimpleNamespace(
            host_id=None,
            src_dir='/tmp/source',
            dst_dir='/srv/releases; touch /tmp/probe',
        )
        host = SimpleNamespace(
            username='deploy',
            hostname='host.internal',
            port=22,
        )

        command = _make_rsync_command(task, host, '/tmp/private-key')

        self.assertIn('--protect-args', command)
        self.assertIn('--', command)
        self.assertEqual(
            'deploy@host.internal:/srv/releases; touch /tmp/probe',
            command[-1],
        )


@override_settings(CACHES=TEST_CACHES)
class TransferSourceHostAuthorizationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username='transfer-operator',
            nickname='文件分发用户',
            password_hash='-',
            access_token='',
            token_expired=0,
            last_login='',
            last_ip='',
        )
        self.role = Role.objects.create(
            name='文件分发角色',
            page_perms=json.dumps({
                'exec': {'transfer': {'do': True}},
            }),
            group_perms='[]',
            created_by=self.user,
        )
        self.user.roles.add(self.role)
        self.target_group = Group.objects.create(name='授权目标分组')
        self.source_group = Group.objects.create(name='越权来源分组')
        self.target = Host.objects.create(
            name='授权目标主机',
            hostname='10.0.0.1',
            port=22,
            username='root',
            created_by=self.user,
        )
        self.source = Host.objects.create(
            name='越权来源主机',
            hostname='10.0.0.2',
            port=22,
            username='root',
            created_by=self.user,
        )
        self.target_group.hosts.add(self.target)
        self.source_group.hosts.add(self.source)
        self.role.group_perms = json.dumps([self.target_group.id])
        self.role.save(update_fields=('group_perms',))

    def test_unauthorized_source_host_is_rejected_before_ssh(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'file_transfer')
        request = self.factory.post(
            '/exec/transfer/',
            data={'data': json.dumps({
                'host': json.dumps([self.source.id, '/srv/releases']),
                'host_ids': [self.target.id],
                'dst_dir': '/tmp',
                'mfa_ticket': ticket,
            })},
        )
        request.user = self.user

        with patch.object(Host, 'get_ssh') as get_ssh:
            response = TransferView.as_view()(request)
        result = json.loads(response.content.decode())

        self.assertIn('无权访问数据源主机', result['error'])
        get_ssh.assert_not_called()
        self.assertEqual(0, Transfer.objects.count())

    @patch('apps.exec.transfer._cleanup_transfer_dir')
    @patch('apps.exec.transfer.get_redis_connection')
    def test_worker_rechecks_source_scope_after_queueing(
            self, get_redis, cleanup):
        task = Transfer.objects.create(
            user=self.user,
            digest='source-scope-recheck',
            host_id=self.source.id,
            src_dir='/tmp/source-scope-recheck',
            dst_dir='/tmp',
            host_ids=json.dumps([self.target.id]),
        )

        _dispatch_sync(task)

        get_redis.return_value.publish.assert_called_once()
        cleanup.assert_called_once_with(
            task.src_dir,
            mounted=True,
        )


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
