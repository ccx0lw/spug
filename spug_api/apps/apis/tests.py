import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.apis.deploy import _parse_request, get_deploy_webhook_key


class WebhookScopeValidationTests(SimpleTestCase):
    @patch(
        'apps.apis.deploy.AppSetting.get_default',
        return_value='master-api-key',
    )
    def test_webhook_key_is_bound_to_deploy_id(self, get_default):
        first = get_deploy_webhook_key(1)
        second = get_deploy_webhook_key(2)

        self.assertNotEqual(first, second)

        request = RequestFactory().post(
            '/api/apis/deploy/2/tag/',
            data=json.dumps({'ref': 'refs/tags/v1'}),
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=first,
        )
        repo, body = _parse_request(request, 2)

        self.assertIsNone(repo)
        self.assertIsNone(body)
