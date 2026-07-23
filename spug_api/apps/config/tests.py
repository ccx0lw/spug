import json
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.account.models import User
from apps.app.models import App
from apps.config.models import Config, ConfigHistory, Environment
from apps.config.views import CONFIG_KEY_RE, ConfigView


class ConfigKeySecurityTests(SimpleTestCase):
    def test_valid_config_key_format_is_preserved(self):
        self.assertIsNotNone(CONFIG_KEY_RE.fullmatch('_SPUG_RELEASE_TAG'))

    def test_shell_syntax_in_config_key_is_rejected_by_api(self):
        request = RequestFactory().post(
            '/api/config/',
            data=json.dumps({
                'o_id': 1,
                'type': 'app',
                'envs': [1],
                'key': '_SPUG_X; touch /tmp/spug-config-probe',
                'is_public': False,
                'value': 'safe',
            }),
            content_type='application/json',
        )
        request.user = SimpleNamespace(
            is_supper=True,
            has_perms=lambda codes: True,
        )

        response = ConfigView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('只能包含字母', result['error'])


class ConfigObjectScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='config-admin',
            nickname='配置管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='配置环境',
            key='config-env',
            created_by=self.creator,
        )
        self.other_env = Environment.objects.create(
            name='其他环境',
            key='other-config-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='配置应用',
            key='config-app',
            created_by=self.creator,
        )
        self.config = Config.objects.create(
            type='app',
            o_id=self.app.id,
            key='_SPUG_SECRET',
            env=self.env,
            value='original',
            is_public=False,
            updated_at='2026-07-23 10:00:00',
            updated_by=self.creator,
        )

    def scoped_user(self, page_perms, apps, envs):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            has_perms=lambda codes: bool(set(codes).intersection(page_perms)),
        )

    def test_service_permission_cannot_read_application_config(self):
        request = self.factory.get(
            '/api/config/',
            data={
                'id': self.app.id,
                'type': 'app',
                'env_id': self.env.id,
            },
        )
        request.user = self.scoped_user(
            {'config.src.view_config'},
            [self.app.id],
            [self.env.id],
        )

        response = ConfigView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('无操作权限', result['error'])

    def test_record_update_rechecks_own_scope(self):
        request = self.factory.patch(
            '/api/config/',
            data=json.dumps({
                'id': self.config.id,
                'value': 'changed',
                'is_public': False,
                'desc': '',
            }),
            content_type='application/json',
        )
        request.user = self.scoped_user(
            {'config.app.edit_config'},
            [self.app.id],
            [],
        )

        response = ConfigView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('无操作权限', result['error'])
        self.config.refresh_from_db()
        self.assertEqual('original', self.config.value)
        self.assertEqual(0, ConfigHistory.objects.count())

    def test_mixed_environment_batch_is_rejected_atomically(self):
        request = self.factory.post(
            '/api/config/',
            data=json.dumps({
                'o_id': self.app.id,
                'type': 'app',
                'envs': [self.env.id, self.other_env.id],
                'key': '_SPUG_NEW_VALUE',
                'is_public': False,
                'value': 'new',
            }),
            content_type='application/json',
        )
        request.user = self.scoped_user(
            {'config.app.edit_config'},
            [self.app.id],
            [self.env.id],
        )

        response = ConfigView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('无操作权限', result['error'])
        self.assertFalse(Config.objects.filter(key='_SPUG_NEW_VALUE').exists())
