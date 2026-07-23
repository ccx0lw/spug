import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.account.models import User
from apps.app.models import App, Deploy
from apps.app.views import kit_key
from apps.config.models import Environment


class ScopedWebhookKeyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='webhook-admin',
            nickname='Webhook管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='Webhook环境',
            key='webhook-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='Webhook应用',
            key='webhook-app',
            created_by=self.creator,
        )
        self.deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )

    def request_key(self, apps, envs):
        request = self.factory.post(
            '/api/app/kit/key/',
            data=json.dumps({
                'key': 'api_key',
                'deploy_id': self.deploy.id,
            }),
            content_type='application/json',
        )
        request.user = SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            has_perms=lambda codes: True,
        )
        with patch(
            'apps.apis.deploy.AppSetting.get_default',
            return_value='master-api-key',
        ):
            response = kit_key(request)
        return json.loads(response.content.decode('utf-8'))

    def test_authorized_user_gets_deploy_scoped_key(self):
        result = self.request_key([self.app.id], [self.env.id])

        self.assertFalse(result['error'])
        self.assertEqual(64, len(result['data']))
        self.assertNotEqual('master-api-key', result['data'])

    def test_out_of_scope_deploy_cannot_get_key(self):
        result = self.request_key([], [])

        self.assertIn('无操作权限', result['error'])
