# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from apps.host.models import Group
import re


def get_group_perms(user):
    if user.is_supper:
        return set(Group.objects.values_list('id', flat=True))
    ids = sub_ids = set(user.group_perms)
    while sub_ids:
        sub_ids = [x.id for x in Group.objects.filter(parent_id__in=sub_ids)]
        ids.update(sub_ids)
    return ids


def has_group_perm(user, target):
    if user.is_supper:
        return True
    group_ids = get_group_perms(user)
    if isinstance(target, (list, set, tuple)):
        try:
            target_ids = {int(x) for x in target}
        except (TypeError, ValueError):
            return False
        return bool(target_ids) and target_ids.issubset(group_ids)
    try:
        return int(target) in group_ids
    except (TypeError, ValueError):
        return False


def get_host_perms(user):
    ids = get_group_perms(user)
    return set(x.host_id for x in Group.hosts.through.objects.filter(group_id__in=ids))


def has_host_perm(user, target):
    if user.is_supper:
        return True
    host_ids = get_host_perms(user)
    if isinstance(target, (list, set, tuple)):
        try:
            target_ids = {int(x) for x in target}
        except (TypeError, ValueError):
            return False
        return target_ids.issubset(host_ids)
    try:
        return int(target) in host_ids
    except (TypeError, ValueError):
        return False


def has_host_management_scope(user, host):
    if user.is_supper:
        return True
    group_ids = set(host.groups.values_list('id', flat=True))
    return bool(group_ids) and group_ids.issubset(get_group_perms(user))


def verify_password(password):
    if len(password) < 8:
        return False
    if not all(map(lambda x: re.findall(x, password), ['[0-9]', '[a-z]', '[A-Z]'])):
        return False
    return True
