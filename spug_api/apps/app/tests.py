import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.account.models import User
from apps.app.models import App, Deploy, DeployExtend1, DeployExtend2
from apps.app.views import DeployView, kit_key
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


class DeployConfigScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='deploy-config-admin',
            nickname='发布配置管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='发布配置环境',
            key='deploy-config-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='发布配置应用',
            key='deploy-config-app',
            created_by=self.creator,
        )

    def request_user(self, apps, envs):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            group_perms=[],
            has_perms=lambda codes: True,
        )

    def post_config(self, user, config_id=None, host_ids=None):
        data = {
            'id': config_id,
            'app_id': self.app.id,
            'env_id': self.env.id,
            'host_ids': host_ids or [999],
            'rst_notify': {'mode': '0'},
            'extend': '1',
            'is_parallel': True,
            'is_audit': False,
        }
        request = self.factory.post(
            '/api/app/deploy/',
            data=json.dumps(data),
            content_type='application/json',
        )
        request.user = user
        response = DeployView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def post_deploy(self, data):
        request = self.factory.post(
            '/api/app/deploy/',
            data=json.dumps(data),
            content_type='application/json',
        )
        request.user = self.creator
        response = DeployView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def deploy_data(self, extend):
        return {
            'app_id': self.app.id,
            'env_id': self.env.id,
            'host_ids': [999],
            'rst_notify': {'mode': '0'},
            'extend': extend,
            'is_parallel': True,
            'is_audit': False,
        }

    def test_out_of_scope_app_environment_is_rejected_before_write(self):
        result = self.post_config(self.request_user([], []))

        self.assertIn('无操作权限', result['error'])
        self.assertEqual(0, Deploy.objects.count())

    def test_out_of_scope_host_is_rejected_before_write(self):
        user = self.request_user([self.app.id], [self.env.id])

        result = self.post_config(user)

        self.assertEqual('无权访问目标主机', result['error'])
        self.assertEqual(0, Deploy.objects.count())

    def test_edit_cannot_take_over_existing_out_of_scope_config(self):
        deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )

        result = self.post_config(
            self.request_user([], []),
            config_id=deploy.id,
        )

        self.assertIn('无操作权限', result['error'])
        deploy.refresh_from_db()
        self.assertEqual('[]', deploy.host_ids)

    def test_create_and_edit_regular_deploy_without_build_image_host(self):
        data = self.deploy_data('1')
        data.update({
            'git_repo': 'https://example.com/repo.git',
            'dst_dir': '/srv/app/',
            'dst_repo': '/srv/releases',
            'versions': 5,
            'filter_rule': {},
        })

        result = self.post_deploy(data)

        self.assertFalse(result['error'])
        deploy = Deploy.objects.get(app=self.app, env=self.env)
        extend = DeployExtend1.objects.get(deploy=deploy)
        self.assertEqual('/srv/app', extend.dst_dir)

        data['id'] = deploy.id
        data['dst_dir'] = '/srv/app-v2/'
        result = self.post_deploy(data)

        self.assertFalse(result['error'])
        extend.refresh_from_db()
        self.assertEqual('/srv/app-v2', extend.dst_dir)

    def test_create_and_edit_custom_deploy_without_build_image_host(self):
        data = self.deploy_data('2')
        data.update({
            'server_actions': [{'type': 'command', 'command': 'echo build'}],
            'host_actions': [],
        })

        result = self.post_deploy(data)

        self.assertFalse(result['error'])
        deploy = Deploy.objects.get(app=self.app, env=self.env)
        extend = DeployExtend2.objects.get(deploy=deploy)
        self.assertEqual('echo build', json.loads(extend.server_actions)[0]['command'])

        data['id'] = deploy.id
        data['server_actions'][0]['command'] = 'echo deploy'
        result = self.post_deploy(data)

        self.assertFalse(result['error'])
        extend.refresh_from_db()
        self.assertEqual('echo deploy', json.loads(extend.server_actions)[0]['command'])
