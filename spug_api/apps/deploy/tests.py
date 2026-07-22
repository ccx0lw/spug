import json
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta

from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.account.models import User
from apps.app.models import App, Deploy
from apps.config.models import Environment
from apps.deploy.models import (
    DeployIteration,
    DeployIterationDetail,
    DeployOperationLog,
    DeployRequest,
)
from apps.deploy.views import (
    IterationDetailView,
    OperationLogView,
    RequestView,
    get_request_info,
)
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
            is_supper=True,
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

    def create_failed_detail(self, iteration_name, failed_at):
        failed_iteration = DeployIteration.objects.create(
            name=iteration_name,
            env=self.env,
            status='-3',
            created_by=self.user,
        )
        failed_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name=f'迭代：{iteration_name}',
            type='1',
            extra='[]',
            host_ids='[]',
            status='-3',
            version='v1.0.0',
            do_at=failed_at,
            failed_at=failed_at,
            created_by=self.user,
        )
        return self.create_detail(
            failed_iteration,
            'v1.0.0',
            status='3',
            request_id=failed_request.id,
        )

    def update_detail_version(self, detail_id, version):
        request = RequestFactory().put(
            '/api/deploy/iteration/detail/',
            data=json.dumps({'detail_id': detail_id, 'version': version}),
            content_type='application/json',
        )
        request.user = self.user
        response = IterationDetailView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

    def get_operation_logs(self, target_type, target_id):
        request = RequestFactory().get(
            '/api/deploy/operation-log/',
            data={'target_type': target_type, 'target_id': target_id},
        )
        request.user = self.user
        response = OperationLogView.as_view()(request)
        return json.loads(response.content.decode('utf-8'))

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
        failed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.create_failed_detail('失败迭代', failed_at)

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertIn('其他失败迭代仍可重试', warning['message'])
        self.assertTrue(
            warning['related_iterations'][0]['request_retry_allowed']
        )

    def test_expired_failed_iteration_is_not_cross_iteration_duplicate(self):
        current_detail = self.create_detail(self.iteration, 'v2.0.0')
        failed_at = (datetime.now() - timedelta(hours=25)).strftime(
            '%Y-%m-%d %H:%M:%S'
        )
        self.create_failed_detail('已过期失败迭代', failed_at)

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertFalse(warning['has_warning'])
        self.assertEqual('none', warning['kind'])
        self.assertEqual([], warning['related_iterations'])

    def test_retry_disabled_failure_is_not_cross_iteration_duplicate(self):
        self.env.deploy_retry_hours = 0
        self.env.save()
        current_detail = self.create_detail(self.iteration, 'v2.0.0')
        failed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.create_failed_detail('禁止重试迭代', failed_at)

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertFalse(warning['has_warning'])
        self.assertEqual([], warning['related_iterations'])

    def test_non_retryable_current_failure_has_no_cross_iteration_duplicate(self):
        failed_at = (datetime.now() - timedelta(hours=25)).strftime(
            '%Y-%m-%d %H:%M:%S'
        )
        failed_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='迭代：当前迭代',
            type='1',
            extra='[]',
            host_ids='[]',
            status='-3',
            version='v1.0.0',
            do_at=failed_at,
            failed_at=failed_at,
            created_by=self.user,
        )
        current_detail = self.create_detail(
            self.iteration,
            'v1.0.0',
            status='3',
            request_id=failed_request.id,
        )
        other_iteration = DeployIteration.objects.create(
            name='其他待发布迭代',
            env=self.env,
            created_by=self.user,
        )
        self.create_detail(other_iteration, 'v2.0.0')

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertFalse(warning['has_warning'])
        self.assertEqual('none', warning['kind'])
        self.assertEqual([], warning['related_iterations'])

    def test_retryable_current_failure_keeps_cross_iteration_duplicate(self):
        failed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        failed_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='迭代：当前迭代',
            type='1',
            extra='[]',
            host_ids='[]',
            status='-3',
            version='v1.0.0',
            do_at=failed_at,
            failed_at=failed_at,
            created_by=self.user,
        )
        current_detail = self.create_detail(
            self.iteration,
            'v1.0.0',
            status='3',
            request_id=failed_request.id,
        )
        other_iteration = DeployIteration.objects.create(
            name='其他待发布迭代',
            env=self.env,
            created_by=self.user,
        )
        self.create_detail(other_iteration, 'v2.0.0')

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertEqual('cross_iteration', warning['kind'])
        self.assertEqual(1, len(warning['related_iterations']))

    def test_expired_failed_detail_cannot_update_version(self):
        failed_at = (datetime.now() - timedelta(hours=25)).strftime(
            '%Y-%m-%d %H:%M:%S'
        )
        detail = self.create_failed_detail('已过期失败迭代', failed_at)

        response = self.update_detail_version(detail.id, 'v2.0.0')

        self.assertIn('过期', response['error'])
        detail.refresh_from_db()
        self.assertEqual('v1.0.0', detail.version)
        self.assertEqual('3', detail.status)
        self.assertIsNotNone(detail.request_id)
        self.assertFalse(DeployOperationLog.objects.filter(
            target_type='iteration',
            target_id=detail.iteration_id,
        ).exists())

    def test_retryable_failed_detail_can_update_version(self):
        failed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        detail = self.create_failed_detail('可重试失败迭代', failed_at)

        response = self.update_detail_version(detail.id, 'v2.0.0')

        self.assertEqual('', response['error'])
        detail.refresh_from_db()
        self.assertEqual('v2.0.0', detail.version)
        self.assertEqual('0', detail.status)
        self.assertIsNone(detail.request_id)
        operation_log = DeployOperationLog.objects.get(
            target_type='iteration',
            target_id=detail.iteration_id,
        )
        self.assertEqual(self.user.id, operation_log.operator_id)
        self.assertEqual('测试用户', operation_log.operator_name)
        self.assertEqual(
            '修改应用【订单服务】版本（环境【测试环境】）',
            operation_log.action,
        )

        response = self.get_operation_logs('iteration', detail.iteration_id)
        self.assertEqual('', response['error'])
        self.assertEqual(
            {'id', 'operator_name', 'action', 'created_at'},
            set(response['data'][0]),
        )

    def test_delete_request_records_operation_log(self):
        deploy_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='待删除发布申请',
            type='1',
            extra='[]',
            host_ids='[]',
            status='1',
            version='v1.0.0',
            created_by=self.user,
        )
        request = RequestFactory().delete(
            f'/api/deploy/request/?id={deploy_request.id}'
        )
        request.user = self.user

        response = RequestView.as_view()(request)
        response_data = json.loads(response.content.decode('utf-8'))

        self.assertEqual('', response_data['error'])
        self.assertFalse(DeployRequest.objects.filter(pk=deploy_request.id).exists())
        operation_log = DeployOperationLog.objects.get(
            target_type='request',
            target_id=deploy_request.id,
        )
        self.assertEqual('删除发布申请', operation_log.action)
        self.assertEqual('测试用户', operation_log.operator_name)

    def test_request_info_contains_direct_detail_metadata(self):
        deploy_request = self.create_success_request(
            'v2.1.0',
            name='迭代发布申请详情',
        )
        request = RequestFactory().get(
            '/api/deploy/request/info/',
            data={'id': deploy_request.id},
        )
        request.user = self.user

        response = get_request_info(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertFalse(payload['error'])
        self.assertEqual(deploy_request.id, payload['data']['id'])
        self.assertEqual('迭代发布申请详情', payload['data']['name'])
        self.assertEqual('订单服务', payload['data']['app_name'])
        self.assertEqual('测试环境', payload['data']['env_name'])
        self.assertEqual('1', payload['data']['app_extend'])
        self.assertEqual('发布成功', payload['data']['status_alias'])

    def test_remove_iteration_detail_log_contains_environment(self):
        other_env = Environment.objects.create(
            name='预发布环境',
            key='staging',
            created_by=self.user,
        )
        other_app = App.objects.create(
            name='库存服务',
            key='inventory-service',
            created_by=self.user,
        )
        other_deploy = Deploy.objects.create(
            app=other_app,
            env=other_env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
            created_by=self.user,
        )
        self.create_detail(self.iteration, 'v1.0.0')
        removed_detail = DeployIterationDetail.objects.create(
            iteration=self.iteration,
            deploy=other_deploy,
            version='v2.0.0',
            created_by=self.user,
        )
        request = RequestFactory().delete(
            f'/api/deploy/iteration/detail/?detail_id={removed_detail.id}'
        )
        request.user = self.user

        response = IterationDetailView.as_view()(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertFalse(payload['error'])
        self.assertFalse(DeployIterationDetail.objects.filter(pk=removed_detail.id).exists())
        operation_log = DeployOperationLog.objects.get(
            target_type='iteration',
            target_id=self.iteration.id,
            action__startswith='移除应用',
        )
        self.assertEqual(
            '移除应用【库存服务】（环境【预发布环境】）',
            operation_log.action,
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
