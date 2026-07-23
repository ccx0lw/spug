# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import base64
import hashlib
import hmac
import re
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from apps.account.models import User


TOTP_INTERVAL = 30
TOTP_SETUP_TTL = 600
TOTP_MAX_FAILURES = 5
TOTP_FAILURE_TTL = 300
SENSITIVE_SCOPES = {
    'host_console': {
        'permissions': ('host.console.view', 'host.console.list'),
        'ttl': getattr(settings, 'TOKEN_TTL', 8 * 3600),
        'reusable': True,
    },
    'exec_task': {
        'permissions': ('exec.task.do',),
        'ttl': 120,
        'reusable': False,
    },
    'file_transfer': {
        'permissions': ('exec.transfer.do',),
        'ttl': 900,
        'reusable': False,
    },
}


class MFASecretError(Exception):
    pass


def _get_fernet():
    source = getattr(settings, 'MFA_ENCRYPTION_KEY', settings.SECRET_KEY)
    key = hashlib.sha256(source.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_totp_secret(secret):
    return _get_fernet().encrypt(secret.encode('utf-8')).decode('utf-8')


def decrypt_totp_secret(encrypted_secret):
    try:
        return _get_fernet().decrypt(encrypted_secret.encode('utf-8')).decode('utf-8')
    except (InvalidToken, AttributeError, UnicodeDecodeError) as exc:
        raise MFASecretError('MFA密钥无法解密，请联系管理员重置认证器') from exc


def _build_qr_data_uri(uri):
    factory = qrcode.image.svg.SvgPathFillImage
    image = qrcode.make(uri, image_factory=factory)
    svg = image.to_string(encoding='utf-8')
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii')


def create_totp_setup(user):
    secret = pyotp.random_base32()
    issuer = getattr(settings, 'MFA_ISSUER', 'Spug')
    uri = pyotp.TOTP(secret, interval=TOTP_INTERVAL).provisioning_uri(
        name=user.username,
        issuer_name=issuer,
    )
    setup_token = secrets.token_urlsafe(32)
    cache.set(
        f'mfa:setup:{setup_token}',
        {'user_id': user.id, 'secret': encrypt_totp_secret(secret)},
        TOTP_SETUP_TTL,
    )
    return {
        'setup_token': setup_token,
        'secret': secret,
        'qr_code': _build_qr_data_uri(uri),
    }


def get_pending_totp_secret(user, setup_token):
    if not setup_token:
        return None
    payload = cache.get(f'mfa:setup:{setup_token}')
    if not payload or payload.get('user_id') != user.id:
        return None
    return decrypt_totp_secret(payload.get('secret'))


def clear_totp_setup(setup_token):
    if setup_token:
        cache.delete(f'mfa:setup:{setup_token}')


def match_totp_counter(secret, code, timestamp=None):
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        return None
    current_counter = int(timestamp or time.time()) // TOTP_INTERVAL
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    for offset in (0, -1, 1):
        counter = current_counter + offset
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None


def bind_totp(user, secret, code):
    counter = match_totp_counter(secret, code)
    if counter is None:
        return False
    user.mfa_secret = encrypt_totp_secret(secret)
    user.mfa_last_counter = counter
    user.mfa_enabled = True
    user.save(update_fields=('mfa_secret', 'mfa_last_counter', 'mfa_enabled'))
    return True


def verify_user_totp(user, code):
    if not user.mfa_secret:
        return False
    secret = decrypt_totp_secret(user.mfa_secret)
    counter = match_totp_counter(secret, code)
    if counter is None:
        return False
    updated = User.objects.filter(pk=user.pk).filter(
        Q(mfa_last_counter__isnull=True) | Q(mfa_last_counter__lt=counter)
    ).update(mfa_last_counter=counter)
    if updated:
        user.mfa_last_counter = counter
    return bool(updated)


def reset_user_totp(user):
    user.mfa_secret = None
    user.mfa_last_counter = None
    user.mfa_enabled = False
    user.save(update_fields=('mfa_secret', 'mfa_last_counter', 'mfa_enabled'))


def set_user_mfa_enabled(user, enabled):
    if enabled and not user.mfa_secret:
        raise MFASecretError('当前账户未绑定身份认证器')
    if enabled:
        secret = decrypt_totp_secret(user.mfa_secret)
        user.mfa_secret = encrypt_totp_secret(secret)
    user.mfa_enabled = enabled
    fields = ['mfa_enabled']
    if enabled:
        fields.append('mfa_secret')
    user.save(update_fields=fields)


def _failure_key(user):
    return f'mfa:failures:{user.id}'


def is_mfa_attempt_locked(user):
    return int(cache.get(_failure_key(user), 0)) >= TOTP_MAX_FAILURES


def register_mfa_failure(user):
    key = _failure_key(user)
    if cache.add(key, 1, TOTP_FAILURE_TTL):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, TOTP_FAILURE_TTL)
        return 1


