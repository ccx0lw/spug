import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from paramiko.ssh_exception import SSHException

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from apps.account.models import User
from apps.app.models import App, Deploy, DeployExtend2, DeployExtend3
from apps.config.models import Environment
from apps.deploy.models import (
    DeployIteration,
    DeployIterationDetail,
    DeployOperationLog,
    DeployRequest,
    DeployUpload,
)
from apps.deploy.views import (
    IterationDetailView,
    IterationImageView,
    IterationPublishView,
    IterationView,
    OperationLogView,
    RequestDetailView,
    RequestView,
    do_upload,
    get_request_info,
    post_request_ext1,
    post_request_ext1_rollback,
    post_request_ext2,
)
from apps.host.models import Group, Host
from apps.docker_image.models import DockerImage
from apps.repository.models import Repository
from apps.app.views import get_info as get_deploy_info
from apps.app.views import get_versions as get_deploy_versions
from apps.deploy.utils import (
    _cleanup_stale_requests,
    dispatch_iteration_request,
    get_cross_iteration_warnings,
    get_iteration_detail_remove_error,
    get_iteration_detail_status,
    get_iteration_overall_status,
    get_deploy_retry_info,
    get_reused_artifact_error,
    lock_deploy_and_get_running_request,
    reconcile_iteration_detail_statuses,
)
from apps.deploy.helper import Helper, RemoteOutcomeUnknown


class DeployUploadSecurityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='upload-admin',
            nickname='上传管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='上传测试环境',
            key='upload-test',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='上传测试应用',
            key='upload-test-app',
            created_by=self.creator,
        )
        self.deploy = Deploy.objects.create(
            app=self.app,
            env=self.env,
            host_ids='[]',
            extend='2',
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )
        DeployExtend2.objects.create(
            deploy=self.deploy,
            server_actions='[]',
            host_actions=json.dumps([{
                'title': '传输上传文件',
                'type': 'transfer',
                'src_mode': '1',
                'dst': '/srv/app/',
            }]),
            require_upload=True,
        )

    def make_user(self, apps, envs):
        if self.app.id in apps and self.env.id in envs:
            return self.creator
        return SimpleNamespace(
            id=self.creator.id,
            is_supper=False,
            deploy_perms={'apps': set(apps), 'envs': set(envs)},
            has_perms=lambda codes: True,
        )

    def upload(self, user, deploy_id):
        request = self.factory.post(
            '/api/deploy/request/upload/',
            data={
                'deploy_id': deploy_id,
                'file': SimpleUploadedFile('release.tar.gz', b'safe-content'),
            },
        )
        request.user = user
        response = do_upload(request)
        return json.loads(response.content.decode('utf-8'))

    def test_valid_scoped_deploy_upload_is_preserved(self):
        user = self.make_user([self.app.id], [self.env.id])
        with tempfile.TemporaryDirectory() as repos_dir:
            with override_settings(REPOS_DIR=repos_dir):
                result = self.upload(user, str(self.deploy.id))
                upload_path = os.path.join(
                    repos_dir,
                    str(self.deploy.id),
                    result['data']['path'],
                )

                self.assertFalse(result['error'])
                self.assertEqual(
                    'release.tar.gz',
                    result['data']['name'],
                )
                with open(upload_path, 'rb') as uploaded:
                    self.assertEqual(b'safe-content', uploaded.read())

    def test_shell_syntax_in_deploy_id_is_rejected(self):
        user = self.make_user([self.app.id], [self.env.id])
        with tempfile.TemporaryDirectory() as repos_dir:
            with override_settings(REPOS_DIR=repos_dir):
                result = self.upload(
                    user,
                    f'{self.deploy.id}; touch /tmp/spug-upload-probe',
                )

                self.assertEqual('发布配置参数错误', result['error'])
                self.assertEqual([], os.listdir(repos_dir))

    def test_numeric_deploy_outside_user_scope_is_rejected(self):
        user = self.make_user([], [])
        with tempfile.TemporaryDirectory() as repos_dir:
            with override_settings(REPOS_DIR=repos_dir):
                result = self.upload(user, str(self.deploy.id))

                self.assertIn('无操作权限', result['error'])
                self.assertEqual([], os.listdir(repos_dir))

    def test_request_uses_server_upload_metadata_and_token_is_single_use(self):
        user = self.make_user([self.app.id], [self.env.id])
        with tempfile.TemporaryDirectory() as repos_dir:
            with override_settings(REPOS_DIR=repos_dir):
                uploaded = self.upload(user, str(self.deploy.id))['data']
                payload = {
                    'deploy_id': self.deploy.id,
                    'name': '绑定上传文件',
                    'extra': {
                        'path': '../../etc/passwd',
                        'name': '../../authorized_keys',
                        'upload_token': uploaded['upload_token'],
                    },
                }
                first_request = self.factory.post(
                    '/api/deploy/request/ext2/',
                    data=json.dumps(payload),
                    content_type='application/json',
                )
                first_request.user = user
                first = json.loads(
                    post_request_ext2(first_request).content.decode()
                )

                self.assertFalse(first['error'])
                deploy_request = DeployRequest.objects.get(
                    name='绑定上传文件'
                )
                extra = json.loads(deploy_request.extra)
                self.assertEqual(uploaded['path'], extra['path'])
                self.assertEqual('release.tar.gz', extra['name'])
                self.assertEqual(
                    deploy_request.id,
                    DeployUpload.objects.get(
                        token=uploaded['upload_token']
                    ).consumed_request_id,
                )

                payload['name'] = '重复使用上传文件'
                second_request = self.factory.post(
                    '/api/deploy/request/ext2/',
                    data=json.dumps(payload),
                    content_type='application/json',
                )
                second_request.user = user
                second = json.loads(
                    post_request_ext2(second_request).content.decode()
                )

                self.assertIn('已被使用', second['error'])
                self.assertFalse(DeployRequest.objects.filter(
                    name='重复使用上传文件'
                ).exists())

    def test_request_rejects_forged_upload_metadata_without_token(self):
        user = self.make_user([self.app.id], [self.env.id])
        request = self.factory.post(
            '/api/deploy/request/ext2/',
            data=json.dumps({
                'deploy_id': self.deploy.id,
                'name': '伪造上传路径',
                'extra': {
                    'path': '/etc/passwd',
                    'name': '../../authorized_keys',
                },
            }),
            content_type='application/json',
        )
        request.user = user

        result = json.loads(post_request_ext2(request).content.decode())

        self.assertIn('上传文件无效', result['error'])
        self.assertFalse(DeployRequest.objects.filter(
            name='伪造上传路径'
        ).exists())

    def test_deleting_legacy_request_cannot_escape_upload_directory(self):
        with tempfile.TemporaryDirectory() as root:
            repos_dir = os.path.join(root, 'repos')
            os.mkdir(repos_dir)
            protected_path = os.path.join(root, 'protected.txt')
            with open(protected_path, 'wb') as protected:
                protected.write(b'keep-me')
            request_obj = DeployRequest.objects.create(
                deploy=self.deploy,
                name='历史恶意路径',
                type='1',
                extra=json.dumps({
                    'path': '../protected.txt',
                    'name': 'protected.txt',
                }),
                host_ids='[]',
                status='1',
                version='',
                spug_version='../protected.txt',
                created_by=self.creator,
            )

            with override_settings(REPOS_DIR=repos_dir):
                request_obj.delete()

            self.assertTrue(os.path.exists(protected_path))


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

    def create_detail(
            self, iteration, version, status='0', request_id=None, deploy=None):
        return DeployIterationDetail.objects.create(
            iteration=iteration,
            deploy=deploy or self.deploy,
            version=version,
            status=status,
            request_id=request_id,
            created_by=self.user,
        )

    def create_deploy(self, suffix):
        app = App.objects.create(
            name=f'订单服务-{suffix}',
            key=f'order-service-{suffix}',
            created_by=self.user,
        )
        return Deploy.objects.create(
            app=app,
            env=self.env,
            host_ids='[]',
            extend='1',
            is_audit=False,
            rst_notify='[]',
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

    def test_higher_semantic_version_is_not_shown_as_rollback(self):
        current_detail = self.create_detail(self.iteration, 'v1.0.3')
        self.create_success_request(
            'v1.0.2',
            name='单应用指定 Tag 发布',
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertFalse(warning['has_warning'])
        self.assertEqual('none', warning['kind'])
        self.assertEqual('', warning['message'])
        self.assertEqual('v1.0.2', warning['latest_success']['version'])

    def test_semantic_version_segments_are_compared_as_numbers(self):
        current_detail = self.create_detail(self.iteration, 'v1.10.0')
        self.create_success_request(
            'v1.9.9',
            name='单应用指定 Tag 发布',
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertFalse(warning['has_warning'])
        self.assertEqual('none', warning['kind'])

    def test_lower_semantic_version_is_still_shown_as_rollback(self):
        current_detail = self.create_detail(self.iteration, 'v1.0.2')
        self.create_success_request(
            'v1.0.3',
            name='单应用指定 Tag 发布',
        )

        warning = get_cross_iteration_warnings(
            self.iteration,
            [current_detail],
        )[current_detail.id]

        self.assertTrue(warning['has_warning'])
        self.assertEqual('version_switch', warning['kind'])
        self.assertIn('可能属于回滚', warning['message'])

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
            '修改应用【订单服务】版本【v1.0.0】→【v2.0.0】（环境【测试环境】）',
            operation_log.action,
        )
        self.assertEqual('v1.0.0', response['data']['old_version'])
        self.assertEqual('v2.0.0', response['data']['new_version'])

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

    def test_batch_remove_pending_details_by_environment(self):
        first = self.create_detail(self.iteration, 'v1.0.0')
        second = self.create_detail(
            self.iteration,
            'v1.0.1',
            deploy=self.create_deploy('batch-second'),
        )
        published = self.create_detail(
            self.iteration,
            'v1.0.2',
            status='2',
            deploy=self.create_deploy('batch-published'),
        )
        request = RequestFactory().delete(
            f'/api/deploy/iteration/detail/?iteration_id={self.iteration.id}'
            f'&env_id={self.env.id}',
        )
        request.user = self.user

        response = IterationDetailView.as_view()(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertFalse(payload['error'])
        self.assertEqual(2, payload['data']['removed_count'])
        self.assertCountEqual(
            [first.id, second.id],
            payload['data']['removed_ids'],
        )
        self.assertFalse(DeployIterationDetail.objects.filter(
            pk__in=(first.id, second.id)
        ).exists())
        self.assertTrue(DeployIterationDetail.objects.filter(pk=published.id).exists())
        self.iteration.refresh_from_db()
        self.assertEqual('2', self.iteration.status)
        self.assertEqual(
            2,
            DeployOperationLog.objects.filter(
                target_type='iteration',
                target_id=self.iteration.id,
                action__startswith='移除应用',
            ).count(),
        )

    def test_batch_remove_keeps_at_least_one_iteration_detail(self):
        first = self.create_detail(self.iteration, 'v1.0.0')
        second = self.create_detail(
            self.iteration,
            'v1.0.1',
            deploy=self.create_deploy('batch-only-second'),
        )
        request = RequestFactory().delete(
            f'/api/deploy/iteration/detail/?iteration_id={self.iteration.id}'
            f'&env_id={self.env.id}',
        )
        request.user = self.user

        response = IterationDetailView.as_view()(request)
        payload = json.loads(response.content.decode('utf-8'))

        self.assertIn('至少保留一个应用', payload['error'])
        self.assertEqual(
            2,
            DeployIterationDetail.objects.filter(
                pk__in=(first.id, second.id)
            ).count(),
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
        request_select_for_update.return_value.filter.assert_called_once_with(
            deploy_id=5,
            status__in=('2', '-2'),
        )

    def test_request_status_mapping(self):
        self.assertEqual('2', get_iteration_detail_status('3'))
        self.assertEqual('3', get_iteration_detail_status('-3'))
        self.assertEqual('4', get_iteration_detail_status('-2'))
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
        self.assertEqual('-2', get_iteration_overall_status(['2', '4']))

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

    def test_unknown_deploy_result_is_never_directly_retryable(self):
        env = SimpleNamespace(name='测试环境', deploy_retry_hours=24)
        request = SimpleNamespace(
            status='-2',
            failed_at='2026-07-23 10:00:00',
            do_at='2026-07-23 09:00:00',
            created_at='2026-07-23 08:00:00',
            deploy=SimpleNamespace(env=env),
        )

        retry_info = get_deploy_retry_info(request)

        self.assertFalse(retry_info['retry_allowed'])
        self.assertIn('禁止直接重试', retry_info['retry_error'])

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


class RemoteOutcomeUnknownTests(SimpleTestCase):
    def test_ssh_disconnect_is_reported_as_unknown_not_retryable_failure(self):
        redis = Mock()
        helper = Helper(redis, 'deploy-log')
        ssh = Mock()
        ssh.exec_command_with_stream.side_effect = SSHException(
            'connection lost'
        )

        with self.assertRaises(RemoteOutcomeUnknown):
            helper.remote('host-1', ssh, 'kubectl apply -f app.yaml')

        message = json.loads(redis.rpush.call_args.args[1])
        self.assertEqual('unknown', message['status'])
        self.assertIn('禁止直接重试', message['data'])


class DeployRequestObjectScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='request-scope-admin',
            nickname='申请管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.allowed_env = Environment.objects.create(
            name='授权环境',
            key='request-scope-allowed-env',
            created_by=self.creator,
        )
        self.denied_env = Environment.objects.create(
            name='越权环境',
            key='request-scope-denied-env',
            created_by=self.creator,
        )
        self.allowed_app = App.objects.create(
            name='授权应用',
            key='request-scope-allowed-app',
            created_by=self.creator,
        )
        self.denied_app = App.objects.create(
            name='越权应用',
            key='request-scope-denied-app',
            created_by=self.creator,
        )
        self.allowed_deploy = self.make_deploy(
            self.allowed_app,
            self.allowed_env,
        )
        self.denied_deploy = self.make_deploy(
            self.denied_app,
            self.denied_env,
        )
        self.denied_request = self.make_request(
            self.denied_deploy,
            status='0',
        )

    def make_deploy(self, app, env):
        return Deploy.objects.create(
            app=app,
            env=env,
            host_ids='[]',
            extend='1',
            is_audit=True,
            rst_notify='[]',
            created_by=self.creator,
        )

    def make_request(self, deploy, status='0'):
        return DeployRequest.objects.create(
            deploy=deploy,
            name='对象范围测试申请',
            type='1',
            extra=json.dumps(['tag', 'v1.0.0']),
            host_ids='[]',
            status=status,
            version='v1.0.0',
            spug_version=f'{deploy.id}_test',
            created_by=self.creator,
        )

    def scoped_user(self, permissions):
        return SimpleNamespace(
            is_supper=False,
            deploy_perms={
                'apps': {self.allowed_app.id},
                'envs': {self.allowed_env.id},
            },
            has_perms=lambda codes: bool(set(codes).intersection(permissions)),
        )

    def decode(self, response):
        return json.loads(response.content.decode())

    def test_detail_and_info_hide_out_of_scope_request(self):
        user = self.scoped_user({'deploy.request.view'})
        detail_request = self.factory.get(
            f'/api/deploy/request/{self.denied_request.id}/'
        )
        detail_request.user = user
        info_request = self.factory.get(
            '/api/deploy/request/info/',
            data={'id': self.denied_request.id},
        )
        info_request.user = user

        detail = self.decode(
            RequestDetailView.as_view()(
                detail_request,
                r_id=self.denied_request.id,
            )
        )
        info = self.decode(get_request_info(info_request))

        self.assertIn('未找到', detail['error'])
        self.assertIn('未找到', info['error'])

    def test_delete_and_approve_cannot_mutate_out_of_scope_request(self):
        delete_request = self.factory.delete(
            f'/api/deploy/request/?id={self.denied_request.id}'
        )
        delete_request.user = self.scoped_user({'deploy.request.del'})
        approve_request = self.factory.patch(
            f'/api/deploy/request/{self.denied_request.id}/',
            data=json.dumps({'is_pass': True}),
            content_type='application/json',
        )
        approve_request.user = self.scoped_user(
            {'deploy.request.approve'}
        )

        deleted = self.decode(RequestView.as_view()(delete_request))
        approved = self.decode(
            RequestDetailView.as_view()(
                approve_request,
                r_id=self.denied_request.id,
            )
        )

        self.assertIn('未找到', deleted['error'])
        self.assertIn('未找到', approved['error'])
        self.denied_request.refresh_from_db()
        self.assertEqual('0', self.denied_request.status)

    def test_add_only_permission_cannot_edit_request(self):
        request_obj = self.make_request(self.allowed_deploy, status='0')
        request = self.factory.post(
            '/api/deploy/request/ext1/',
            data=json.dumps({
                'id': request_obj.id,
                'deploy_id': self.allowed_deploy.id,
                'name': '不应被修改',
                'extra': ['tag', 'v2.0.0'],
            }),
            content_type='application/json',
        )
        request.user = self.scoped_user({'deploy.request.add'})

        result = self.decode(post_request_ext1(request))

        self.assertEqual('权限拒绝', result['error'])
        request_obj.refresh_from_db()
        self.assertEqual('对象范围测试申请', request_obj.name)

    def test_queued_request_cannot_be_retargeted(self):
        request_obj = self.make_request(self.allowed_deploy, status='1')
        request = self.factory.post(
            '/api/deploy/request/ext1/',
            data=json.dumps({
                'id': request_obj.id,
                'deploy_id': self.allowed_deploy.id,
                'name': '排队申请篡改',
                'extra': ['tag', 'v2.0.0'],
            }),
            content_type='application/json',
        )
        request.user = self.scoped_user({'deploy.request.edit'})

        result = self.decode(post_request_ext1(request))

        self.assertIn('未找到可编辑', result['error'])
        request_obj.refresh_from_db()
        self.assertEqual('对象范围测试申请', request_obj.name)

    def test_rollback_and_deploy_metadata_are_scope_filtered(self):
        self.denied_request.status = '3'
        self.denied_request.save(update_fields=('status',))
        rollback_request = self.factory.post(
            '/api/deploy/request/ext1/rollback/',
            data=json.dumps({
                'request_id': self.denied_request.id,
                'name': '越权回滚',
            }),
            content_type='application/json',
        )
        rollback_request.user = self.scoped_user({'deploy.request.do'})
        deploy_info_request = self.factory.get(
            f'/api/app/deploy/{self.denied_deploy.id}/'
        )
        deploy_info_request.user = self.scoped_user(
            {'deploy.request.view'}
        )
        versions_request = self.factory.get(
            f'/api/app/deploy/{self.denied_deploy.id}/versions/'
        )
        versions_request.user = self.scoped_user(
            {'deploy.request.add'}
        )

        rollback = self.decode(post_request_ext1_rollback(rollback_request))
        deploy_info = self.decode(
            get_deploy_info(deploy_info_request, self.denied_deploy.id)
        )
        versions = self.decode(
            get_deploy_versions(versions_request, self.denied_deploy.id)
        )

        self.assertIn('无操作权限', rollback['error'])
        self.assertIn('无操作权限', deploy_info['error'])
        self.assertIn('无操作权限', versions['error'])
        self.assertEqual(
            1,
            DeployRequest.objects.filter(deploy=self.denied_deploy).count(),
        )

    def test_request_rejects_repository_that_did_not_build_successfully(self):
        repository = Repository.objects.create(
            app=self.allowed_app,
            env=self.allowed_env,
            deploy=self.allowed_deploy,
            version='v1.0.0',
            spug_version='failed-repository',
            extra=json.dumps(['tag', 'v1.0.0']),
            status='2',
            created_by=self.creator,
        )
        request = self.factory.post(
            '/api/deploy/request/ext1/',
            data=json.dumps({
                'deploy_id': self.allowed_deploy.id,
                'name': '失败制品复用',
                'extra': ['repository', repository.id],
            }),
            content_type='application/json',
        )
        request.user = self.scoped_user({'deploy.request.add'})

        result = self.decode(post_request_ext1(request))

        self.assertIn('未找到已成功的构建记录', result['error'])
        self.assertFalse(DeployRequest.objects.filter(
            name='失败制品复用'
        ).exists())

    def test_artifact_metadata_must_match_immutable_source(self):
        image_deploy = self.make_deploy(
            self.allowed_app,
            self.allowed_env,
        )
        image_deploy.extend = '3'
        image_deploy.save(update_fields=('extend',))
        image = DockerImage.objects.create(
            app=self.allowed_app,
            env=self.allowed_env,
            deploy=image_deploy,
            version='v2.0.0',
            spug_version='successful-image',
            url='registry.example/app:v2.0.0',
            extra=json.dumps(['tag', 'v2.0.0']),
            status='5',
            created_by=self.creator,
        )
        request_obj = DeployRequest.objects.create(
            deploy=image_deploy,
            docker_image=image,
            name='镜像来源绑定',
            type='1',
            extra=json.dumps(['docker_image', 'tag', 'tampered']),
            host_ids='[]',
            status='1',
            version=image.version,
            spug_version=image.spug_version,
            created_by=self.creator,
        )

        error = get_reused_artifact_error(request_obj)

        self.assertIn('来源信息不一致', error)

    def test_operator_can_resolve_unknown_request_as_success(self):
        request_obj = self.make_request(self.allowed_deploy, status='-2')
        request_obj.failed_at = '2026-07-23 10:00:00'
        request_obj.save(update_fields=('failed_at',))
        request = self.factory.put(
            f'/api/deploy/request/{request_obj.id}/',
            data=json.dumps({'outcome': 'success'}),
            content_type='application/json',
        )
        request.user = self.creator

        result = self.decode(
            RequestDetailView.as_view()(request, r_id=request_obj.id)
        )

        self.assertFalse(result['error'])
        request_obj.refresh_from_db()
        self.assertEqual('3', request_obj.status)
        self.assertIsNone(request_obj.failed_at)
        self.assertTrue(DeployOperationLog.objects.filter(
            target_type='request',
            target_id=request_obj.id,
            action='人工核验结果未知申请：确认发布成功',
        ).exists())

    def test_confirming_unknown_as_failure_restores_timed_retry_policy(self):
        request_obj = self.make_request(self.allowed_deploy, status='-2')
        unknown_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        request_obj.failed_at = unknown_at
        request_obj.save(update_fields=('failed_at',))
        request = self.factory.put(
            f'/api/deploy/request/{request_obj.id}/',
            data=json.dumps({'outcome': 'failure'}),
            content_type='application/json',
        )
        request.user = self.creator

        result = self.decode(
            RequestDetailView.as_view()(request, r_id=request_obj.id)
        )

        self.assertFalse(result['error'])
        request_obj.refresh_from_db()
        self.assertEqual('-3', request_obj.status)
        self.assertEqual(unknown_at, request_obj.failed_at)
        self.assertTrue(get_deploy_retry_info(
            request_obj
        )['retry_allowed'])


class DeployIterationObjectScopeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.creator = User.objects.create(
            username='iteration-scope-admin',
            nickname='迭代管理员',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
            is_supper=True,
        )
        self.env = Environment.objects.create(
            name='迭代授权环境',
            key='iteration-scope-env',
            created_by=self.creator,
        )
        self.other_env = Environment.objects.create(
            name='迭代越权环境',
            key='iteration-denied-env',
            created_by=self.creator,
        )
        self.app = App.objects.create(
            name='迭代授权应用',
            key='iteration-scope-app',
            created_by=self.creator,
        )
        self.other_app = App.objects.create(
            name='迭代越权应用',
            key='iteration-denied-app',
            created_by=self.creator,
        )
        self.target_host = Host.objects.create(
            name='发布目标主机',
            hostname='10.0.0.1',
            port=22,
            username='root',
            created_by=self.creator,
        )
        self.deploy = self.make_deploy(
            self.app,
            self.env,
            [self.target_host.id],
        )
        self.denied_deploy = self.make_deploy(
            self.other_app,
            self.other_env,
            [],
        )
        self.iteration = DeployIteration.objects.create(
            name='对象范围迭代',
            env=self.env,
            created_by=self.creator,
        )
        self.detail = DeployIterationDetail.objects.create(
            iteration=self.iteration,
            deploy=self.deploy,
            version='v1.0.0',
            created_by=self.creator,
        )

    def make_deploy(self, app, env, host_ids, extend='1'):
        return Deploy.objects.create(
            app=app,
            env=env,
            host_ids=json.dumps(host_ids),
            extend=extend,
            is_audit=False,
            rst_notify='[]',
            created_by=self.creator,
        )

    def scoped_user(self, apps=None, envs=None, groups=None):
        return SimpleNamespace(
            id=999,
            nickname='受限用户',
            is_supper=False,
            deploy_perms={
                'apps': set(apps or []),
                'envs': set(envs or []),
            },
            group_perms=list(groups or []),
            has_perms=lambda codes: True,
        )

    def decode(self, response):
        return json.loads(response.content.decode())

    def test_iteration_read_and_create_require_all_app_environment_scope(self):
        user = self.scoped_user()
        read_request = self.factory.get(
            '/api/deploy/iteration/',
            data={'id': self.iteration.id},
        )
        read_request.user = user
        create_request = self.factory.post(
            '/api/deploy/iteration/',
            data=json.dumps({
                'name': '越权创建',
                'env_ids': [self.other_env.id],
                'details': [{
                    'app_id': self.other_app.id,
                    'env_id': self.other_env.id,
                    'version': 'v2.0.0',
                }],
            }),
            content_type='application/json',
        )
        create_request.user = user

        read_result = self.decode(IterationView.as_view()(read_request))
        create_result = self.decode(IterationView.as_view()(create_request))

        self.assertEqual([], read_result['data'])
        self.assertIn('无权访问目标环境', create_result['error'])
        self.assertEqual(1, DeployIteration.objects.count())

    @patch('apps.deploy.views.Thread')
    def test_publish_checks_target_host_before_creating_requests(
            self, thread):
        user = self.scoped_user(
            apps=[self.app.id],
            envs=[self.env.id],
        )
        request = self.factory.post(
            '/api/deploy/iteration/publish/',
            data=json.dumps({
                'iteration_id': self.iteration.id,
                'env_id': self.env.id,
            }),
            content_type='application/json',
        )
        request.user = user

        result = self.decode(IterationPublishView.as_view()(request))

        self.assertEqual('无权访问发布目标主机', result['error'])
        self.assertEqual(0, DeployRequest.objects.count())
        thread.assert_not_called()

    @patch('apps.deploy.views.Thread')
    def test_retry_checks_scope_before_changing_failed_request(
            self, thread):
        failed_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='失败申请',
            type='1',
            extra=json.dumps(['tag', 'v1.0.0']),
            host_ids=self.deploy.host_ids,
            status='-3',
            failed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            created_by=self.creator,
        )
        self.detail.status = '3'
        self.detail.request_id = failed_request.id
        self.detail.save()
        user = self.scoped_user(
            apps=[self.app.id],
            envs=[self.env.id],
        )
        request = self.factory.patch(
            '/api/deploy/iteration/publish/',
            data=json.dumps({'detail_id': self.detail.id}),
            content_type='application/json',
        )
        request.user = user

        result = self.decode(IterationPublishView.as_view()(request))

        self.assertEqual('无权访问发布目标主机', result['error'])
        failed_request.refresh_from_db()
        self.assertEqual('-3', failed_request.status)
        thread.assert_not_called()

    @patch('apps.deploy.views.Thread')
    def test_image_upload_checks_build_host_before_writes(self, thread):
        deploy_group = Group.objects.create(name='发布主机分组')
        deploy_group.hosts.add(self.target_host)
        build_host = Host.objects.create(
            name='镜像构建主机',
            hostname='10.0.0.2',
            port=22,
            username='root',
            created_by=self.creator,
        )
        container_deploy = self.make_deploy(
            self.app,
            self.env,
            [self.target_host.id],
            extend='3',
        )
        DeployExtend3.objects.create(
            deploy=container_deploy,
            git_repo='git@example/repo.git',
            dst_dir='/tmp',
            dst_repo='/tmp/repo',
            versions=3,
            filter_rule='[]',
            build_image_host_id=build_host.id,
            dockerfile_params='[]',
            yaml_params='[]',
        )
        container_detail = DeployIterationDetail.objects.create(
            iteration=self.iteration,
            deploy=container_deploy,
            version='v1.0.0',
            created_by=self.creator,
        )
        user = self.scoped_user(
            apps=[self.app.id],
            envs=[self.env.id],
            groups=[deploy_group.id],
        )
        request = self.factory.post(
            '/api/deploy/iteration/image/',
            data=json.dumps({
                'iteration_id': self.iteration.id,
                'env_id': self.env.id,
            }),
            content_type='application/json',
        )
        request.user = user

        result = self.decode(IterationImageView.as_view()(request))

        self.assertEqual('无权访问镜像构建主机', result['error'])
        container_detail.refresh_from_db()
        self.assertEqual('0', container_detail.image_status)
        self.assertEqual(0, DockerImage.objects.count())
        thread.assert_not_called()

    def test_detail_mutations_require_iteration_scope(self):
        user = self.scoped_user()
        update_request = self.factory.put(
            '/api/deploy/iteration/detail/',
            data=json.dumps({
                'detail_id': self.detail.id,
                'version': 'v9.9.9',
            }),
            content_type='application/json',
        )
        update_request.user = user
        delete_request = self.factory.delete(
            f'/api/deploy/iteration/detail/?detail_id={self.detail.id}'
        )
        delete_request.user = user

        updated = self.decode(
            IterationDetailView.as_view()(update_request)
        )
        deleted = self.decode(
            IterationDetailView.as_view()(delete_request)
        )

        self.assertIn('无操作权限', updated['error'])
        self.assertIn('无操作权限', deleted['error'])
        self.detail.refresh_from_db()
        self.assertEqual('v1.0.0', self.detail.version)

    @patch('apps.deploy.utils.dispatch')
    def test_background_dispatch_rechecks_revoked_scope(self, dispatch):
        actor = User.objects.create(
            username='revoked-iteration-operator',
            nickname='已撤权用户',
            password_hash='-',
            access_token='',
            last_login='',
            last_ip='',
        )
        deploy_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='等待后台复核',
            type='1',
            extra=json.dumps(['tag', 'v1.0.0']),
            host_ids=self.deploy.host_ids,
            status='2',
            created_by=self.creator,
            do_by=actor,
        )
        self.detail.status = '1'
        self.detail.request_id = deploy_request.id
        self.detail.save()

        dispatch_iteration_request(deploy_request.id, actor.id)

        dispatch.assert_not_called()
        deploy_request.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual('-3', deploy_request.status)
        self.assertEqual('3', self.detail.status)

    def test_stale_running_request_becomes_unknown_and_blocks_replay(self):
        deploy_request = DeployRequest.objects.create(
            deploy=self.deploy,
            name='迭代：长时间发布',
            type='1',
            extra=json.dumps(['tag', 'v1.0.0']),
            host_ids=self.deploy.host_ids,
            status='2',
            do_at='2020-01-01 00:00:00',
            created_by=self.creator,
            do_by=self.creator,
        )
        self.detail.status = '1'
        self.detail.request_id = deploy_request.id
        self.detail.save()

        cleaned = _cleanup_stale_requests(self.env.id)

        deploy_request.refresh_from_db()
        self.detail.refresh_from_db()
        self.iteration.refresh_from_db()
        self.assertEqual(1, cleaned)
        self.assertEqual('-2', deploy_request.status)
        self.assertEqual('4', self.detail.status)
        self.assertEqual('-2', self.iteration.status)
        _, unresolved = lock_deploy_and_get_running_request(self.deploy.id)
        self.assertEqual(deploy_request.id, unresolved.id)
