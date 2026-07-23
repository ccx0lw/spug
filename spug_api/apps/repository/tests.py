import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase
from git import Actor, Repo

from apps.repository import utils as repository_utils
from apps.account.models import User
from apps.app.models import App, Deploy
from apps.config.models import Environment
from apps.repository.models import Repository
from apps.repository.views import RepositoryView, scoped_repositories
from libs.utils import AttrDict


class _LocalBuildHelper:
    def __init__(self):
        self.commands = []

    def local(self, command, env=None):
        self.commands.append(command)
        process_env = os.environ.copy()
        if env:
            process_env.update(dict(env.items()))
        task = subprocess.run(
            command,
            env=process_env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if task.returncode:
            raise RuntimeError(task.stdout.decode(errors='replace'))

    @staticmethod
    def parse_filter_rule(_rules, env=None):
        return []

    @staticmethod
    def send_info(_key, _message):
        return None

    @staticmethod
    def send_error(_key, message, with_break=True):
        raise RuntimeError(message)

    @staticmethod
    def send_step(_key, _step, _message):
        return None


class RepositoryArchiveSecurityTests(SimpleTestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.repos_dir = Path(self.workspace.name, 'repos')
        self.build_dir = Path(self.workspace.name, 'build')
        self.git_dir = self.repos_dir / '7'
        self.git_dir.mkdir(parents=True)
        self.repo = Repo.init(self.git_dir)
        Path(self.git_dir, 'application.txt').write_text(
            'trusted build content\n',
            encoding='utf-8',
        )
        self.repo.index.add(['application.txt'])
        actor = Actor('Spug Test', 'spug-test@example.invalid')
        self.repo.index.commit('initial', author=actor, committer=actor)
        self.repo.create_tag('v1.0.0')
        self.repo.create_tag('release')
        self.shell_sensitive_tag = 'release;touch${IFS}marker'
        self.repo.create_tag(self.shell_sensitive_tag)

    def tearDown(self):
        self.repo.close()
        self.workspace.cleanup()

    def _build_extra(self, extra):
        version = '7_20260723120000'
        extend = SimpleNamespace(
            git_repo='unused-for-local-regression',
            dst_dir='/srv/spug',
            hook_pre_server='',
            hook_post_server='',
            filter_rule=json.dumps({'type': 'exclude', 'data': []}),
        )
        rep = SimpleNamespace(
            deploy_id=7,
            spug_version=version,
            extra=json.dumps(extra),
            deploy=SimpleNamespace(extend_obj=extend),
        )
        helper = _LocalBuildHelper()
        build_error = None
        with patch.object(repository_utils, 'REPOS_DIR', str(self.repos_dir)), \
                patch.object(repository_utils, 'BUILD_DIR', str(self.build_dir)), \
                patch.object(repository_utils, 'fetch_repo'):
            try:
                repository_utils._build(rep, helper, AttrDict())
            except RuntimeError as exc:
                build_error = exc
        return version, helper, build_error

    def _build_tag(self, tag):
        return self._build_extra(['tag', tag, None])

    def test_normal_tag_is_archived(self):
        version, _helper, build_error = self._build_tag('v1.0.0')

        self.assertIsNone(build_error)
        self.assertEqual(
            'trusted build content\n',
            Path(self.repos_dir, version, 'application.txt').read_text(encoding='utf-8'),
        )
        self.assertTrue(Path(self.build_dir, f'{version}.tar.gz').is_file())

    def test_shell_sensitive_tag_is_treated_as_revision_data(self):
        version, helper, build_error = self._build_tag(self.shell_sensitive_tag)

        self.assertFalse(Path(self.git_dir, 'marker').exists())
        self.assertIsNone(build_error)
        self.assertEqual(
            'trusted build content\n',
            Path(self.repos_dir, version, 'application.txt').read_text(encoding='utf-8'),
        )
        self.assertFalse(
            any(self.shell_sensitive_tag in command for command in helper.commands),
            'Git revision must never be interpolated into a Shell command',
        )

    def test_branch_commit_is_archived(self):
        commit_id = self.repo.head.commit.hexsha
        version, _helper, build_error = self._build_extra(
            ['branch', 'main', commit_id]
        )

        self.assertIsNone(build_error)
        self.assertEqual(
            'trusted build content\n',
            Path(self.repos_dir, version, 'application.txt').read_text(encoding='utf-8'),
        )

    def test_branch_revision_with_shell_suffix_is_rejected_before_execution(self):
        revision = f'{self.repo.head.commit.hexsha};touch${{IFS}}branch-marker'
        _version, helper, build_error = self._build_extra(
            ['branch', 'main', revision]
        )

        self.assertIsInstance(build_error, RuntimeError)
        self.assertIn('Commit ID格式错误', str(build_error))
        self.assertFalse(Path(self.git_dir, 'branch-marker').exists())
        self.assertFalse(
            any(revision in command for command in helper.commands),
            'Invalid commit input must be rejected before any Shell command',
        )


class RepositoryObjectScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='repository-admin',
            nickname='仓库管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='仓库环境',
            key='repository-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='仓库应用',
            key='repository-app',
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
        self.repository = Repository.objects.create(
            app=self.app,
            env=self.env,
            deploy=self.deploy,
            version='v1',
            spug_version='1_20260723120000',
            extra='["tag", "v1", null]',
            created_by=self.creator,
        )

    def scoped_user(self, apps, envs):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            has_perms=lambda codes: True,
        )

    @patch('apps.repository.views.Thread')
    def test_out_of_scope_rebuild_is_rejected_before_dispatch(self, thread):
        request = self.factory.patch(
            '/api/repository/',
            data=json.dumps({'id': self.repository.id, 'action': 'rebuild'}),
            content_type='application/json',
        )
        request.user = self.scoped_user([], [])

        response = RepositoryView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('未找到指定构建记录', result['error'])
        thread.assert_not_called()

    def test_scope_requires_both_app_and_environment(self):
        app_only = self.scoped_user([self.app.id], [])
        full_scope = self.scoped_user([self.app.id], [self.env.id])

        self.assertFalse(
            scoped_repositories(app_only).filter(pk=self.repository.id).exists()
        )
        self.assertTrue(
            scoped_repositories(full_scope).filter(pk=self.repository.id).exists()
        )