def clear_mfa_failures(user):
    cache.delete(_failure_key(user))


def get_sensitive_scope(scope):
    return SENSITIVE_SCOPES.get(scope)


def issue_sensitive_ticket(user, scope):
    config = get_sensitive_scope(scope)
    if not config:
        raise ValueError('不支持的敏感操作类型')
    state_error = _user_mfa_state_error(user)
    if state_error:
        raise ValueError(state_error)
    ticket = secrets.token_urlsafe(32)
    cache.set(
        f'mfa:sensitive:ticket:{ticket}',
        {
            'user_id': user.id,
            'scope': scope,
            'reusable': config['reusable'],
            'credential': _sensitive_credential_fingerprint(user),
        },
        config['ttl'],
    )
    return ticket, config['ttl']


def authorize_sensitive_action(user, scope, action_token):
    config = get_sensitive_scope(scope)
    if not config:
        raise ValueError('不支持的敏感操作类型')
    state_error = _user_mfa_state_error(user)
    if state_error:
        raise ValueError(state_error)
    cache.set(
        _sensitive_action_key(user, scope, action_token),
        {
            'user_id': user.id,
            'scope': scope,
            'credential': _sensitive_credential_fingerprint(user),
        },
        config['ttl'],
    )


def consume_sensitive_action_authorization(user, scope, action_token):
    state_error = _user_mfa_state_error(user)
    if state_error:
        return state_error
    if not get_sensitive_scope(scope):
        return '不支持的敏感操作类型'
    if not action_token:
        return 'MFA操作授权已失效，请重新发起操作'

    key = _sensitive_action_key(user, scope, action_token)
    lock_key = f'{key}:consume'
    if not cache.add(lock_key, 1, 5):
        return 'MFA操作授权已被使用，请重新发起操作'
    try:
        payload = cache.get(key)
        if not payload or payload.get('user_id') != user.id \
                or payload.get('scope') != scope \
                or payload.get('credential') != _sensitive_credential_fingerprint(user):
            return 'MFA操作授权已失效或已被使用，请重新发起操作'
        cache.delete(key)
        return None
    finally:
        cache.delete(lock_key)


def validate_sensitive_ticket(user, scope, ticket):
    state_error = _user_mfa_state_error(user)
    if state_error:
        return state_error
    config = get_sensitive_scope(scope)
    if not config:
        return '不支持的敏感操作类型'
    if not ticket:
        return '本操作必须先通过MFA验证'

    key = f'mfa:sensitive:ticket:{ticket}'
    if config['reusable']:
        payload = cache.get(key)
        if not _is_valid_sensitive_ticket(payload, user, scope, config):
            return 'MFA授权已失效，请重新验证'
        return None

    lock_key = f'{key}:consume'
    if not cache.add(lock_key, 1, 5):
        return 'MFA授权已被使用，请重新验证'
    try:
        payload = cache.get(key)
        if not _is_valid_sensitive_ticket(payload, user, scope, config):
            return 'MFA授权已失效或已被使用，请重新验证'
        cache.delete(key)
        return None
    finally:
        cache.delete(lock_key)


def _is_valid_sensitive_ticket(payload, user, scope, config):
    return bool(
        payload
        and payload.get('user_id') == user.id
        and payload.get('scope') == scope
        and payload.get('reusable') == config['reusable']
        and payload.get('credential') == _sensitive_credential_fingerprint(user)
    )


def _sensitive_credential_fingerprint(user):
    value = f'totp:{user.mfa_secret or ""}'.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def _sensitive_action_key(user, scope, action_token):
    return f'mfa:sensitive:action:{user.id}:{scope}:{action_token}'


def _user_mfa_state_error(user):
    if not user.mfa_enabled:
        return '当前账户未开启MFA认证，禁止使用该功能'
    if not user.mfa_bound:
        return '当前账户未绑定身份认证器，请先在个人中心完成绑定'
    return None
