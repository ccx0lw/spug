from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime

from django.test import SimpleTestCase

from apps.deploy.utils import (
    get_iteration_detail_remove_error,
    get_iteration_detail_status,
    get_iteration_overall_status,
    get_deploy_retry_info,
    lock_deploy_and_get_running_request,
    reconcile_iteration_detail_statuses,
)


class IterationDetailStatusTests(SimpleTestCase):
    @patch('apps.app.models.Deploy.objects.select_for_update')
    @patch('apps.deploy.utils.DeployRequest.objects.select_for_update')
    def test_publish_lock_checks_latest_running_request(
            self, request_select_for_update, deploy_select_for_update):
        deploy = SimpleNamespace(id=5)
        running_request = SimpleNamespace(id=9)
        deploy_select_for_update.return_value.select_related.return_value.filter \
            .return_value.first.return_value = deploy
        request_select_for_update.return_value.filter.return_value.only \
            .return_value.first.return_value = running_request

        locked_deploy, locked_request = lock_deploy_and_get_running_request(5)

        self.assertIs(deploy, locked_deploy)
        self.assertIs(running_request, locked_request)
        deploy_select_for_update.assert_called_once_with()
        request_select_for_update.assert_called_once_with()

    def test_request_status_mapping(self):
        self.assertEqual('2', get_iteration_detail_status('3'))
        self.assertEqual('3', get_iteration_detail_status('-3'))
        self.assertEqual('1', get_iteration_detail_status('2'))
        self.assertEqual('1', get_iteration_detail_status('1'))
        self.assertEqual('0', get_iteration_detail_status('0'))

    @patch('apps.deploy.utils.update_iteration_overall_status')
    @patch('apps.deploy.models.DeployIterationDetail.objects.bulk_update')
    @patch('apps.deploy.utils.DeployRequest.objects.filter')
    def test_reconcile_success_request_updates_stuck_detail(
            self, request_filter, bulk_update, update_overall_status):
        request_filter.return_value.values_list.return_value = [(11, '3')]
        detail = SimpleNamespace(
            request_id=11,
            status='1',
            iteration_id=7,
        )

        affected_iteration_ids = reconcile_iteration_detail_statuses([detail])

        self.assertEqual('2', detail.status)
        self.assertEqual({7}, affected_iteration_ids)
        bulk_update.assert_called_once_with([detail], ['status'])
        update_overall_status.assert_called_once_with(7)

    def test_overall_status_after_pending_detail_removed(self):
        self.assertEqual('2', get_iteration_overall_status(['2', '2']))
        self.assertEqual('-1', get_iteration_overall_status(['2', '3']))
        self.assertEqual('-3', get_iteration_overall_status(['3']))

    def test_only_untouched_pending_detail_can_be_removed(self):
        removable = SimpleNamespace(
            request_id=None,
            status='0',
            image_status='0',
            docker_image_id=None,
        )
        self.assertIsNone(get_iteration_detail_remove_error(removable))

        removable.request_id = 11
        self.assertIn('发布申请', get_iteration_detail_remove_error(removable))
        removable.request_id = None
        removable.image_status = '2'
        self.assertIn('预传镜像', get_iteration_detail_remove_error(removable))

    def test_failed_deploy_retry_window_uses_environment_config(self):
        env = SimpleNamespace(name='测试环境', deploy_retry_hours=24)
        request = SimpleNamespace(
            status='-3',
            failed_at='2026-07-16 10:00:00',
            do_at='2026-07-16 09:00:00',
            created_at='2026-07-16 08:00:00',
            deploy=SimpleNamespace(env=env),
        )

        at_deadline = get_deploy_retry_info(
            request,
            now=datetime(2026, 7, 17, 10, 0, 0),
        )
        self.assertTrue(at_deadline['retry_allowed'])
        self.assertEqual('2026-07-17 10:00:00', at_deadline['retry_deadline'])

        expired = get_deploy_retry_info(
            request,
            now=datetime(2026, 7, 17, 10, 0, 1),
        )
        self.assertFalse(expired['retry_allowed'])
        self.assertIn('已于2026-07-17 10:00:00过期', expired['retry_error'])

        env.deploy_retry_hours = 0
        disabled = get_deploy_retry_info(request)
        self.assertFalse(disabled['retry_allowed'])
        self.assertIn('已禁止', disabled['retry_error'])

    def test_historical_failure_without_failed_at_falls_back_to_do_at(self):
        env = SimpleNamespace(name='历史环境', deploy_retry_hours=24)
        request = SimpleNamespace(
            status='-3',
            failed_at=None,
            do_at='2026-07-16 10:00:00',
            created_at='2026-07-16 08:00:00',
            deploy=SimpleNamespace(env=env),
        )

        retry_info = get_deploy_retry_info(
            request,
            now=datetime(2026, 7, 17, 9, 59, 59),
        )

        self.assertTrue(retry_info['retry_allowed'])
        self.assertEqual('2026-07-17 10:00:00', retry_info['retry_deadline'])
