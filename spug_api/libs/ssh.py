# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from paramiko.client import SSHClient, AutoAddPolicy
from paramiko.rsakey import RSAKey
from paramiko.auth_handler import AuthHandler
from paramiko.ssh_exception import AuthenticationException, SSHException
from paramiko.py3compat import b, u
from io import StringIO
from uuid import uuid4
import socket
import time
import re
import shlex


def _is_legacy_openssh(remote_version):
    match = re.search(r'-OpenSSH_(\d+)(?:\.(\d+))?', remote_version)
    if not match:
        return False
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major < 7 or (major == 7 and minor <= 7)


def _finalize_pubkey_algorithm(self, key_type):
    if "rsa" not in key_type:
        return key_type
    if _is_legacy_openssh(self.transport.remote_version):
        pubkey_algo = "ssh-rsa"
        if key_type.endswith("-cert-v01@openssh.com"):
            pubkey_algo += "-cert-v01@openssh.com"

        self.transport._agreed_pubkey_algorithm = pubkey_algo
        return pubkey_algo
    my_algos = [x for x in self.transport.preferred_pubkeys if "rsa" in x]
    if not my_algos:
        raise SSHException(
            "An RSA key was specified, but no RSA pubkey algorithms are configured!"  # noqa
        )
    server_algo_str = u(
        self.transport.server_extensions.get("server-sig-algs", b(""))
    )
    if server_algo_str:
        server_algos = server_algo_str.split(",")
        agreement = list(filter(server_algos.__contains__, my_algos))
        if agreement:
            pubkey_algo = agreement[0]
        else:
            err = "Unable to agree on a pubkey algorithm for signing a {!r} key!"  # noqa
            raise AuthenticationException(err.format(key_type))
    else:
        # 现代 OpenSSH 默认禁用 SHA-1 的 ssh-rsa 签名，应优先使用 Paramiko
        # 的 rsa-sha2 算法；旧版 OpenSSH 已在上面的版本分支单独兼容。
        pubkey_algo = my_algos[0]
    if key_type.endswith("-cert-v01@openssh.com"):
        pubkey_algo += "-cert-v01@openssh.com"
    self.transport._agreed_pubkey_algorithm = pubkey_algo
    return pubkey_algo


AuthHandler._finalize_pubkey_algorithm = _finalize_pubkey_algorithm


