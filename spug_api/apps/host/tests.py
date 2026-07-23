import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)

from apps.account.models import Role, User
from apps.host.models import Group, Host
from apps.host.views import HostView, batch_valid
from libs.ssh import SSH, _finalize_pubkey_algorithm


class PublicKeyAlgorithmTests(SimpleTestCase):
    @staticmethod
    def make_handler(remote_version, server_algorithms=b''):
        transport = SimpleNamespace(
            remote_version=remote_version,
            preferred_pubkeys=(
                'rsa-sha2-512',
                'rsa-sha2-256',
                'ssh-rsa',
            ),
            server_extensions={'server-sig-algs': server_algorithms},
            _agreed_pubkey_algorithm=None,
        )
        return SimpleNamespace(transport=transport)

    def test_modern_openssh_without_extension_uses_rsa_sha2(self):
        handler = self.make_handler('SSH-2.0-OpenSSH_10.2')

        algorithm = _finalize_pubkey_algorithm(handler, 'ssh-rsa')

        self.assertEqual('rsa-sha2-512', algorithm)
        self.assertEqual(
            'rsa-sha2-512',
            handler.transport._agreed_pubkey_algorithm,
        )

    def test_old_openssh_keeps_ssh_rsa_compatibility(self):
        handler = self.make_handler('SSH-2.0-OpenSSH_7.6')

        algorithm = _finalize_pubkey_algorithm(handler, 'ssh-rsa')

        self.assertEqual('ssh-rsa', algorithm)

    def test_server_algorithm_list_is_respected(self):
        handler = self.make_handler(
            'SSH-2.0-OpenSSH_9.8',
            b'rsa-sha2-256,ssh-ed25519',
        )

        algorithm = _finalize_pubkey_algorithm(handler, 'ssh-rsa')

        self.assertEqual('rsa-sha2-256', algorithm)


class AddPublicKeyTests(SimpleTestCase):
    def test_authorized_keys_write_is_idempotent_and_newline_safe(self):
        ssh = SSH('127.0.0.1')
        ssh.exec_command_raw = Mock(return_value=(0, ''))

        ssh.add_public_key('  ssh-rsa AAAATEST spug  ')

        command = ssh.exec_command_raw.call_args.args[0]
        self.assertIn('grep -qxF', command)
        self.assertIn("printf '\\n%s\\n'", command)
        self.assertIn('chmod 700 "$HOME/.ssh"', command)
        self.assertIn('chmod 600 "$HOME/.ssh/authorized_keys"', command)
        self.assertIn("'ssh-rsa AAAATEST spug'", command)

    def test_empty_public_key_is_rejected(self):
        ssh = SSH('127.0.0.1')

        with self.assertRaisesRegex(ValueError, 'SSH 公钥不能为空'):
            ssh.add_public_key('  ')

    def test_remote_write_failure_is_reported(self):
        ssh = SSH('127.0.0.1')
        ssh.exec_command_raw = Mock(return_value=(1, 'permission denied'))

        with self.assertRaisesRegex(Exception, '写入 SSH 公钥失败'):
            ssh.add_public_key('ssh-rsa AAAATEST spug')


class HostSerializationSecurityTests(TestCase):
    def test_host_inventory_never_returns_private_key(self):
        creator = User.objects.create(
            username='host-admin',
            nickname='主机管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        host = Host.objects.create(
            name='生产主机',
            hostname='10.0.0.10',
            port=22,
            username='deploy',
            pkey='-----BEGIN PRIVATE KEY-----secret',
            created_by=creator,
        )

        response = host.to_view()

        self.assertNotIn('pkey', response)
        self.assertEqual('10.0.0.10', response['hostname'])


