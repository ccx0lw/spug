import json
from unittest.mock import patch

import pyotp
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from apps.account.mfa import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    issue_sensitive_ticket,
    validate_sensitive_ticket,
)
from apps.account.models import User
from apps.account.views import SensitiveMFAView, UserMFAView, UserView, login
from libs.middleware import AuthenticationMiddleware
from apps.setting.models import Setting


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'account-mfa-tests',
    }
}


@override_settings(
    CACHES=TEST_CACHES,
    SECRET_KEY='test-secret-key-for-mfa',
    MFA_ISSUER='Spug Test',
)
class TOTPLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username='tester',
            nickname='测试用户',
            password_hash=User.make_password('Password123'),
            access_token='',
            token_expired=0,
            last_login='',
            last_ip='',
            is_supper=True,
        )

    def request_login(self, **overrides):
        payload = {
            'username': self.user.username,
            'password': 'Password123',
            'type': 'default',
        }
        payload.update(overrides)
        request = self.factory.post(
            '/account/login/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_USER_AGENT='Spug MFA Test',
            HTTP_X_REAL_IP='8.8.8.8',
        )
        response = login(request)
        return json.loads(response.content.decode('utf-8'))

    def enable_totp(self):
        secret = pyotp.random_base32()
        self.user.mfa_secret = encrypt_totp_secret(secret)
        self.user.mfa_last_counter = None
        self.user.mfa_enabled = True
        self.user.save(update_fields=(
            'mfa_secret',
            'mfa_last_counter',
            'mfa_enabled',
        ))
        return secret

    def test_bound_user_logs_in_with_totp_and_code_cannot_be_replayed(self):
        secret = self.enable_totp()

        challenge = self.request_login()
        self.assertFalse(challenge['error'])
        self.assertTrue(challenge['data']['required_mfa'])
        self.assertEqual('totp', challenge['data']['mfa_method'])
        self.assertNotIn('access_token', challenge['data'])

        code = pyotp.TOTP(secret).now()
        result = self.request_login(captcha=code)
        self.assertFalse(result['error'])
        self.assertEqual(32, len(result['data']['access_token']))

        replay = self.request_login(captcha=code)
        self.assertIn('验证码错误', replay['error'])

    def test_disabled_account_logs_in_without_mfa(self):
        secret = self.enable_totp()
        self.user.mfa_enabled = False
        self.user.save(update_fields=('mfa_enabled',))
        result = self.request_login()

        self.assertFalse(result['error'])
        self.assertEqual(32, len(result['data']['access_token']))
        self.assertTrue(self.user.mfa_bound)
        self.assertEqual(secret, decrypt_totp_secret(self.user.mfa_secret))

    def test_legacy_global_setting_does_not_enable_account_mfa(self):
        Setting.objects.create(
            key='MFA',
            value=json.dumps({'enable': True, 'method': 'totp'}),
        )

        result = self.request_login()

        self.assertFalse(result['error'])
        self.assertEqual(32, len(result['data']['access_token']))
        self.assertNotIn('required_mfa', result['data'])

    def test_account_list_only_exposes_totp_binding_status(self):
        self.user.mfa_secret = encrypt_totp_secret(pyotp.random_base32())
        self.user.mfa_last_counter = 123
        self.user.mfa_enabled = True
        self.user.save(update_fields=('mfa_secret', 'mfa_last_counter', 'mfa_enabled'))
        request = self.factory.get('/account/user/')
        request.user = self.user

        response = UserView.as_view()(request)
        record = json.loads(response.content.decode('utf-8'))['data'][0]

        self.assertTrue(record['mfa_bound'])
        self.assertTrue(record['mfa_enabled'])
        self.assertNotIn('mfa_secret', record)
        self.assertNotIn('mfa_last_counter', record)
        self.assertNotIn('mfa_secret', self.user.to_dict())

    def test_user_can_bind_and_unbind_authenticator(self):
        setup_request = self.factory.get('/account/mfa/')
        setup_request.user = self.user
        setup_response = UserMFAView.as_view()(setup_request)
        setup = json.loads(setup_response.content.decode('utf-8'))['data']

        bind_request = self.factory.post(
            '/account/mfa/',
            data=json.dumps({
                'action': 'bind',
                'code': pyotp.TOTP(setup['secret']).now(),
                'setup_token': setup['setup_token'],
            }),
            content_type='application/json',
        )
        bind_request.user = self.user
        bind_response = UserMFAView.as_view()(bind_request)
        self.assertFalse(json.loads(bind_response.content.decode('utf-8'))['error'])

        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_bound)
        self.assertTrue(self.user.mfa_enabled)
        self.user.mfa_last_counter = None
        self.user.save(update_fields=('mfa_last_counter',))
        unbind_request = self.factory.post(
            '/account/mfa/',
            data=json.dumps({
                'action': 'unbind',
                'code': pyotp.TOTP(setup['secret']).now(),
            }),
            content_type='application/json',
        )
        unbind_request.user = self.user
        unbind_response = UserMFAView.as_view()(unbind_request)

        self.assertFalse(json.loads(unbind_response.content.decode('utf-8'))['error'])
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_bound)
        self.assertFalse(self.user.mfa_enabled)

    def test_user_can_disable_and_reenable_mfa_without_rebinding(self):
        secret = self.enable_totp()
        encrypted_secret = self.user.mfa_secret
        self.user.mfa_last_counter = None
        self.user.save(update_fields=('mfa_last_counter',))
        disable_request = self.factory.post(
            '/account/mfa/',
            data=json.dumps({
                'action': 'disable',
                'code': pyotp.TOTP(secret).now(),
            }),
            content_type='application/json',
        )
        disable_request.user = self.user
        disable_response = UserMFAView.as_view()(disable_request)
        self.assertFalse(json.loads(disable_response.content.decode('utf-8'))['error'])
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        self.assertTrue(self.user.mfa_bound)
        self.assertEqual(encrypted_secret, self.user.mfa_secret)

        self.user.mfa_last_counter = None
        self.user.save(update_fields=('mfa_last_counter',))
        enable_request = self.factory.post(
            '/account/mfa/',
            data=json.dumps({
                'action': 'enable',
                'code': pyotp.TOTP(secret).now(),
            }),
            content_type='application/json',
        )
        enable_request.user = self.user
        enable_response = UserMFAView.as_view()(enable_request)
        enable_payload = json.loads(enable_response.content.decode('utf-8'))

        self.assertFalse(enable_payload['error'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)
        self.assertTrue(self.user.mfa_bound)
        self.assertNotEqual(encrypted_secret, self.user.mfa_secret)
        self.assertEqual(secret, decrypt_totp_secret(self.user.mfa_secret))

    def test_sensitive_operation_is_denied_when_mfa_is_disabled(self):
        request = self.factory.get(
            '/account/mfa/sensitive/',
            data={'scope': 'exec_task'},
        )
        request.user = self.user

        response = SensitiveMFAView.as_view()(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertIn('当前账户未开启MFA认证', payload['error'])

    def test_sensitive_totp_ticket_is_scoped_and_single_use(self):
        secret = self.enable_totp()
        request = self.factory.post(
            '/account/mfa/sensitive/',
            data=json.dumps({
                'scope': 'exec_task',
                'code': pyotp.TOTP(secret).now(),
            }),
            content_type='application/json',
        )
        request.user = self.user

        response = SensitiveMFAView.as_view()(request)
        payload = json.loads(response.content.decode('utf-8'))
        ticket = payload['data']['ticket']

        self.assertFalse(payload['error'])
        self.assertIsNone(validate_sensitive_ticket(self.user, 'exec_task', ticket))
        self.assertIn(
            '已失效或已被使用',
            validate_sensitive_ticket(self.user, 'exec_task', ticket),
        )

    def test_host_console_ticket_can_be_reused_only_for_its_scope(self):
        self.enable_totp()
        ticket, _ = issue_sensitive_ticket(self.user, 'host_console')

        self.assertIsNone(validate_sensitive_ticket(self.user, 'host_console', ticket))
        self.assertIsNone(validate_sensitive_ticket(self.user, 'host_console', ticket))
        self.assertIsNotNone(validate_sensitive_ticket(self.user, 'exec_task', ticket))

@override_settings(CACHES=TEST_CACHES)
class DeletedUserSessionRevocationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.admin = User.objects.create(
            username='delete-admin',
            nickname='删除管理员',
            password_hash='-',
            access_token='admin-token'.ljust(32, '0'),
            token_expired=9999999999,
            last_login='',
            last_ip='127.0.0.1',
            is_supper=True,
        )
        self.target = User.objects.create(
            username='deleted-target',
            nickname='待删除用户',
            password_hash='-',
            access_token='deleted-token'.ljust(32, '0'),
            token_expired=9999999999,
            last_login='',
            last_ip='127.0.0.1',
            is_supper=True,
            created_by=self.admin,
        )

    def delete_target(self):
        request = self.factory.delete(
            f'/account/user/?id={self.target.id}'
        )
        request.user = self.admin
        return UserView.as_view()(request)

    def test_delete_revokes_token_and_privileged_state(self):
        response = self.delete_target()
        result = json.loads(response.content.decode())

        self.assertFalse(result['error'])
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(self.target.is_supper)
        self.assertEqual('', self.target.access_token)
        self.assertEqual(0, self.target.token_expired)
        self.assertIsNotNone(self.target.deleted_by_id)

    def test_middleware_rejects_legacy_soft_deleted_token(self):
        old_token = self.target.access_token
        self.delete_target()
        User.objects.filter(pk=self.target.id).update(
            is_active=True,
            is_supper=True,
            access_token=old_token,
            token_expired=9999999999,
        )
        request = self.factory.get(
            '/account/user/',
            HTTP_X_TOKEN=old_token,
            HTTP_X_REAL_IP='127.0.0.1',
        )
        middleware = AuthenticationMiddleware(lambda req: None)

        response = middleware.process_request(request)

        self.assertEqual(401, response.status_code)
        self.assertFalse(hasattr(request, 'user'))


@override_settings(CACHES=TEST_CACHES)
class LoginFailureThrottlingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username='throttle-user',
            nickname='登录限流用户',
            password_hash=User.make_password('Password123'),
            access_token='',
            token_expired=0,
            last_login='',
            last_ip='',
        )

    def request_login(self, password, source_ip='10.0.0.1'):
        request = self.factory.post(
            '/account/login/',
            data=json.dumps({
                'username': self.user.username,
                'password': password,
                'type': 'default',
            }),
            content_type='application/json',
            HTTP_USER_AGENT='Spug Login Throttle Test',
            HTTP_X_REAL_IP=source_ip,
        )
        return json.loads(login(request).content.decode('utf-8'))

    def test_repeated_failures_temporarily_throttle_without_disabling_user(self):
        for _ in range(5):
            result = self.request_login('WrongPassword')
            self.assertEqual('用户名或密码错误', result['error'])

        result = self.request_login('WrongPassword')

        self.assertEqual('登录失败次数过多，请5分钟后重试', result['error'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_throttled_source_does_not_lock_valid_login_from_another_ip(self):
        for _ in range(5):
            self.request_login('WrongPassword', source_ip='10.0.0.1')

        blocked = self.request_login('Password123', source_ip='10.0.0.1')
        allowed = self.request_login('Password123', source_ip='10.0.0.2')

        self.assertEqual('登录失败次数过多，请5分钟后重试', blocked['error'])
        self.assertFalse(allowed['error'])
        self.assertEqual(32, len(allowed['data']['access_token']))
