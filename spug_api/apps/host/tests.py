from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase

from apps.account.models import User
from apps.host.models import Host
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
