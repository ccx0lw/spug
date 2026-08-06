import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from apps.account.models import User
from apps.app.models import App, Deploy, DeployExtend1, DeployExtend2
from apps.app.views import DeployView, clean_repo, kit_key
from apps.config.models import Environment, Tag
from apps.deploy.models import DeployRequest


class CleanDeployRepoTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='clean-repo-admin',
            nickname='目录清理管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='目录清理环境',
            key='clean-repo-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='目录清理应用',
            key='clean-repo-app',
            created_by=self.creator,
        )
        self.frontend_tag = Tag.objects.create(
            name='前端',
            key='front',
            created_by=self.creator,
        )
        self.app.rel_tags = json.dumps([self.frontend_tag.id])
        self.app.save(update_fields=('rel_tags',))
        self.deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )

    def clean(self, repos_dir, target='node_modules', user=None):
        request = self.factory.post(
            '/api/app/deploy/clean/',
            data=json.dumps({
                'deploy_id': self.deploy.id,
                'target': target,
            }),
            content_type='application/json',
        )
        request.user = user or self.creator
        with override_settings(REPOS_DIR=repos_dir):
            response = clean_repo(request)
        return json.loads(response.content.decode('utf-8'))

    def test_clean_node_modules_preserves_repository(self):
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            modules_dir = os.path.join(deploy_dir, 'node_modules', 'dependency')
            os.makedirs(modules_dir)
            package_file = os.path.join(deploy_dir, 'package.json')
            with open(package_file, 'w') as f:
                f.write('{}')

            result = self.clean(repos_dir)

            self.assertFalse(result['error'])
            self.assertTrue(result['data']['removed'])
            self.assertFalse(os.path.exists(os.path.join(deploy_dir, 'node_modules')))
            self.assertTrue(os.path.isfile(package_file))

    def test_clean_entire_repository_preserves_sibling_deploy(self):
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            sibling_dir = os.path.join(repos_dir, f'{self.deploy.id}-sibling')
            os.makedirs(deploy_dir)
            os.makedirs(sibling_dir)

            result = self.clean(repos_dir, 'repo')

            self.assertFalse(result['error'])
            self.assertTrue(result['data']['removed'])
            self.assertFalse(os.path.exists(deploy_dir))
            self.assertTrue(os.path.isdir(sibling_dir))

    def test_missing_directory_is_an_idempotent_success(self):
        with tempfile.TemporaryDirectory() as repos_dir:
            result = self.clean(repos_dir, 'repo')

            self.assertFalse(result['error'])
            self.assertFalse(result['data']['removed'])

    def test_out_of_scope_deploy_is_rejected(self):
        user = SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(), 'envs': set()},
            has_perms=lambda codes: True,
        )
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)

            result = self.clean(repos_dir, 'repo', user)

            self.assertIn('无操作权限', result['error'])
            self.assertTrue(os.path.isdir(deploy_dir))

    def test_edit_permission_does_not_authorize_cleanup(self):
        user = SimpleNamespace(
            is_supper=False,
            deploy_perms={
                'apps': {self.app.id},
                'envs': {self.env.id},
            },
            has_perms=lambda codes: bool(
                {'deploy.app.edit'}.intersection(codes)
            ),
        )
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)

            result = self.clean(repos_dir, 'repo', user)

            self.assertEqual('权限拒绝', result['error'])
            self.assertTrue(os.path.isdir(deploy_dir))

    def test_non_frontend_app_is_rejected(self):
        self.app.rel_tags = '[]'
        self.app.save(update_fields=('rel_tags',))
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)

            result = self.clean(repos_dir, 'repo')

            self.assertIn('仅标记为前端', result['error'])
            self.assertTrue(os.path.isdir(deploy_dir))

    def test_clean_permission_authorizes_cleanup(self):
        user = SimpleNamespace(
            is_supper=False,
            deploy_perms={
                'apps': {self.app.id},
                'envs': {self.env.id},
            },
            has_perms=lambda codes: bool(
                {'deploy.app.clean'}.intersection(codes)
            ),
        )
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)

            result = self.clean(repos_dir, 'repo', user)

            self.assertFalse(result['error'])
            self.assertFalse(os.path.exists(deploy_dir))

    def test_running_deploy_is_rejected(self):
        DeployRequest.objects.create(
            deploy=self.deploy,
            name='正在发布',
            extra='[]',
            host_ids='[]',
            status='2',
            created_by=self.creator,
        )
        with tempfile.TemporaryDirectory() as repos_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)

            result = self.clean(repos_dir, 'repo')

            self.assertIn('发布中或结果未知', result['error'])
            self.assertTrue(os.path.isdir(deploy_dir))

    def test_node_modules_symlink_is_unlinked_without_touching_target(self):
        with tempfile.TemporaryDirectory() as repos_dir, \
                tempfile.TemporaryDirectory() as external_dir:
            deploy_dir = os.path.join(repos_dir, str(self.deploy.id))
            os.makedirs(deploy_dir)
            external_file = os.path.join(external_dir, 'keep.txt')
            with open(external_file, 'w') as f:
                f.write('keep')
            os.symlink(external_dir, os.path.join(deploy_dir, 'node_modules'))

            result = self.clean(repos_dir)

            self.assertFalse(result['error'])
            self.assertTrue(result['data']['removed'])
            self.assertTrue(os.path.isfile(external_file))
            self.assertFalse(os.path.lexists(os.path.join(deploy_dir, 'node_modules')))


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
