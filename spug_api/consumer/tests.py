from types import SimpleNamespace

from django.test import TestCase

from apps.account.models import User
from apps.app.models import App, Deploy
from apps.config.models import Environment
from apps.deploy.models import DeployRequest
from apps.docker_image.models import DockerImage
from apps.repository.models import Repository
from consumer.consumers import can_read_com_log


class ComLogAuthorizationTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create(
            username='ws-log-admin',
            nickname='日志管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.allowed_env = Environment.objects.create(
            name='授权环境',
            key='ws-log-allowed-env',
            created_by=self.creator,
        )
        self.denied_env = Environment.objects.create(
            name='越权环境',
            key='ws-log-denied-env',
            created_by=self.creator,
        )
        self.allowed_app = App.objects.create(
            name='授权应用',
            key='ws-log-allowed-app',
            created_by=self.creator,
        )
        self.denied_app = App.objects.create(
            name='越权应用',
            key='ws-log-denied-app',
            created_by=self.creator,
        )
        self.allowed_request = self.make_request(
            self.allowed_app,
            self.allowed_env,
        )
        self.denied_request = self.make_request(
            self.denied_app,
            self.denied_env,
        )
        self.allowed_repository = self.make_repository(
            self.allowed_request.deploy,
            'allowed-build',
        )
        self.denied_repository = self.make_repository(
            self.denied_request.deploy,
            'denied-build',
        )
        self.allowed_image = self.make_image(
            self.allowed_request.deploy,
            'allowed-image',
        )
        self.denied_image = self.make_image(
            self.denied_request.deploy,
            'denied-image',
        )

    def make_request(self, app, env):
        deploy = Deploy.objects.create(
            app=app,
            env=env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )
        return DeployRequest.objects.create(
            deploy=deploy,
            name='WebSocket 日志授权测试',
            type='1',
            extra='["tag", "v1.0.0"]',
            host_ids='[]',
            status='2',
            version='v1.0.0',
            spug_version=f'{deploy.id}_ws_test',
            created_by=self.creator,
        )

    def make_repository(self, deploy, spug_version):
        return Repository.objects.create(
            app=deploy.app,
            env=deploy.env,
            deploy=deploy,
            version='v1.0.0',
            spug_version=spug_version,
            extra='["tag", "v1.0.0"]',
            created_by=self.creator,
        )

    def make_image(self, deploy, spug_version):
        return DockerImage.objects.create(
            app=deploy.app,
            env=deploy.env,
            deploy=deploy,
            version='v1.0.0',
            spug_version=spug_version,
            url='registry.example/app:v1.0.0',
            extra='["tag", "v1.0.0"]',
            created_by=self.creator,
        )

    def scoped_user(self, permissions):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={
                'apps': {self.allowed_app.id},
                'envs': {self.allowed_env.id},
            },
            has_perms=lambda codes: bool(
                set(codes).intersection(permissions)
            ),
        )

    def test_request_log_requires_page_and_object_scope(self):
        user = self.scoped_user({'deploy.request.view'})

        self.assertTrue(can_read_com_log(
            user,
            'request',
            str(self.allowed_request.id),
        ))
        self.assertFalse(can_read_com_log(
            user,
            'request',
            str(self.denied_request.id),
        ))

    def test_request_log_rejects_user_without_page_permission(self):
        user = self.scoped_user(set())

        self.assertFalse(can_read_com_log(
            user,
            'request',
            str(self.allowed_request.id),
        ))

    def test_request_log_rejects_invalid_or_missing_object(self):
        user = self.scoped_user({'deploy.request.view'})

        self.assertFalse(can_read_com_log(user, 'request', 'not-an-id'))
        self.assertFalse(can_read_com_log(user, 'request', '999999'))

    def test_build_logs_require_matching_object_scope(self):
        user = self.scoped_user({
            'deploy.repository.view',
            'deploy.docker_image.view',
        })

        self.assertTrue(can_read_com_log(
            user,
            'build',
            self.allowed_repository.spug_version,
        ))
        self.assertFalse(can_read_com_log(
            user,
            'build',
            self.denied_repository.spug_version,
        ))
        self.assertTrue(can_read_com_log(
            user,
            'build_image',
            self.allowed_image.spug_version,
        ))
        self.assertFalse(can_read_com_log(
            user,
            'build_image',
            self.denied_image.spug_version,
        ))
