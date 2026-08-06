# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf import settings
from apps.app.models import Deploy
from apps.setting.utils import AppSetting
from libs.gitlib import Git
from pathlib import Path
import shutil
import os


def has_app_env_scope(user, app_id, env_id):
    if user.is_supper:
        return True
    perms = user.deploy_perms
    return app_id in perms['apps'] and env_id in perms['envs']


def has_deploy_scope(user, deploy):
    return has_app_env_scope(user, deploy.app_id, deploy.env_id)


def scoped_deploys(user):
    queryset = Deploy.objects.all()
    if user.is_supper:
        return queryset
    perms = user.deploy_perms
    return queryset.filter(
        app_id__in=perms['apps'],
        env_id__in=perms['envs'],
    )


def parse_envs(text):
    data = {}
    if text:
        for line in text.split('\n'):
            fields = line.split('=', 1)
            if len(fields) != 2 or fields[0].strip() == '':
                raise Exception(f'解析自定义全局变量{line!r}失败，确认其遵循 key = value 格式')
            data[fields[0].strip()] = fields[1].strip()
    return data


def fetch_versions(deploy: Deploy):
    git_repo = deploy.extend_obj.git_repo
    repo_dir = os.path.join(settings.REPOS_DIR, str(deploy.id))
    pkey = AppSetting.get_default('private_key')
    with Git(git_repo, repo_dir, pkey) as git:
        return git.fetch_branches_tags()


def fetch_repo(deploy_id, git_repo):
    repo_dir = os.path.join(settings.REPOS_DIR, str(deploy_id))
    pkey = AppSetting.get_default('private_key')
    with Git(git_repo, repo_dir, pkey) as git:
        return git.fetch_branches_tags()


def remove_repo(deploy_id):
    shutil.rmtree(os.path.join(settings.REPOS_DIR, str(deploy_id)), True)


def clean_deploy_repo(deploy_id, target):
    """Safely remove a deploy repository or only its node_modules directory."""
    if target not in ('repo', 'node_modules'):
        raise ValueError('不支持的清理范围')

    repos_dir = Path(settings.REPOS_DIR).resolve()
    deploy_dir = repos_dir / str(int(deploy_id))
    if deploy_dir.parent != repos_dir:
        raise ValueError('发布目录不安全，已拒绝清理')

    if target == 'node_modules':
        # Never follow a deploy-directory symlink to delete data outside REPOS_DIR.
        if deploy_dir.is_symlink():
            raise ValueError('发布目录为符号链接，已拒绝清理 node_modules')
        clean_path = deploy_dir / 'node_modules'
    else:
        clean_path = deploy_dir

    if not clean_path.exists() and not clean_path.is_symlink():
        return False
    if clean_path.is_symlink() or not clean_path.is_dir():
        clean_path.unlink()
    else:
        shutil.rmtree(clean_path)
    return True
