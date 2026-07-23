# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.core.cache import cache
from django.conf import settings
from libs.mixins import AdminView, View
from libs import JsonParser, Argument, human_datetime, json_response
from libs.utils import get_request_real_ip, generate_random_str
from libs.push import send_login_code
from apps.account.models import User, Role, History
from apps.account.mfa import (
    MFASecretError,
    bind_totp,
    clear_mfa_failures,
    clear_totp_setup,
    create_totp_setup,
    get_sensitive_scope,
    get_pending_totp_secret,
    issue_sensitive_ticket,
    is_mfa_attempt_locked,
    register_mfa_failure,
    reset_user_totp,
    verify_user_totp,
)
from apps.setting.utils import AppSetting
from apps.account.utils import verify_password
from libs.ldap import LDAP
from functools import partial
import user_agents
import ipaddress
import time
import uuid
import json
import secrets


class UserView(AdminView):
    def get(self, request):
        users = []
        for u in User.objects.filter(deleted_by_id__isnull=True):
            tmp = u.to_dict(excludes=('access_token', 'password_hash', 'mfa_secret', 'mfa_last_counter'))
            tmp['role_ids'] = [x.id for x in u.roles.all()]
            tmp['password'] = '******'
            tmp['mfa_bound'] = u.mfa_bound
            users.append(tmp)
        return json_response(users)

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('username', help='请输入登录名'),
            Argument('password', help='请输入密码'),
            Argument('nickname', help='请输入姓名'),
            Argument('role_ids', type=list, default=[]),
            Argument('wx_token', required=False),
        ).parse(request.body)
        if error is None:
            user = User.objects.filter(username=form.username, deleted_by_id__isnull=True).first()
            if user and (not form.id or form.id != user.id):
                return json_response(error=f'已存在登录名为【{form.username}】的用户')

            role_ids, password = form.pop('role_ids'), form.pop('password')
            if form.id:
                user = User.objects.get(pk=form.id)
                user.update_by_dict(form)
            else:
                if not verify_password(password):
                    return json_response(error='请设置至少8位包含数字、小写和大写字母的新密码')
                user = User.objects.create(
                    password_hash=User.make_password(password),
                    created_by=request.user,
                    **form
                )
            user.roles.set(role_ids)
            user.set_perms_cache()
        return json_response(error=error)

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('password', required=False),
            Argument('is_active', type=bool, required=False),
            Argument('reset_mfa', type=bool, required=False),
        ).parse(request.body)
        if error is None:
            user = User.objects.get(pk=form.id)
            if form.password:
                if not verify_password(form.password):
                    return json_response(error='请设置至少8位包含数字、小写和大写字母的新密码')
                user.token_expired = 0
                user.password_hash = User.make_password(form.pop('password'))
            if form.is_active is not None:
                user.is_active = form.is_active
                cache.delete(user.username)
            if form.reset_mfa:
                reset_user_totp(user)
            user.save()
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            user = User.objects.filter(pk=form.id).first()
            if user:
                if user.type == 'ldap':
                    return json_response(error='ldap账户无法删除，请使用禁用功能来禁止该账户访问系统')
                if user.id == request.user.id:
                    return json_response(error='无法删除当前登录账户')
                user.is_active = False
                user.is_supper = False
                user.access_token = ''
                user.token_expired = 0
                user.deleted_at = human_datetime()
                user.deleted_by = request.user
                user.roles.clear()
                user.set_perms_cache()
                user.save()
        return json_response(error=error)


