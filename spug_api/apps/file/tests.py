import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from apps.account.mfa import issue_sensitive_ticket
from apps.account.models import User
from apps.file.views import FileView
from apps.host.models import Host
from apps.setting.utils import AppSetting


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'file-mfa-tests',
    }
}


@override_settings(CACHES=TEST_CACHES)
class FileManagerMFAEnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username='file-user',
            nickname='文件用户',
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
            created_by=self.user,
        )

    def fetch_files(self, ticket):
        request = self.factory.get('/file/', data={
            'id': self.host.id,
            'path': '/',
            'mfa_ticket': ticket,
        })
        request.user = self.user
        with patch('apps.file.views.fetch_dir_list', return_value=[]):
            response = FileView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def test_file_manager_is_denied_when_mfa_is_disabled(self):
        result = self.fetch_files('invalid-ticket')

        self.assertIn('系统未开启MFA认证', result['error'])

    def test_file_manager_accepts_reusable_console_ticket(self):
        AppSetting.set('MFA', {'enable': True, 'method': 'totp'})
        ticket, _ = issue_sensitive_ticket(self.user, 'host_console')

        first = self.fetch_files(ticket)
        second = self.fetch_files(ticket)

        self.assertFalse(first['error'])
        self.assertFalse(second['error'])
