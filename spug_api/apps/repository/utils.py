# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import json
import os
import re
import subprocess
import uuid
from tempfile import TemporaryFile

from django_redis import get_redis_connection
from django.conf import settings
from django.db import close_old_connections
from git import BadName, Repo

from libs.utils import AttrDict, human_time, render_str
from apps.repository.models import Repository
from apps.app.utils import fetch_repo
from apps.config.utils import compose_configs
from apps.deploy.helper import Helper

REPOS_DIR = settings.REPOS_DIR
BUILD_DIR = settings.BUILD_DIR
COMMIT_ID_RE = re.compile(r'^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$')


def dispatch(rep: Repository, helper=None):
    rep.status = '1'
    alone_build = helper is None
    if not helper:
        rds = get_redis_connection()
        rds_key = f'{settings.BUILD_KEY}:{rep.spug_version}'
        helper = Helper.make(rds, rds_key)
        rep.save()
    try:
        api_token = uuid.uuid4().hex
        helper.rds.setex(api_token, 60 * 60, f'{rep.app_id},{rep.env_id}')
        helper.send_info('local', f'\033[32m完成√\033[0m\r\n{human_time()} 构建准备...        ')
        env = AttrDict(
            SPUG_APP_NAME=rep.app.name,
            SPUG_APP_KEY=rep.app.key,
            SPUG_APP_ID=str(rep.app_id),
            SPUG_DEPLOY_ID=str(rep.deploy_id),
            SPUG_BUILD_ID=str(rep.id),
            SPUG_ENV_ID=str(rep.env_id),
            SPUG_ENV_KEY=rep.env.key,
            SPUG_VERSION=rep.version,
            SPUG_BUILD_VERSION=rep.spug_version,
            SPUG_API_TOKEN=api_token,
            SPUG_REPOS_DIR=REPOS_DIR,
        )
        # append configs
        configs = compose_configs(rep.app, rep.env_id)
        configs_env = {f'{k.upper()}': v for k, v in configs.items()}
        env.update(configs_env)

        _build(rep, helper, env)
        rep.status = '5'
    except Exception as e:
        rep.status = '2'
        raise e
    finally:
        helper.local(f'cd {REPOS_DIR} && rm -rf {rep.spug_version}')
        close_old_connections()
        if alone_build:
            helper.clear()
            rep.save()
            return rep
        elif rep.status == '5':
            rep.save()


def _resolve_archive_commit(repo, source_type, revision):
    if not isinstance(revision, str):
        raise ValueError('Git版本参数错误')
    if source_type == 'branch':
        if not COMMIT_ID_RE.fullmatch(revision):
            raise ValueError('Commit ID格式错误')
        try:
            commit = repo.commit(revision)
            commit.tree
            return commit.hexsha
        except (BadName, ValueError):
            raise ValueError('未找到指定Commit ID')
    if source_type == 'tag':
        for tag in repo.tags:
            if tag.name == revision:
                return tag.commit.hexsha
        raise ValueError('未找到指定Tag')
    raise ValueError('不支持的Git版本类型')


def _archive_repository(git_dir, target_dir, build_name, source_type, revision):
    repo = Repo(git_dir)
    try:
        commit_id = _resolve_archive_commit(repo, source_type, revision)
        with TemporaryFile() as archive:
            repo.archive(archive, commit_id, prefix=f'{build_name}/')
            archive.seek(0)
            task = subprocess.run(
                ['tar', 'xf', '-'],
                cwd=target_dir,
                stdin=archive,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
            )
            if task.returncode:
                message = task.stdout.decode(errors='replace').strip()
                raise RuntimeError(message or f'tar退出码: {task.returncode}')
    finally:
        repo.close()


def _build(rep: Repository, helper, env):
    extend = rep.deploy.extend_obj
    extras = json.loads(rep.extra)
    git_dir = os.path.join(REPOS_DIR, str(rep.deploy_id))
    build_dir = os.path.join(REPOS_DIR, rep.spug_version)
    tar_file = os.path.join(BUILD_DIR, f'{rep.spug_version}.tar.gz')
    if extras[0] == 'branch':
        tree_ish = extras[2]
        env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
    else:
        tree_ish = extras[1]
        env.update(SPUG_GIT_TAG=extras[1])
    env.update(SPUG_DST_DIR=render_str(extend.dst_dir, env))
    fetch_repo(rep.deploy_id, extend.git_repo)
    helper.send_info('local', '\033[32m完成√\033[0m\r\n')

    if extend.hook_pre_server:
        helper.send_step('local', 1, f'{human_time()} 检出前任务...\r\n')
        helper.local(f'cd {git_dir} && {extend.hook_pre_server}', env)

    helper.send_step('local', 2, f'{human_time()} 执行检出...        ')
    try:
        _archive_repository(
            git_dir,
            REPOS_DIR,
            rep.spug_version,
            extras[0],
            tree_ish,
        )
    except Exception as e:
        helper.send_error('local', f'检出失败: {e}')
    helper.send_info('local', '\033[32m完成√\033[0m\r\n')

    if extend.hook_post_server:
        helper.send_step('local', 3, f'{human_time()} 检出后任务...\r\n')
        helper.local(f'cd {build_dir} && {extend.hook_post_server}', env)

    helper.send_step('local', 4, f'\r\n{human_time()} 执行打包...        ')
    filter_rule, exclude, contain = json.loads(extend.filter_rule), '', rep.spug_version
    files = helper.parse_filter_rule(filter_rule['data'], env=env)
    if files:
        if filter_rule['type'] == 'exclude':
            excludes = []
            for x in files:
                if x.startswith('/'):
                    excludes.append(f'--exclude={rep.spug_version}{x}')
                else:
                    excludes.append(f'--exclude={x}')
            exclude = ' '.join(excludes)
        else:
            contain = ' '.join(f'{rep.spug_version}/{x}' for x in files)
    helper.local(f'mkdir -p {BUILD_DIR} && cd {REPOS_DIR} && tar zcf {tar_file} {exclude} {contain}')
    helper.send_step('local', 5, f'\033[32m完成√\033[0m')
    helper.send_step('local', 100, f'\r\n\r\n{human_time()} ** \033[32m构建成功\033[0m **')
