from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime

from django.test import SimpleTestCase, TestCase

from apps.account.models import User
from apps.app.models import App, Deploy
from apps.config.models import Environment
from apps.deploy.models import DeployIteration, DeployIterationDetail, DeployRequest
from apps.deploy.utils import (
    get_cross_iteration_warnings,
    get_iteration_detail_remove_error,
    get_iteration_detail_status,
    get_iteration_overall_status,
    get_deploy_retry_info,
    lock_deploy_and_get_running_request,
    reconcile_iteration_detail_statuses,
)


class CrossIterationWarningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='tester',
            nickname='测试用户',
            password_hash='-',
            access_token='test-token',
            last_login='',
            last_ip='',
        )
        self.env = Environment.objects.create(
            name='测试环境',
            key='test',
            created_by=self.user,
        )
        self.app = App.objects.create(
            name='订单服务',
            key='order-service',
            created_by=self.user,
        )
        self.deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.user,
        )
        self.iteration = DeployIteration.objects.create(
            name='当前迭代',
            env=self.env,
            created_by=self.user,
        )

    def create_detail(self, iteration, version, status='0', request_id=None):
        return DeployIterationDetail.objects.create(
            iteration=iteration,
            deploy=self.deploy,
            version=version,
            status=status,
            request_id=request_id,
            created_by=self.user,
        )

    def create_success_request(self, version, name='迭代：后续迭代'):
        return DeployRequest.objects.create(
            deploy=self.deploy,
            name=name,
            type='1',
            extra='[]',
            host_ids='[]',
            status='3',
            version=version,
            do_at='2026-07-21 10:00:00',
            created_by=self.user,
        )

    def test_later_iteration_success_is_shown_as_version_switch(self):
        current_detail = self.create_detail(self.iteration, 'v1.0.0')
        later_iteration = DeployIteration.objects.create(
            name='后续迭代',
            env=self.env,
            status='2',
            created_by=self.user,
        )
        success_request = self.create_success_request('v2.0.0')
        self.create_detail(
            later_iteration,
            'v2.0.0',
            status='2',
            request_id=success_request.id,
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertEqual('version_switch', warning['kind'])
        self.assertEqual('warning', warning['level'])
        self.assertIn('后续迭代【后续迭代】已发布 v2.0.0', warning['message'])
        self.assertEqual(later_iteration.id, warning['latest_success']['iteration_id'])

    def test_same_latest_version_is_shown_without_blocking(self):
        current_detail = self.create_detail(self.iteration, 'v2.0.0')
        self.create_success_request(
            'v2.0.0',
            name='单应用指定 Tag 发布',
        )
        DeployRequest.objects.create(
            deploy=self.deploy,
            name='重启应用',
            type='0',
            extra='[]',
            host_ids='[]',
            status='3',
            version=None,
            do_at='2026-07-21 11:00:00',
            created_by=self.user,
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertEqual('same_version', warning['kind'])
        self.assertEqual('info', warning['level'])
        self.assertTrue(warning['latest_success']['is_same_version'])

    def test_other_pending_iteration_is_included_in_warning(self):
        current_detail = self.create_detail(self.iteration, 'v1.0.0')
        other_iteration = DeployIteration.objects.create(
            name='并行规划迭代',
            env=self.env,
            created_by=self.user,
        )
        self.create_detail(other_iteration, 'v1.1.0')

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertEqual('cross_iteration', warning['kind'])
        self.assertEqual('warning', warning['level'])
        self.assertEqual(1, len(warning['related_iterations']))
        self.assertEqual(
            other_iteration.id,
            warning['related_iterations'][0]['iteration_id'],
        )

    def test_other_retryable_failed_iteration_is_included_in_warning(self):
        current_detail = self.create_detail(self.iteration, 'v2.0.0')
        failed_iteration = DeployIteration.objects.create(
            name='失败迭代',
            env=self.env,
            status='-3',
            created_by=self.user,
        )
        failed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        failed_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='迭代：失败迭代',
            type='1',
            extra='[]',
            host_ids='[]',
            status='-3',
            version='v1.0.0',
            do_at=failed_at,
            failed_at=failed_at,
            created_by=self.user,
        )
        self.create_detail(
            failed_iteration,
            'v1.0.0',
            status='3',
            request_id=failed_request.id,
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertIn('其他失败迭代仍可重试', warning['message'])
        self.assertTrue(
            warning['related_iterations'][0]['request_retry_allowed']
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
