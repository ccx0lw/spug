# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '系统设置'

    def add_arguments(self, parser):
        parser.add_argument('target', type=str, help='设置对象')
        parser.add_argument('value', type=str, help='设置值')

    def echo_success(self, msg):
        self.stdout.write(self.style.SUCCESS(msg))

    def echo_error(self, msg):
        self.stderr.write(self.style.ERROR(msg))

    def print_help(self, *args):
        message = '''
        系统设置命令用法：
            MFA 已改为账号独立设置，请由账号在个人中心开启或关闭。
        '''
        self.stdout.write(message)

    def handle(self, *args, **options):
        target = options['target']
        if target == 'mfa':
            self.echo_error('MFA已改为账号独立设置，不能通过系统级命令修改')
        else:
            self.echo_error('未识别的操作')
            self.print_help()