class EnvironmentVariableSecurityTests(SimpleTestCase):
    def test_valid_environment_key_is_exported(self):
        ssh = SSH('127.0.0.1')

        command = ssh._make_env_command({'_SPUG_RELEASE': 'v1'})

        self.assertEqual("export _SPUG_RELEASE='v1'", command)

    def test_shell_syntax_in_environment_key_is_rejected(self):
        ssh = SSH('127.0.0.1')

        with self.assertRaisesRegex(ValueError, '环境变量名称格式错误'):
            ssh._make_env_command({
                '_SPUG_X; touch /tmp/spug-config-probe': 'value'
            })


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'host-management-scope-tests',
    },
})
class HostManagementScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.admin = self.make_user('admin', {}, [], is_supper=True)
        self.allowed_group = Group.objects.create(name='授权分组')
        self.denied_group = Group.objects.create(name='越权分组')
        self.allowed_host = self.make_host('授权主机', self.allowed_group)
        self.denied_host = self.make_host('越权主机', self.denied_group)

    def make_user(self, name, host_perms, group_perms, is_supper=False):
        user = User.objects.create(
            username=name,
            nickname=name,
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=is_supper,
        )
        if not is_supper:
            role = Role.objects.create(
                name=f'{name}-role',
                page_perms=json.dumps({'host': {'host': host_perms}}),
                group_perms=json.dumps(group_perms),
                created_by=self.admin if hasattr(self, 'admin') else user,
            )
            user.roles.add(role)
        return user

    def make_host(self, name, group):
        host = Host.objects.create(
            name=name,
            hostname='127.0.0.1',
            port=22,
            username='root',
            created_by=self.admin,
        )
        host.groups.add(group)
        return host

    def post_host(self, user, host=None, group=None):
        request = self.factory.post(
            '/api/host/',
            data=json.dumps({
                'id': host.id if host else None,
                'group_ids': [(group or self.allowed_group).id],
                'name': host.name if host else '新主机',
                'username': 'root',
                'hostname': '127.0.0.2',
                'port': 22,
                'password': '',
            }),
            content_type='application/json',
        )
        request.user = user
        with patch('apps.host.views._do_host_verify') as verify:
            response = HostView.as_view()(request)
        return json.loads(response.content.decode()), verify

    def test_add_permission_cannot_edit_existing_host(self):
        user = self.make_user(
            'add-only',
            {'add': True},
            [self.allowed_group.id],
        )

        result, verify = self.post_host(user, self.allowed_host)

        self.assertEqual('权限拒绝', result['error'])
        verify.assert_not_called()

    def test_edit_rejects_host_outside_current_group_scope(self):
        user = self.make_user(
            'editor',
            {'edit': True},
            [self.allowed_group.id],
        )

        result, verify = self.post_host(
            user,
            self.denied_host,
            self.allowed_group,
        )

        self.assertEqual('无权访问目标主机', result['error'])
        verify.assert_not_called()

    def test_add_rejects_unauthorized_target_group(self):
        user = self.make_user(
            'creator',
            {'add': True},
            [self.allowed_group.id],
        )

        result, verify = self.post_host(
            user,
            group=self.denied_group,
        )

        self.assertEqual('无权访问目标主机分组', result['error'])
        verify.assert_not_called()
        self.assertEqual(2, Host.objects.count())

    def test_delete_rejects_host_outside_group_scope(self):
        user = self.make_user(
            'deleter',
            {'del': True},
            [self.allowed_group.id],
        )
        request = self.factory.delete(
            f'/api/host/?id={self.denied_host.id}',
        )
        request.user = user

        response = HostView.as_view()(request)
        result = json.loads(response.content.decode())

        self.assertEqual('无权访问目标主机', result['error'])
        self.assertTrue(Host.objects.filter(pk=self.denied_host.id).exists())

    @patch('apps.host.views.Thread')
    def test_batch_validation_only_dispatches_scoped_hosts(self, thread):
        user = self.make_user(
            'validator',
            {'add': True},
            [self.allowed_group.id],
        )
        request = self.factory.post(
            '/api/host/valid/',
            data=json.dumps({'range': '1'}),
            content_type='application/json',
        )
        request.user = user

        response = batch_valid(request)
        result = json.loads(response.content.decode())

        self.assertFalse(result['error'])
        self.assertEqual(
            [str(self.allowed_host.id)],
            list(result['data']['hosts'].keys()),
        )
        dispatched_hosts = list(thread.call_args.kwargs['args'][1])
        self.assertEqual([self.allowed_host.id], [x.id for x in dispatched_hosts])
