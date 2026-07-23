# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.conf import settings
from django.db import close_old_connections
from django_redis import get_redis_connection
from apps.exec.models import Transfer
from apps.account.utils import has_host_perm
from apps.account.mfa import (
    authorize_sensitive_action,
    consume_sensitive_action_authorization,
    validate_sensitive_ticket,
)
from apps.host.models import Host
from apps.setting.utils import AppSetting
from libs import json_response, JsonParser, Argument, auth
from libs.utils import str_decode, human_seconds_time
from concurrent import futures
from threading import Thread
import subprocess
import tempfile
import shlex
import shutil
import uuid
import json
import time
import os


def _remote_is_dir_command(path):
    return f'[ -d {shlex.quote(path)} ]'


def _make_sshfs_command(host, path, private_key_file, base_dir):
    target = f'{host.username}@{host.hostname}:{path}'
    return [
        'sshfs',
        '-o',
        'ro',
        '-o',
        f'ssh_command=ssh -p {int(host.port or 22)} -i {private_key_file}',
        target,
        base_dir,
    ]


class TransferView(View):
    @auth('exec.transfer.do')
    def get(self, request):
        records = Transfer.objects.filter(user=request.user)
        return json_response([x.to_view() for x in records])

    @auth('exec.transfer.do')
    def post(self, request):
        data = request.POST.get('data')
        form, error = JsonParser(
            Argument('host', required=False),
            Argument('dst_dir', help='请输入目标路径'),
            Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择目标主机'),
            Argument('mfa_ticket', required=False),
        ).parse(data)
        if error is None:
            if not has_host_perm(request.user, form.host_ids):
                return json_response(error='无权访问主机，请联系管理员')
            mfa_error = validate_sensitive_ticket(
                request.user, 'file_transfer', form.pop('mfa_ticket')
            )
            if mfa_error:
                return json_response(error=mfa_error)
            host_id = None
            token = uuid.uuid4().hex
            base_dir = os.path.join(settings.TRANSFER_DIR, token)
            if form.host:
                host_id, path = json.loads(form.host)
                if not path.strip('/'):
                    return json_response(error='请输入正确的数据源路径')
                host = Host.objects.get(pk=host_id)
                with host.get_ssh() as ssh:
                    code, _ = ssh.exec_command_raw(_remote_is_dir_command(path))
                    if code != 0:
                        return json_response(error='数据源路径必须为该主机上已存在的目录')
                os.makedirs(base_dir)
                with tempfile.NamedTemporaryFile(mode='w') as fp:
                    fp.write(host.pkey or AppSetting.get('private_key'))
                    fp.flush()
                    command = _make_sshfs_command(
                        host, path, fp.name, base_dir
                    )
                    task = subprocess.run(
                        command,
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    if task.returncode != 0:
                        _cleanup_transfer_dir(base_dir, mounted=True)
                        return json_response(error=task.stdout.decode())
            else:
                os.makedirs(base_dir)
                index = 0
                while True:
                    file = request.FILES.get(f'file{index}')
                    if not file:
                        break
                    with open(os.path.join(base_dir, file.name), 'wb') as f:
                        for chunk in file.chunks():
                            f.write(chunk)
                    index += 1
            authorize_sensitive_action(request.user, 'file_transfer', token)
            Transfer.objects.create(
                user=request.user,
                digest=token,
                host_id=host_id,
                src_dir=base_dir,
                dst_dir=form.dst_dir,
                host_ids=json.dumps(form.host_ids),
            )
            return json_response(token)
        return json_response(error=error)

    @auth('exec.transfer.do')
    def patch(self, request):
        form, error = JsonParser(
            Argument('token', help='参数错误')
        ).parse(request.body)
        if error is None:
            mfa_error = consume_sensitive_action_authorization(
                request.user, 'file_transfer', form.token
            )
            if mfa_error:
                return json_response(error=mfa_error)
            task = Transfer.objects.get(digest=form.token, user=request.user)
            Thread(target=_dispatch_sync, args=(task,)).start()
        return json_response(error=error)


def _dispatch_sync(task):
    rds = get_redis_connection()
    threads = []
    max_workers = max(10, os.cpu_count() * 5)
    with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for host in Host.objects.filter(id__in=json.loads(task.host_ids)):
            t = executor.submit(_do_sync, rds, task, host)
            t.token = task.digest
            t.key = host.id
            threads.append(t)
        for t in futures.as_completed(threads):
            exc = t.exception()
            if exc:
                rds.publish(
                    t.token,
                    json.dumps({'key': t.key, 'status': -1, 'data': f'\x1b[31mException: {exc}\x1b[0m'})
                )
    _cleanup_transfer_dir(task.src_dir, mounted=bool(task.host_id))
    close_old_connections()


def _cleanup_transfer_dir(path, mounted=False):
    if mounted:
        subprocess.run(
            ['umount', '-f', path],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    shutil.rmtree(path, ignore_errors=True)


def _make_rsync_command(task, host, private_key_file):
    options = '-azv' if task.host_id else '-rzv'
    ssh_command = (
        f'ssh -p {int(host.port or 22)} '
        f'-o StrictHostKeyChecking=no -i {private_key_file}'
    )
    return [
        'rsync',
        options,
        '--protect-args',
        '--progress',
        '-h',
        '-e',
        ssh_command,
        '--',
        f'{task.src_dir}/',
        f'{host.username}@{host.hostname}:{task.dst_dir}',
    ]


def _do_sync(rds, task, host):
    token = task.digest
    rds.publish(token, json.dumps({'key': host.id, 'data': '\r\n\x1b[36m### Executing ...\x1b[0m\r\n'}))
    with tempfile.NamedTemporaryFile(mode='w') as fp:
        fp.write(host.pkey or AppSetting.get('private_key'))
        fp.write('\n')
        fp.flush()

        flag = time.time()
        command = _make_rsync_command(task, host, fp.name)
        task = subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        message = b''
        while True:
            output = task.stdout.read(1)
            if not output:
                break
            if output in (b'\r', b'\n'):
                message += b'\r\n' if output == b'\n' else b'\r'
                message = str_decode(message)
                if 'rsync: command not found' in message:
                    data = '\r\n\x1b[31m检测到该主机未安装rsync，可通过批量执行/执行任务模块进行以下命令批量安装\x1b[0m'
                    data += '\r\nCentos/Redhat: yum install -y rsync'
                    data += '\r\nUbuntu/Debian: apt install -y rsync'
                    rds.publish(token, json.dumps({'key': host.id, 'data': data}))
                    break
                rds.publish(token, json.dumps({'key': host.id, 'data': message}))
                message = b''
            else:
                message += output
        status = task.wait()
        if status == 0:
            human_time = human_seconds_time(time.time() - flag)
            rds.publish(token, json.dumps({'key': host.id, 'data': f'\r\n\x1b[32m** 分发完成，总耗时：{human_time} **\x1b[0m'}))
        rds.publish(token, json.dumps({'key': host.id, 'status': task.wait()}))