class RoleView(AdminView):
    def get(self, request):
        roles = Role.objects.all()
        return json_response(roles)

    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入角色名称'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                Role.objects.filter(pk=form.id).update(**form)
            else:
                Role.objects.create(created_by=request.user, **form)
        return json_response(error=error)

    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('page_perms', type=dict, required=False),
            Argument('deploy_perms', type=dict, required=False),
            Argument('group_perms', type=list, required=False)
        ).parse(request.body)
        if error is None:
            role = Role.objects.filter(pk=form.pop('id')).first()
            if not role:
                return json_response(error='未找到指定角色')
            if form.page_perms is not None:
                role.page_perms = json.dumps(form.page_perms)
                role.clear_perms_cache()
            if form.deploy_perms is not None:
                role.deploy_perms = json.dumps(form.deploy_perms)
            if form.group_perms is not None:
                role.group_perms = json.dumps(form.group_perms)
            role.user_set.update(token_expired=0)
            role.save()
        return json_response(error=error)

    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误')
        ).parse(request.GET)
        if error is None:
            role = Role.objects.get(pk=form.id)
            if role.user_set.exists():
                return json_response(error='已有用户使用了该角色，请解除关联后再尝试删除')
            role.delete()
        return json_response(error=error)


class SelfView(View):
    def get(self, request):
        data = request.user.to_dict(selects=('nickname', 'wx_token'))
        data['mfa_bound'] = request.user.mfa_bound
        return json_response(data)

    def patch(self, request):
        form, error = JsonParser(
            Argument('old_password', required=False),
            Argument('new_password', required=False),
            Argument('nickname', required=False, help='请输入昵称'),
            Argument('wx_token', required=False),
        ).parse(request.body)
        if error is None:
            if form.old_password and form.new_password:
                if request.user.type == 'ldap':
                    return json_response(error='LDAP账户无法修改密码')

                if not verify_password(form.new_password):
                    return json_response(error='请设置至少8位包含数字、小写和大写字母的新密码')

                if request.user.verify_password(form.old_password):
                    request.user.password_hash = User.make_password(form.new_password)
                    request.user.token_expired = 0
                    request.user.save()
                    return json_response()
                else:
                    return json_response(error='原密码错误，请重新输入')
            if form.nickname is not None:
                request.user.nickname = form.nickname
            if form.wx_token is not None:
                request.user.wx_token = form.wx_token
            request.user.save()
        return json_response(error=error)


