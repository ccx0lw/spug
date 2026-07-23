import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from git import Actor, Repo

from apps.repository import utils as repository_utils
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
