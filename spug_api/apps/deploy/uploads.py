from pathlib import Path, PurePosixPath
import re

from django.conf import settings


STORAGE_NAME_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def normalize_upload_name(value):
    value = str(value or '').replace('\\', '/')
    name = PurePosixPath(value).name
    if (
            not name
            or name in ('.', '..')
            or '\x00' in name
            or len(name) > 255):
        raise ValueError('上传文件名无效')
    return name


def resolve_upload_path(deploy_id, storage_name, must_exist=False):
    storage_name = str(storage_name or '')
    if not STORAGE_NAME_PATTERN.fullmatch(storage_name):
        raise ValueError('上传文件路径无效')
    root = Path(settings.REPOS_DIR).resolve()
    deploy_dir = (root / str(int(deploy_id))).resolve()
    if deploy_dir.parent != root:
        raise ValueError('上传文件路径无效')
    candidate = deploy_dir / storage_name
    if candidate.is_symlink():
        raise ValueError('上传文件不存在或已失效')
    path = candidate.resolve()
    if path.parent != deploy_dir:
        raise ValueError('上传文件路径无效')
    if must_exist and not path.is_file():
        raise ValueError('上传文件不存在或已失效')
    return path
