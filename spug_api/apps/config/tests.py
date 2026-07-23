import json
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase

from apps.config.views import CONFIG_KEY_RE, ConfigView


class ConfigKeySecurityTests(SimpleTestCase):
    def test_valid_config_key_format_is_preserved(self):
        self.assertIsNotNone(CONFIG_KEY_RE.fullmatch('_SPUG_RELEASE_TAG'))

    def test_shell_syntax_in_config_key_is_rejected_by_api(self):
        request = RequestFactory().post(
            '/api/config/',
            data=json.dumps({
                'o_id': 1,
                'type': 'app',
                'envs': [1],
                'key': '_SPUG_X; touch /tmp/spug-config-probe',
                'is_public': False,
                'value': 'safe',
            }),
            content_type='application/json',
        )
        request.user = SimpleNamespace(has_perms=lambda codes: True)

        response = ConfigView.as_view()(request)
        result = json.loads(response.content.decode('utf-8'))

        self.assertIn('只能包含字母', result['error'])
