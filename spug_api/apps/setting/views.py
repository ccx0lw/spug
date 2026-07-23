# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import django
from django.conf import settings
from libs import JsonParser, Argument, json_response, auth
from libs.mail import Mail
from libs.push import get_balance
from libs.mixins import AdminView
from apps.setting.utils import AppSetting
from apps.setting.models import Setting, KEYS_DEFAULT
from copy import deepcopy
import platform
import ldap


class SettingView(AdminView):
    def get(self, request):
        response = deepcopy(KEYS_DEFAULT)
        for item in Setting.objects.all():
            if item.key == 'spug_push_key':
                response[item.key] = f'{item.real_val[:8]}********{item.real_val[-8:]}'
            elif item.key == 'MFA':
                continue
            else:
                response[item.key] = item.real_val
        return json_response(response)

    def post(self, request):
        form, error = JsonParser(
            Argument('data', type=list, help='缺少必要的参数')
        ).parse(request.body)
        if error is None:
            for item in form.data:
                AppSetting.set(**item)
        return json_response(error=error)


@auth('admin')
def ldap_test(request):
    form, error = JsonParser(
        Argument('server'),
        Argument('port', type=int),
        Argument('admin_dn'),
        Argument('password'),
    ).parse(request.body)
    if error is None:
        try:
            con = ldap.initialize("ldap://{0}:{1}".format(form.server, form.port), bytes_mode=False)
            con.simple_bind_s(form.admin_dn, form.password)
            return json_response()
        except Exception as e:
            error = eval(str(e))
            return json_response(error=error['desc'])
    return json_response(error=error)


@auth('admin')
def email_test(request):
    form, error = JsonParser(
        Argument('server', help='请输入邮件服务地址'),
        Argument('port', type=int, help='请输入邮件服务端口号'),
        Argument('username', help='请输入邮箱账号'),
        Argument('password', help='请输入密码/授权码'),
    ).parse(request.body)
    if error is None:
        try:
            mail = Mail(**form)
            server = mail.get_server()
            server.quit()
            return json_response()
        except Exception as e:
            error = f'{e}'
    return json_response(error=error)


@auth('admin')
def get_about(request):
    return json_response({
        'python_version': platform.python_version(),
        'system_version': platform.platform(),
        'spug_version': settings.SPUG_VERSION,
        'django_version': django.get_version()
    })


@auth('admin')
def handle_push_bind(request):
    form, error = JsonParser(
        Argument('spug_push_key', required=False),
    ).parse(request.body)
    if error is None:
        if not form.spug_push_key:
            AppSetting.delete('spug_push_key')
            return json_response()

        try:
            res = get_balance(form.spug_push_key)
        except Exception as e:
            return json_response(error=f'绑定失败：{e}')

        AppSetting.set('spug_push_key', form.spug_push_key)
        return json_response(res)
    return json_response(error=error)


@auth('admin')
def handle_push_balance(request):
    token = AppSetting.get_default('spug_push_key')
    if not token:
        return json_response(error='请先配置推送服务绑定账户')
    res = get_balance(token)
    return json_response(res)
