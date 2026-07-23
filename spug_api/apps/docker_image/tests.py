import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.account.models import User
from apps.app.models import App, Deploy
from apps.config.models import Environment
from apps.docker_image.models import DockerImage
from apps.docker_image.views import DockerImageView, scoped_docker_images


class DockerImageObjectScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='image-admin',
            nickname='镜像管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='镜像环境',
            key='image-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='镜像应用',
            key='image-app',
            created_by=self.creator,
        )
        self.deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='3',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )
        self.image = DockerImage.objects.create(
            app=self.app,
            env=self.env,
            deploy=self.deploy,
            version='v1',
            spug_version='1_20260723120000',
            url='registry/image:v1',
            extra='["tag", "v1", null]',
            created_by=self.creator,
        )

    def scoped_user(self, apps, envs):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            has_perms=lambda codes: True,
        )

    @patch('apps.docker_image.views.Thread')
    def test_out_of_scope_rebuild_is_rejected_before_dispatch(self, thread):
        request = self.factory.patch(
            '/api/docker-image/',
            data=json.dumps({'id': self.image.id, 'action': 'rebuild'}),
            content_type='application/json',
        )
        request.user = self.scoped_user([], [])

        response = DockerImageView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('未找到指定构建记录', result['error'])
        thread.assert_not_called()

    def test_scope_requires_both_app_and_environment(self):
        app_only = self.scoped_user([self.app.id], [])
        full_scope = self.scoped_user([self.app.id], [self.env.id])

        self.assertFalse(
            scoped_docker_images(app_only).filter(pk=self.image.id).exists()
        )
        self.assertTrue(
            scoped_docker_images(full_scope).filter(pk=self.image.id).exists()
        )