class SSH:
    def __init__(self, hostname, port=22, username='root', pkey=None, password=None, default_env=None,
                 connect_timeout=10, term=None, keepalive_interval=60, command_timeout=300):
        self.stdout = None
        self.client = None
        self.channel = None
        self.sftp = None
        self.exec_file = None
        self.term = term or {}
        self.eof = 'Spug EOF 2108111926'
        self.default_env = default_env
        self.keepalive_interval = keepalive_interval
        self.command_timeout = command_timeout
        self.regex = re.compile(r'Spug EOF 2108111926 (-?\d+)[\r\n]?')
        self.arguments = {
            'hostname': hostname,
            'port': port,
            'username': username,
            'password': password,
            'pkey': RSAKey.from_private_key(StringIO(pkey)) if isinstance(pkey, str) else pkey,
            'timeout': connect_timeout,
            'allow_agent': False,
            'look_for_keys': False,
            'banner_timeout': 30
        }

    @staticmethod
    def generate_key():
        key_obj = StringIO()
        key = RSAKey.generate(2048)
        key.write_private_key(key_obj)
        return key_obj.getvalue(), 'ssh-rsa ' + key.get_base64()

    def get_client(self):
        if self.client is not None:
            return self.client
        self.client = SSHClient()
        self.client.set_missing_host_key_policy(AutoAddPolicy)
        self.client.connect(**self.arguments)
        transport = self.client.get_transport()
        if transport:
            transport.set_keepalive(self.keepalive_interval)
        return self.client

    def ping(self):
        return True

    def reconnect(self):
        """关闭并重新建立 SSH 连接，重置 channel/sftp 状态。"""
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.client = None
        self.channel = None
        self.sftp = None
        self.exec_file = None
        self.stdout = None
        self.get_client()
        transport = self.client.get_transport()
        if transport and 'windows' in transport.remote_version.lower():
            self.exec_command = self.exec_command_raw
            self.exec_command_with_stream = self._win_exec_command_with_stream

    def is_connected(self):
        """检查 SSH 连接是否仍然活跃。"""
        try:
            transport = self.client.get_transport() if self.client else None
            return transport is not None and transport.is_active()
        except Exception:
            return False

    def add_public_key(self, public_key):
        public_key = public_key.strip() if public_key else ''
        if not public_key:
            raise ValueError('SSH 公钥不能为空')
        quoted_public_key = shlex.quote(public_key)
        command = (
            'umask 077 && '
            'mkdir -p "$HOME/.ssh" && '
            'chmod 700 "$HOME/.ssh" && '
            'touch "$HOME/.ssh/authorized_keys" && '
            'chmod 600 "$HOME/.ssh/authorized_keys" && '
            f'(grep -qxF {quoted_public_key} "$HOME/.ssh/authorized_keys" || '
            f'printf \'\\n%s\\n\' {quoted_public_key} >> "$HOME/.ssh/authorized_keys")'
        )
        exit_code, out = self.exec_command_raw(command)
        if exit_code != 0:
            raise Exception(f'写入 SSH 公钥失败: {out}')

    def exec_command_raw(self, command, environment=None):
        channel = self.client.get_transport().open_session()
        channel.settimeout(self.command_timeout)
        if environment:
            channel.update_environment(environment)
        channel.set_combine_stderr(True)
        channel.exec_command(command)
        # 轮询等待退出状态，避免连接断开时无限阻塞
        start_time = time.time()
        while not channel.exit_status_ready():
            if time.time() - start_time > self.command_timeout:
                if not self.is_connected():
                    raise SSHException('SSH connection lost while waiting for command to complete')
                # 连接仍然活跃，命令还在执行，重置计时器
                start_time = time.time()
            time.sleep(0.5)
        code, output = channel.recv_exit_status(), channel.recv(-1)
        return code, self._decode(output)

    def exec_command(self, command, environment=None):
        channel = self._get_channel()
        command = self._handle_command(command, environment)
        channel.sendall(command)
        out, exit_code = '', -1
        for line in self.stdout:
            match = self.regex.search(line)
            if match:
                exit_code = int(match.group(1))
                line = line[:match.start()]
                out += line
                break
            out += line
        return exit_code, out

    def _win_exec_command_with_stream(self, command, environment=None):
        channel = self.client.get_transport().open_session()
        if environment:
            channel.update_environment(environment)
        channel.set_combine_stderr(True)
        channel.get_pty(width=102)
        channel.exec_command(command)
        stdout = channel.makefile("rb", -1)
        out = stdout.readline()
        while out:
            yield channel.exit_status, self._decode(out)
            out = stdout.readline()
        yield channel.recv_exit_status(), self._decode(out)

    def exec_command_with_stream(self, command, environment=None):
        channel = self._get_channel()
        command = self._handle_command(command, environment)
        channel.settimeout(self.command_timeout)
        channel.sendall(command)
        exit_code, line = -1, ''
        while True:
            try:
                line = self._decode(channel.recv(8196))
            except socket.timeout:
                # recv 超时，检查连接是否仍然活跃
                if not self.is_connected():
                    raise SSHException(f'SSH connection lost (no data received for {self.command_timeout}s)')
                # 连接仍然活跃，命令还在执行（只是暂时没有输出），继续等待
                continue
            if not line:
                if not self.is_connected():
                    raise SSHException('SSH connection lost unexpectedly')
                break
            match = self.regex.search(line)
            if match:
                exit_code = int(match.group(1))
                line = line[:match.start()]
                break
            yield exit_code, line
        yield exit_code, line

    def put_file(self, local_path, remote_path, callback=None):
        sftp = self._get_sftp()
        sftp.put(local_path, remote_path, callback=callback, confirm=False)

    def put_file_by_fl(self, fl, remote_path, callback=None):
        sftp = self._get_sftp()
        sftp.putfo(fl, remote_path, callback=callback, confirm=False)

    def list_dir_attr(self, path):
        sftp = self._get_sftp()
        return sftp.listdir_attr(path)

    def sftp_stat(self, path):
        sftp = self._get_sftp()
        return sftp.stat(path)

    def remove_file(self, path):
        sftp = self._get_sftp()
        sftp.remove(path)

    def _get_channel(self):
        if self.channel:
            return self.channel

        counter = 0
        self.channel = self.client.invoke_shell(**self.term)
        command = '[ -n "$BASH_VERSION" ] && set +o history\n'
        command += '[ -n "$ZSH_VERSION" ] && set +o zle && set -o no_nomatch\n'
        command += 'export PS1= && stty -echo\n'
        command = self._handle_command(command, self.default_env)
        self.channel.sendall(command)
        out = ''
        while True:
            if self.channel.recv_ready():
                out += self._decode(self.channel.recv(8196))
                if self.regex.search(out):
                    self.stdout = self.channel.makefile('r')
                    break
            elif counter >= 100:
                self.client.close()
                raise Exception('Wait spug response timeout')
            else:
                counter += 1
                time.sleep(0.1)
        return self.channel

    def _get_sftp(self):
        if self.sftp:
            return self.sftp

        self.sftp = self.client.open_sftp()
        return self.sftp

    def _make_env_command(self, environment):
        if not environment:
            return None
        str_envs = []
        for k, v in environment.items():
            k = k.replace('-', '_')
            if isinstance(v, str):
                v = v.replace("'", "'\"'\"'")
            str_envs.append(f"{k}='{v}'")
        str_envs = ' '.join(str_envs)
        return f'export {str_envs}'

    def _handle_command(self, command, environment):
        new_command = commands = ''
        if not self.exec_file:
            self.exec_file = f'/tmp/spug.{uuid4().hex}'
            commands += f'trap \'rm -f {self.exec_file}\' EXIT\n'

        env_command = self._make_env_command(environment)
        if env_command:
            new_command += f'{env_command}\n'
        new_command += command
        new_command += f'\necho {self.eof} $?\n'
        self.put_file_by_fl(StringIO(new_command), self.exec_file)
        commands += f'. {self.exec_file}\n'
        return commands

    def _decode(self, content):
        try:
            content = content.decode()
        except UnicodeDecodeError:
            content = content.decode(encoding='GBK', errors='ignore')
        return content

    def __enter__(self):
        self.get_client()
        transport = self.client.get_transport()
        if 'windows' in transport.remote_version.lower():
            self.exec_command = self.exec_command_raw
            self.exec_command_with_stream = self._win_exec_command_with_stream
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
        self.client = None