class UserMFAView(View):
    def get(self, request):
        if request.user.mfa_bound:
            return json_response(error='当前账户已绑定身份认证器')
        return json_response(create_totp_setup(request.user))

    def post(self, request):
        form, error = JsonParser(
            Argument('action', filter=lambda x: x in ('bind', 'unbind'), help='参数错误'),
            Argument('code', help='请输入6位验证码'),
            Argument('setup_token', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if is_mfa_attempt_locked(request.user):
            return json_response(error='验证码错误次数过多，请5分钟后重试')

        try:
            if form.action == 'bind':
                if request.user.mfa_bound:
                    return json_response(error='当前账户已绑定身份认证器')
                secret = get_pending_totp_secret(request.user, form.setup_token)
                if not secret:
                    return json_response(error='绑定信息已失效，请重新生成二维码')
                if not bind_totp(request.user, secret, form.code):
                    register_mfa_failure(request.user)
                    return json_response(error='验证码错误，请确认服务器时间与手机时间一致')
                clear_totp_setup(form.setup_token)
            else:
                if not request.user.mfa_bound:
                    return json_response({'mfa_bound': False})
                if not verify_user_totp(request.user, form.code):
                    register_mfa_failure(request.user)
                    return json_response(error='验证码错误，请重新输入')
                reset_user_totp(request.user)
        except MFASecretError as exc:
            return json_response(error=str(exc))

        clear_mfa_failures(request.user)
        return json_response({'mfa_bound': request.user.mfa_bound})


class SensitiveMFAView(View):
    def get(self, request):
        form, error = JsonParser(
            Argument('scope', help='参数错误'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        method, error = _get_sensitive_mfa_method(request.user, form.scope)
        if error:
            return json_response(error=error)

        if method == 'push':
            cooldown_key = _sensitive_push_cooldown_key(request.user, form.scope)
            if cache.get(cooldown_key):
                return json_response({'method': method, 'retry_after': 60})
            code = ''.join(secrets.choice('0123456789') for _ in range(6))
            spug_push_key = AppSetting.get_default('spug_push_key')
            send_login_code(spug_push_key, request.user.wx_token, code)
            cache.set(_sensitive_push_code_key(request.user, form.scope), code, 300)
            cache.set(cooldown_key, 1, 60)
        return json_response({'method': method, 'retry_after': 60 if method == 'push' else 0})

    def post(self, request):
        form, error = JsonParser(
            Argument('scope', help='参数错误'),
            Argument('code', help='请输入6位验证码'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        method, error = _get_sensitive_mfa_method(request.user, form.scope)
        if error:
            return json_response(error=error)
        if is_mfa_attempt_locked(request.user):
            return json_response(error='验证码错误次数过多，请5分钟后重试')

        try:
            if method == 'totp':
                verified = verify_user_totp(request.user, form.code)
            else:
                key = _sensitive_push_code_key(request.user, form.scope)
                expected = cache.get(key)
                verified = bool(expected and secrets.compare_digest(expected, form.code))
                if verified:
                    cache.delete(key)
        except MFASecretError as exc:
            return json_response(error=str(exc))

        if not verified:
            register_mfa_failure(request.user)
            return json_response(error='验证码错误，请重新输入')
        clear_mfa_failures(request.user)
        ticket, expires_in = issue_sensitive_ticket(request.user, form.scope)
        return json_response({'ticket': ticket, 'expires_in': expires_in})


def _get_sensitive_mfa_method(user, scope):
    scope_config = get_sensitive_scope(scope)
    if not scope_config:
        return None, '不支持的敏感操作类型'
    if not user.has_perms(scope_config['permissions']):
        return None, '权限拒绝'
    mfa = AppSetting.get_default('MFA', {'enable': False}) or {}
    if not mfa.get('enable'):
        return None, '系统未开启MFA认证，禁止使用该功能'
    method = mfa.get('method', 'push')
    if method == 'totp':
        if not user.mfa_bound:
            return None, '当前账户未绑定身份认证器，请先在个人中心完成绑定'
    else:
        if not user.wx_token:
            return None, '当前账户未配置推送MFA标识，请联系管理员'
        if not AppSetting.get_default('spug_push_key'):
            return None, '系统未配置推送服务，请联系管理员'
        method = 'push'
    return method, None


def _sensitive_push_code_key(user, scope):
    return f'mfa:sensitive:push:{user.id}:{scope}'


def _sensitive_push_cooldown_key(user, scope):
    return f'mfa:sensitive:push:cooldown:{user.id}:{scope}'


def login(request):
    form, error = JsonParser(
        Argument('username', help='请输入用户名'),
        Argument('password', help='请输入密码'),
        Argument('captcha', required=False),
        Argument('mfa_setup_token', required=False),
        Argument('type', required=False)
    ).parse(request.body)
    if error is None:
        handle_response = partial(handle_login_record, request, form.username, form.type)
        user = User.objects.filter(username=form.username, type=form.type).first()
        if user and not user.is_active:
            return handle_response(error="账户已被系统禁用")
        if form.type == 'ldap':
            config = AppSetting.get_default('ldap_service')
            if not config:
                return handle_response(error='请在系统设置中配置LDAP后再尝试通过该方式登录')
            ldap = LDAP(**config)
            is_success, message = ldap.valid_user(form.username, form.password)
            if is_success:
                if not user:
                    user = User.objects.create(username=form.username, nickname=form.username, type=form.type)
                return handle_user_info(
                    handle_response, request, user, form.captcha, form.mfa_setup_token
                )
            elif message:
                return handle_response(error=message)
        else:
            if user and user.deleted_by is None:
                if user.verify_password(form.password):
                    return handle_user_info(
                        handle_response, request, user, form.captcha, form.mfa_setup_token
                    )

        value = cache.get_or_set(form.username, 0, 86400)
        if value >= 3:
            if user and user.is_active:
                user.is_active = False
                user.save()
            return handle_response(error='账户已被系统禁用')
        cache.set(form.username, value + 1, 86400)
        return handle_response(error="用户名或密码错误，连续多次错误账户将会被禁用")
    return json_response(error=error)


def handle_login_record(request, username, login_type, error=None):
    x_real_ip = get_request_real_ip(request.headers)
    user_agent = user_agents.parse(request.headers.get('User-Agent'))
    History.objects.create(
        username=username,
        type=login_type,
        ip=x_real_ip,
        agent=user_agent,
        is_success=False if error else True,
        message=error
    )
    if error:
        return json_response(error=error)


def handle_user_info(handle_response, request, user, captcha, mfa_setup_token=None):
    cache.delete(user.username)
    mfa = AppSetting.get_default('MFA', {'enable': False})
    if mfa.get('enable'):
        method = mfa.get('method', 'push')
        if method == 'totp':
            response = _handle_totp_login(
                handle_response, user, captcha, mfa_setup_token
            )
            if response is not None:
                return response
        else:
            key = f'{user.username}:code'
            if captcha:
                code = cache.get(key)
                if not code:
                    return handle_response(error='验证码已失效，请重新获取')
                if code != captcha:
                    ttl = cache.ttl(key)
                    cache.expire(key, ttl - 100)
                    return handle_response(error='验证码错误')
                cache.delete(key)
            else:
                if not user.wx_token:
                    return handle_response(error='已启用登录双重认证，但您的账户未配置推送标识，请联系管理员')
                spug_push_key = AppSetting.get_default('spug_push_key')
                if not spug_push_key:
                    return handle_response(error='已启用登录双重认证，但系统未配置推送服务，请联系管理员')
                code = generate_random_str(6)
                send_login_code(spug_push_key, user.wx_token, code)
                cache.set(key, code, 300)
                return json_response({'required_mfa': True, 'mfa_method': 'push'})

    handle_response()
    x_real_ip = get_request_real_ip(request.headers)
    token_isvalid = user.access_token and len(user.access_token) == 32 and user.token_expired >= time.time()
    user.access_token = user.access_token if token_isvalid else uuid.uuid4().hex
    user.token_expired = time.time() + settings.TOKEN_TTL
    user.last_login = human_datetime()
    user.last_ip = x_real_ip
    user.save()
    verify_ip = AppSetting.get_default('verify_ip', True)
    return json_response({
        'id': user.id,
        'access_token': user.access_token,
        'nickname': user.nickname,
        'is_supper': user.is_supper,
        'has_real_ip': x_real_ip and ipaddress.ip_address(x_real_ip).is_global if verify_ip else True,
        'permissions': [] if user.is_supper else list(user.page_perms)
    })


def _handle_totp_login(handle_response, user, code, setup_token):
    if is_mfa_attempt_locked(user):
        return handle_response(error='验证码错误次数过多，请5分钟后重试')
    if not code:
        data = {'required_mfa': True, 'mfa_method': 'totp'}
        if not user.mfa_bound:
            data.update(create_totp_setup(user))
            data['mfa_setup_required'] = True
        return json_response(data)

    try:
        if user.mfa_bound:
            verified = verify_user_totp(user, code)
        else:
            secret = get_pending_totp_secret(user, setup_token)
            if not secret:
                return handle_response(error='绑定信息已失效，请重新登录生成二维码')
            verified = bind_totp(user, secret, code)
            if verified:
                clear_totp_setup(setup_token)
    except MFASecretError as exc:
        return handle_response(error=str(exc))

    if not verified:
        register_mfa_failure(user)
        return handle_response(error='验证码错误，请确认服务器时间与手机时间一致')
    clear_mfa_failures(user)
    return None


def logout(request):
    request.user.token_expired = 0
    request.user.save()
    return json_response()
