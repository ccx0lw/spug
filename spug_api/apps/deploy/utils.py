# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django_redis import get_redis_connection
from django.core.exceptions import MultipleObjectsReturned
from django.conf import settings
from django.db import close_old_connections, transaction
from libs.utils import AttrDict, human_time, human_datetime, parse_time, render_str, render_str_or_empty
from apps.host.models import Host
from apps.config.utils import compose_configs
from apps.config.models import ContainerRepository, FileTemplate
from apps.repository.models import Repository
from apps.repository.utils import dispatch as build_repository
from apps.deploy.models import DeployRequest
from apps.deploy.helper import Helper, SpugError
from apps.docker_image.models import DockerImage
from apps.docker_image.utils import dispatch as build_docker_image
from concurrent import futures
from functools import partial
from datetime import datetime, timedelta
import json
import uuid
import os

REPOS_DIR = settings.REPOS_DIR
BUILD_DIR = settings.BUILD_DIR


def scoped_deploy_requests(user):
    queryset = DeployRequest.objects.all()
    if user.is_supper:
        return queryset
    perms = user.deploy_perms
    return queryset.filter(
        deploy__app_id__in=perms['apps'],
        deploy__env_id__in=perms['envs'],
    )


def lock_deploy_and_get_running_request(deploy_id):
    """锁定应用在指定环境的发布配置，并返回当前正在发布的申请。

    调用方必须处于数据库事务中，所有发布入口通过同一行锁串行化“检查+启动”。
    """
    from apps.app.models import Deploy

    deploy = Deploy.objects.select_for_update().select_related('app', 'env').filter(
        pk=deploy_id
    ).first()
    if not deploy:
        return None, None
    # 使用锁定读获取最新已提交状态，避免 MySQL 事务快照读取到旧数据。
    running_request = DeployRequest.objects.select_for_update().filter(
        deploy_id=deploy_id,
        status='2',
    ).only('id').first()
    return deploy, running_request


def get_running_deploy_error(deploy):
    return f'应用【{deploy.app.name}】在【{deploy.env.name}】环境正在发布，请等待当前发布完成'


def get_deploy_retry_info(req, now=None):
    """返回环境级发布失败重试窗口信息。"""
    now = now or datetime.now()
    env = req.deploy.env
    retry_hours = getattr(env, 'deploy_retry_hours', 24)
    info = {
        'retry_allowed': False,
        'retry_deadline': None,
        'retry_hours': retry_hours,
        'retry_error': '',
    }

    if req.status not in ('-3', '-2'):
        info['retry_error'] = '当前发布申请不是失败状态，不能重试'
        return info
    if retry_hours <= 0:
        info['retry_error'] = f'环境【{env.name}】已禁止发布失败后重试'
        return info

    failed_time = None
    for value in (getattr(req, 'failed_at', None), req.do_at, req.created_at):
        if not value:
            continue
        try:
            failed_time = parse_time(value)
            break
        except (TypeError, ValueError):
            continue
    if failed_time is None:
        info['retry_error'] = '无法确定发布失败时间，不能重试'
        return info

    deadline = failed_time + timedelta(hours=retry_hours)
    info['retry_deadline'] = human_datetime(deadline)
    if now <= deadline:
        info['retry_allowed'] = True
    else:
        info['retry_error'] = (
            f'发布失败重试有效期为{retry_hours}小时，已于{info["retry_deadline"]}过期'
        )
    return info


def get_deploy_retry_error(req, now=None):
    info = get_deploy_retry_info(req, now=now)
    return '' if info['retry_allowed'] else info['retry_error']


def get_cross_iteration_warnings(iteration, details):
    """生成迭代明细的跨迭代版本提示，不参与发布准入判断。"""
    from django.db.models import OuterRef, Q, Subquery
    from apps.app.models import Deploy
    from apps.deploy.models import DeployIterationDetail

    details = list(details)
    deploy_ids = {detail.deploy_id for detail in details if detail.deploy_id}
    if not deploy_ids:
        return {}

    # do_at 会在失败重试时刷新，比申请 ID 更接近服务最后一次实际发布成功的顺序。
    latest_request = DeployRequest.objects.filter(
        deploy_id=OuterRef('pk'),
        status='3',
        type__in=('1', '2', '3'),
        version__isnull=False,
    ).order_by('-do_at', '-id')
    latest_request_ids = [
        request_id
        for request_id in Deploy.objects.filter(pk__in=deploy_ids).annotate(
            latest_request_id=Subquery(latest_request.values('id')[:1])
        ).values_list('latest_request_id', flat=True)
        if request_id
    ]
    latest_requests = DeployRequest.objects.filter(
        pk__in=latest_request_ids
    ).select_related('created_by')
    latest_request_by_deploy = {req.deploy_id: req for req in latest_requests}

    latest_iteration_details = DeployIterationDetail.objects.filter(
        request_id__in=latest_request_ids
    ).select_related('iteration')
    latest_detail_by_request = {
        detail.request_id: detail for detail in latest_iteration_details
    }

    # 未完成的其他迭代始终展示；历史记录只展示最近一次成功发布，避免信息过载。
    related_details = list(DeployIterationDetail.objects.filter(
        deploy_id__in=deploy_ids,
        status__in=('0', '1'),
    ).exclude(
        iteration_id=iteration.id
    ).select_related('iteration').order_by('-iteration_id', 'sequence'))
    max_retry_hours = max(
        (
            getattr(detail.deploy.env, 'deploy_retry_hours', 24)
            for detail in details
            if detail.deploy and detail.deploy.env
        ),
        default=0,
    )
    retryable_requests = {}
    if max_retry_hours > 0:
        retry_threshold = human_datetime(
            datetime.now() - timedelta(hours=max_retry_hours)
        )
        failed_requests = DeployRequest.objects.filter(
            deploy_id__in=deploy_ids,
            status__in=('-3', '-2'),
        ).filter(
            Q(failed_at__gte=retry_threshold) | Q(do_at__gte=retry_threshold)
        ).select_related('deploy__env')
        for req in failed_requests:
            retry_info = get_deploy_retry_info(req)
            if retry_info['retry_allowed']:
                retryable_requests[req.id] = retry_info
        if retryable_requests:
            related_details.extend(DeployIterationDetail.objects.filter(
                deploy_id__in=deploy_ids,
                request_id__in=retryable_requests,
                status='3',
            ).exclude(
                iteration_id=iteration.id
            ).select_related('iteration'))

    related_request_ids = {
        detail.request_id for detail in related_details if detail.request_id
    }
    related_requests = {
        req.id: req for req in DeployRequest.objects.filter(
            pk__in=related_request_ids
        )
    }
    related_by_deploy = {}
    for detail in related_details:
        req = related_requests.get(detail.request_id)
        effective_status = get_iteration_detail_status(req.status) if req else detail.status
        retry_info = retryable_requests.get(detail.request_id)
        if effective_status not in ('0', '1') and not (
            effective_status == '3' and retry_info
        ):
            continue
        related_by_deploy.setdefault(detail.deploy_id, []).append({
            'iteration_id': detail.iteration_id,
            'iteration_name': detail.iteration.name,
            'iteration_status': detail.iteration.status,
            'iteration_status_alias': detail.iteration.get_status_display(),
            'detail_status': effective_status,
            'detail_status_alias': dict(
                DeployIterationDetail.STATUS_CHOICES
            ).get(effective_status, detail.get_status_display()),
            'version': detail.version,
            'request_id': detail.request_id,
            'request_status': req.status if req else None,
            'request_status_alias': req.get_status_display() if req else None,
            'request_retry_allowed': bool(retry_info),
            'request_retry_deadline': (
                retry_info['retry_deadline'] if retry_info else None
            ),
            'is_later_iteration': detail.iteration_id > iteration.id,
        })

    result = {}
    for detail in details:
        messages = []
        level = 'none'
        kind = 'none'
        label = ''
        latest_success = None

        latest_req = latest_request_by_deploy.get(detail.deploy_id)
        latest_detail = latest_detail_by_request.get(latest_req.id) if latest_req else None
        # 当前明细自己的成功记录不属于跨迭代提示。
        is_current_iteration_release = (
            latest_detail is not None
            and latest_detail.iteration_id == iteration.id
        )
        if latest_req and not is_current_iteration_release:
            is_same_version = latest_req.version == detail.version
            latest_success = {
                'request_id': latest_req.id,
                'request_name': latest_req.name,
                'version': latest_req.version,
                'do_at': latest_req.do_at,
                'created_by_user': latest_req.created_by.nickname if latest_req.created_by else '',
                'iteration_id': latest_detail.iteration_id if latest_detail else None,
                'iteration_name': latest_detail.iteration.name if latest_detail else None,
                'is_later_iteration': (
                    latest_detail.iteration_id > iteration.id if latest_detail else False
                ),
                'is_same_version': is_same_version,
            }
            if is_same_version:
                level = 'info'
                kind = 'same_version'
                label = '相同版本'
                messages.append(f'最近成功发布版本同为 {detail.version}')
            else:
                level = 'warning'
                kind = 'version_switch'
                label = '版本切换提示'
                if latest_detail and latest_detail.iteration_id > iteration.id:
                    messages.append(
                        f'后续迭代【{latest_detail.iteration.name}】已发布 '
                        f'{latest_req.version}，本次将切换为 {detail.version}'
                    )
                else:
                    messages.append(
                        f'最近成功版本为 {latest_req.version}，本次将切换为 '
                        f'{detail.version}，可能属于回滚'
                    )

        # 跨迭代重复只对仍可执行发布动作的明细有意义。失败且已超过重试
        # 有效期的明细不能再次发布，不应再与其他迭代形成重复提示。
        can_publish_again = detail.status in ('0', '1') or (
            detail.status == '3' and detail.request_id in retryable_requests
        )
        related_iterations = (
            related_by_deploy.get(detail.deploy_id, [])
            if can_publish_again else []
        )
        publishing_iterations = [
            item for item in related_iterations if item['detail_status'] == '1'
        ]
        retryable_iterations = [
            item for item in related_iterations if item['request_retry_allowed']
        ]
        if publishing_iterations:
            level = 'danger'
            kind = 'active_iteration'
            label = '其他迭代发布中'
            names = '、'.join(
                f'【{item["iteration_name"]}】{item["version"]}'
                for item in publishing_iterations[:3]
            )
            messages.insert(0, f'其他迭代正在处理同一服务：{names}')
        elif related_iterations:
            if level in ('none', 'info'):
                level = 'warning'
                kind = 'cross_iteration'
                label = '跨迭代重复'
            pending_iterations = [
                item for item in related_iterations if item['detail_status'] == '0'
            ]
            if pending_iterations:
                names = '、'.join(
                    f'【{item["iteration_name"]}】{item["version"]}'
                    for item in pending_iterations[:3]
                )
                messages.append(f'其他待发布迭代也包含该服务：{names}')
            if retryable_iterations:
                names = '、'.join(
                    f'【{item["iteration_name"]}】{item["version"]}'
                    for item in retryable_iterations[:3]
                )
                messages.append(f'其他失败迭代仍可重试该服务：{names}')

        result[detail.id] = {
            'has_warning': bool(messages),
            'level': level,
            'kind': kind,
            'label': label,
            'message': '；'.join(messages),
            'latest_success': latest_success,
            'related_iterations': related_iterations,
        }
    return result


def dispatch(req, fail_mode=False):
    rds = get_redis_connection()
    rds_key = f'{settings.REQUEST_KEY}:{req.id}'
    
    if fail_mode:
        req.host_ids = req.fail_host_ids
    req.fail_mode = fail_mode
    req.host_ids = json.loads(req.host_ids)
    req.fail_host_ids = req.host_ids[:]
    helper = Helper.make(rds, rds_key, req.host_ids if fail_mode else None)

    try:
        api_token = uuid.uuid4().hex
        rds.setex(api_token, 60 * 60, f'{req.deploy.app_id},{req.deploy.env_id}')
        env = AttrDict(
            SPUG_APP_NAME=req.deploy.app.name,
            SPUG_APP_KEY=req.deploy.app.key,
            SPUG_APP_ID=str(req.deploy.app_id),
            SPUG_REQUEST_ID=str(req.id),
            SPUG_REQUEST_NAME=req.name,
            SPUG_DEPLOY_ID=str(req.deploy.id),
            SPUG_ENV_ID=str(req.deploy.env_id),
            SPUG_ENV_KEY=req.deploy.env.key,
            SPUG_VERSION=req.version,
            SPUG_BUILD_VERSION=req.spug_version,
            SPUG_DEPLOY_TYPE=req.type,
            SPUG_API_TOKEN=api_token,
            SPUG_REPOS_DIR=REPOS_DIR,
        )
        # append configs
        configs = compose_configs(req.deploy.app, req.deploy.env_id)
        configs_env = {f'{k.upper()}': v for k, v in configs.items()}
        env.update(configs_env)

        if req.deploy.extend == '1':
            _ext1_deploy(req, helper, env)
        elif req.deploy.extend == '3':
            if req.type == '0' :
                _ext3_restart(req, helper, env)
            else:
                _ext3_deploy(req, helper, env)
        else:
            _ext2_deploy(req, helper, env)
        req.status = '3'
    except Exception as e:
        req.status = '-3'
        raise e
    finally:
        close_old_connections()
        failed_at = human_datetime() if req.status == '-3' else None
        req.failed_at = failed_at
        DeployRequest.objects.filter(pk=req.id).update(
            status=req.status,
            repository=req.repository,
            docker_image=req.docker_image,
            fail_host_ids=json.dumps(req.fail_host_ids),
            failed_at=failed_at,
        )
        # 需求2: 发布完成后同步更新迭代明细状态
        _update_iteration_detail_status(req)
        # 发布完成后调度同迭代同环境下排队等待的发布任务
        try:
            _dispatch_pending_iteration_requests(req)
        except Exception:
            pass
        helper.clear()
        Helper.send_deploy_notify(req)


def _update_iteration_detail_status(req):
    """发布完成后同步更新迭代明细状态和迭代整体状态"""
    try:
        from apps.deploy.models import DeployIterationDetail
        # 查找关联到这个发布申请的迭代明细
        details = DeployIterationDetail.objects.filter(request_id=req.id)
        if details.exists():
            detail_status = get_iteration_detail_status(req.status)
            if detail_status is None:
                return

            iteration_ids = set(details.values_list('iteration_id', flat=True))
            details.update(status=detail_status)
            
            # 更新迭代的整体状态
            for iteration_id in iteration_ids:
                update_iteration_overall_status(iteration_id)
    except Exception as e:
        import logging
        logging.error(f'更新迭代明细发布状态失败: {e}')


def get_iteration_detail_status(request_status):
    """将发布申请状态转换为迭代明细状态。"""
    if request_status == '3':
        return '2'
    if request_status in ('-3', '-2'):
        return '3'
    if request_status in ('1', '2'):
        return '1'
    if request_status in ('-1', '0'):
        return '0'
    return None


def reconcile_iteration_detail_statuses(details):
    """以发布申请为准校准迭代明细，补偿发布完成后的偶发同步失败。"""
    from apps.deploy.models import DeployIterationDetail

    details = list(details)
    request_ids = {detail.request_id for detail in details if detail.request_id}
    if not request_ids:
        return set()

    request_statuses = dict(DeployRequest.objects.filter(
        pk__in=request_ids
    ).values_list('id', 'status'))
    details_to_update = []
    iteration_ids = set()
    for detail in details:
        request_status = request_statuses.get(detail.request_id)
        expected_status = get_iteration_detail_status(request_status)
        if expected_status is None or detail.status == expected_status:
            continue
        detail.status = expected_status
        details_to_update.append(detail)
        iteration_ids.add(detail.iteration_id)

    if not details_to_update:
        return set()

    DeployIterationDetail.objects.bulk_update(details_to_update, ['status'])
    for iteration_id in iteration_ids:
        update_iteration_overall_status(iteration_id)
    return iteration_ids


def get_iteration_overall_status(detail_statuses):
    """根据全部明细状态计算迭代主状态；全部待发布时保持当前主状态。"""
    detail_statuses = list(detail_statuses)
    total_count = len(detail_statuses)
    if total_count == 0:
        return None

    success_count = detail_statuses.count('2')
    failed_count = detail_statuses.count('3')
    publishing_count = detail_statuses.count('1')
    pending_count = detail_statuses.count('0')

    if success_count == total_count:
        return '2'
    if failed_count > 0 and pending_count == 0 and publishing_count == 0:
        return '-1' if success_count > 0 else '-3'
    if publishing_count > 0:
        return '1'
    if pending_count < total_count and (success_count > 0 or failed_count > 0):
        return '1'
    return None


def get_iteration_detail_remove_error(detail):
    """返回迭代明细不可移除的原因，允许移除时返回 None。"""
    if detail.request_id:
        return '该应用已关联发布申请，不能从迭代中移除'
    if detail.status != '0':
        return '只有待发布的应用才能从迭代中移除'
    if detail.image_status != '0' or detail.docker_image_id:
        return '该应用已开始预传镜像，不能从迭代中移除'
    return None


def update_iteration_overall_status(iteration_id):
    """更新迭代的整体状态"""
    try:
        from apps.deploy.models import DeployIteration
        iteration = DeployIteration.objects.filter(pk=iteration_id).first()
        if not iteration:
            return

        detail_statuses = iteration.details.values_list('status', flat=True)
        new_status = get_iteration_overall_status(detail_statuses)
        
        if new_status and iteration.status != new_status:
            iteration.status = new_status
            iteration.save()
        return new_status or iteration.status
    except Exception as e:
        import logging
        logging.error(f'更新迭代整体状态失败: {e}')
        return None
        

def _dispatch_pending_iteration_requests(req):
    """发布完成后，检查并调度同迭代同环境下排队等待的发布申请"""
    try:
        from apps.deploy.models import DeployIterationDetail
        from apps.config.models import Environment

        # 找到关联到这个发布申请的迭代明细
        detail = DeployIterationDetail.objects.filter(request_id=req.id).first()
        if not detail:
            return

        iteration = detail.iteration
        env_id = req.deploy.env_id

        _try_dispatch_queued_requests(iteration, env_id)
    except Exception as e:
        import logging
        logging.error(f'调度迭代待发布申请失败: {e}')


def _cleanup_stale_requests(env_id, stale_minutes=60):
    """清理僵死的发布申请（超过指定时间仍为发布中状态）
    处理场景：SSH连接中断、命令假死、进程崩溃/重启导致发布申请卡在 status='2'
    """
    from datetime import datetime, timedelta
    import logging
    logger = logging.getLogger(__name__)

    threshold = human_datetime(datetime.now() - timedelta(minutes=stale_minutes))

    # 查找超时的迭代发布申请（名称以"迭代"开头的）
    stale_requests = DeployRequest.objects.filter(
        deploy__env_id=env_id,
        status='2',
        do_at__lt=threshold,
        name__startswith='迭代'
    )

    cleaned = 0
    for stale_req in stale_requests:
        logger.warning(
            f'检测到僵死的发布申请: id={stale_req.id}, '
            f'app={stale_req.deploy.app.name}, do_at={stale_req.do_at}, '
            f'已超过{stale_minutes}分钟，标记为失败'
        )
        stale_req.status = '-3'
        stale_req.failed_at = human_datetime()
        stale_req.save()
        # 同步更新迭代明细状态
        _update_iteration_detail_status(stale_req)
        cleaned += 1

    if cleaned:
        logger.info(f'环境 env_id={env_id} 清理了 {cleaned} 个僵死的发布申请')
    return cleaned


def _try_dispatch_queued_requests(iteration, env_id):
    """尝试调度指定迭代指定环境下排队等待的发布申请，含僵死清理"""
    from apps.deploy.models import DeployIterationDetail
    from apps.config.models import Environment
    from threading import Thread
    import logging
    logger = logging.getLogger(__name__)

    env = Environment.objects.filter(pk=env_id).first()

    # 如果 env.conc_num <= 0 则不限制并发，不需要调度
    if not env or env.conc_num <= 0:
        return

    # 先清理僵死的发布申请，释放槽位
    _cleanup_stale_requests(env_id)

    # 计算当前环境可用槽位
    current_count = DeployRequest.objects.filter(deploy__env_id=env_id, status='2').count()
    available_slots = env.conc_num - current_count
    if available_slots <= 0:
        return

    # 找到同迭代同环境下状态为待发布(status='1')的发布申请，按明细sequence排序
    pending_details = DeployIterationDetail.objects.filter(
        iteration=iteration,
        deploy__env_id=env_id,
    ).exclude(request_id__isnull=True).order_by('sequence')

    dispatched = 0
    for pd in pending_details:
        if dispatched >= available_slots:
            break
        if not pd.request_id:
            continue
        with transaction.atomic():
            request_snapshot = DeployRequest.objects.filter(
                pk=pd.request_id,
                status='1',
            ).only('id', 'deploy_id').first()
            if not request_snapshot:
                continue

            deploy, running_request = lock_deploy_and_get_running_request(
                request_snapshot.deploy_id
            )
            if not deploy or running_request:
                continue
            pending_req = DeployRequest.objects.select_for_update().filter(
                pk=request_snapshot.id,
                status='1',
            ).first()
            if not pending_req:
                continue

            pending_req.status = '2'
            pending_req.do_at = human_datetime()
            pending_req.save()

            logger.info(
                f'调度排队发布申请: id={pending_req.id}, '
                f'app={deploy.app.name}'
            )
            transaction.on_commit(
                lambda req=pending_req: Thread(
                    target=dispatch,
                    args=(req, False),
                ).start()
            )
            dispatched += 1
        

def _recover_on_startup():
    """服务启动时恢复被中断的迭代发布队列
    处理场景：整个 Spug 服务重启后，之前正在发布中(status='2')的线程已死，排队中(status='1')的任务无人调度。
    使用 Redis 锁确保多个 gunicorn worker 中只有一个执行恢复。
    """
    import logging
    from apps.deploy.models import DeployIterationDetail, DeployIteration
    from apps.config.models import Environment
    from threading import Thread
    from django.db import close_old_connections

    logger = logging.getLogger(__name__)

    # 使用 Redis 锁确保只有一个进程执行恢复，防止多 worker 重复调度
    rds = get_redis_connection()
    lock_key = 'spug:iteration:startup_recovery_lock'
    # 120秒过期，防止锁意外未释放
    if not rds.set(lock_key, '1', nx=True, ex=120):
        logger.info('另一个进程已在执行启动恢复，跳过')
        return

    try:
        close_old_connections()
        logger.info('开始执行迭代发布启动恢复...')

        # 第一步：将所有迭代相关的 status='2'(发布中) 的申请标记为失败
        # 服务重启后，这些请求的发布线程已经死亡，无法继续执行
        stuck_requests = DeployRequest.objects.filter(
            status='2',
            name__startswith='迭代'
        )
        stuck_count = 0
        affected_iteration_ids = set()
        for req in stuck_requests:
            logger.warning(
                f'启动恢复: 标记被中断的发布申请为失败 id={req.id}, '
                f'app={req.deploy.app.name}, env={req.deploy.env.name}'
            )
            req.status = '-3'
            req.failed_at = human_datetime()
            req.save()
            # 同步更新迭代明细状态
            details = DeployIterationDetail.objects.filter(request_id=req.id)
            for detail in details:
                detail.status = '3'  # 发布失败
                detail.save()
                affected_iteration_ids.add(detail.iteration_id)
            stuck_count += 1

        if stuck_count:
            logger.info(f'启动恢复: 已标记 {stuck_count} 个被中断的发布申请为失败')

        # 更新受影响的迭代整体状态
        for iteration_id in affected_iteration_ids:
            update_iteration_overall_status(iteration_id)

        # 第二步：找到所有有排队中请求(status='1')的迭代，按并发限制重新调度
        queued_details = DeployIterationDetail.objects.filter(
            status='1'
        ).exclude(
            request_id__isnull=True
        ).select_related('iteration', 'deploy', 'deploy__env')

        # 按 (iteration_id, env_id) 分组
        iteration_env_pairs = set()
        for detail in queued_details:
            # 确认关联的发布申请确实是待发布状态
            if detail.request_id:
                req_exists = DeployRequest.objects.filter(
                    pk=detail.request_id, status='1'
                ).exists()
                if req_exists and detail.deploy:
                    iteration_env_pairs.add((detail.iteration_id, detail.deploy.env_id))

        dispatched_total = 0
        for iteration_id, env_id in iteration_env_pairs:
            iteration = DeployIteration.objects.filter(pk=iteration_id).first()
            if not iteration:
                continue
            env = Environment.objects.filter(pk=env_id).first()
            if not env or env.conc_num <= 0:
                # 不限并发，全部调度
                pending_details = DeployIterationDetail.objects.filter(
                    iteration=iteration,
                    deploy__env_id=env_id,
                ).exclude(request_id__isnull=True).order_by('sequence')
                for pd in pending_details:
                    if not pd.request_id:
                        continue
                    with transaction.atomic():
                        request_snapshot = DeployRequest.objects.filter(
                            pk=pd.request_id,
                            status='1',
                        ).only('id', 'deploy_id').first()
                        if not request_snapshot:
                            continue
                        deploy, running_request = lock_deploy_and_get_running_request(
                            request_snapshot.deploy_id
                        )
                        if not deploy or running_request:
                            continue
                        pending_req = DeployRequest.objects.select_for_update().filter(
                            pk=request_snapshot.id,
                            status='1',
                        ).first()
                        if not pending_req:
                            continue
                        pending_req.status = '2'
                        pending_req.do_at = human_datetime()
                        pending_req.save()
                        logger.info(
                            f'启动恢复调度: id={pending_req.id}, '
                            f'app={deploy.app.name}'
                        )
                        transaction.on_commit(
                            lambda req=pending_req: Thread(
                                target=dispatch,
                                args=(req, False),
                            ).start()
                        )
                        dispatched_total += 1
            else:
                # 有并发限制，使用 _try_dispatch_queued_requests
                try:
                    _try_dispatch_queued_requests(iteration, env_id)
                except Exception as e:
                    logger.error(f'启动恢复调度失败: iteration={iteration_id}, env={env_id}, error={e}')

        logger.info(f'迭代发布启动恢复完成: 清理了 {stuck_count} 个中断请求，恢复了 {len(iteration_env_pairs)} 组调度')
    except Exception as e:
        logger.error(f'启动恢复执行失败: {e}')
    finally:
        try:
            rds.delete(lock_key)
        except Exception:
            pass
        

def _ext1_deploy(req, helper, env):
    if not req.repository_id:
        rep = Repository(
            app_id=req.deploy.app_id,
            env_id=req.deploy.env_id,
            deploy_id=req.deploy_id,
            version=req.version,
            spug_version=req.spug_version,
            extra=req.extra,
            remarks='SPUG AUTO MAKE',
            created_by_id=req.created_by_id
        )
        build_repository(rep, helper)
        req.repository = rep
    extras = json.loads(req.extra)
    if extras[0] == 'repository':
        extras = extras[1:]
    if extras[0] == 'branch':
        env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
    else:
        env.update(SPUG_GIT_TAG=extras[1])
    if req.deploy.is_parallel:
        threads, latest_exception = [], None
        max_workers = max(10, os.cpu_count() * 5)
        with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for h_id in req.host_ids:
                new_env = AttrDict(env.items())
                t = executor.submit(_deploy_ext1_host, req, helper, h_id, new_env)
                t.h_id = h_id
                threads.append(t)
            for t in futures.as_completed(threads):
                exception = t.exception()
                if exception:
                    latest_exception = exception
                    if not isinstance(exception, SpugError):
                        helper.send_error(t.h_id, f'Exception: {exception}', False)
                else:
                    req.fail_host_ids.remove(t.h_id)
        if latest_exception:
            raise latest_exception
    else:
        host_ids = sorted(req.host_ids, reverse=True)
        while host_ids:
            h_id = host_ids.pop()
            new_env = AttrDict(env.items())
            try:
                _deploy_ext1_host(req, helper, h_id, new_env)
                req.fail_host_ids.remove(h_id)
            except Exception as e:
                helper.send_error(h_id, f'Exception: {e}', False)
                for h_id in host_ids:
                    helper.send_error(h_id, '终止发布', False)
                raise e


def _ext2_deploy(req, helper, env):
    extend, step = req.deploy.extend_obj, 1
    host_actions = json.loads(extend.host_actions)
    server_actions = json.loads(extend.server_actions)
    env.update({'SPUG_RELEASE': req.version})
    if req.version:
        for index, value in enumerate(req.version.split()):
            env.update({f'SPUG_RELEASE_{index + 1}': value})

    if not req.fail_mode:
        helper.send_info('local', f'\033[32m完成√\033[0m\r\n')
        for action in server_actions:
            helper.send_step('local', step, f'{human_time()} {action["title"]}...\r\n')
            helper.local(f'cd /tmp && {action["data"]}', env)
            step += 1

    for action in host_actions:
        if action.get('type') == 'transfer':
            action['src'] = render_str(action.get('src', '').strip().rstrip('/'), env)
            action['dst'] = render_str(action['dst'].strip().rstrip('/'), env)
            if action.get('src_mode') == '1':  # upload when publish
                extra = json.loads(req.extra)
                if 'name' in extra:
                    action['name'] = extra['name']
                break
            helper.send_step('local', step, f'{human_time()} 检测到来源为本地路径的数据传输动作，执行打包...   \r\n')
            action['src'] = action['src'].rstrip('/ ')
            action['dst'] = action['dst'].rstrip('/ ')
            if not action['src'] or not action['dst']:
                helper.send_error('local', f'Invalid path for transfer, src: {action["src"]} dst: {action["dst"]}')
            if not os.path.exists(action['src']):
                helper.send_error('local', f'No such file or directory: {action["src"]}')
            is_dir, exclude = os.path.isdir(action['src']), ''
            sp_dir, sd_dst = os.path.split(action['src'])
            contain = sd_dst
            if action['mode'] != '0' and is_dir:
                files = helper.parse_filter_rule(action['rule'], ',', env)
                if files:
                    if action['mode'] == '1':
                        contain = ' '.join(f'{sd_dst}/{x}' for x in files)
                    else:
                        excludes = []
                        for x in files:
                            if x.startswith('/'):
                                excludes.append(f'--exclude={sd_dst}{x}')
                            else:
                                excludes.append(f'--exclude={x}')
                        exclude = ' '.join(excludes)
            tar_gz_file = f'{req.spug_version}.tar.gz'
            helper.local(f'cd {sp_dir} && tar -zcf {tar_gz_file} {exclude} {contain}')
            helper.send_info('local', f'{human_time()} \033[32m完成√\033[0m\r\n')
            helper.add_callback(partial(os.remove, os.path.join(sp_dir, tar_gz_file)))
            break
    helper.send_step('local', 100, '')

    if host_actions:
        if req.deploy.is_parallel:
            threads, latest_exception = [], None
            max_workers = max(10, os.cpu_count() * 5)
            with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                for h_id in req.host_ids:
                    new_env = AttrDict(env.items())
                    t = executor.submit(_deploy_ext2_host, helper, h_id, host_actions, new_env, req.spug_version)
                    t.h_id = h_id
                    threads.append(t)
                for t in futures.as_completed(threads):
                    exception = t.exception()
                    if exception:
                        latest_exception = exception
                        if not isinstance(exception, SpugError):
                            helper.send_error(t.h_id, f'Exception: {exception}', False)
                    else:
                        req.fail_host_ids.remove(t.h_id)
            if latest_exception:
                raise latest_exception
        else:
            host_ids = sorted(req.host_ids, reverse=True)
            while host_ids:
                h_id = host_ids.pop()
                new_env = AttrDict(env.items())
                try:
                    _deploy_ext2_host(helper, h_id, host_actions, new_env, req.spug_version)
                    req.fail_host_ids.remove(h_id)
                except Exception as e:
                    helper.send_error(h_id, f'Exception: {e}', False)
                    for h_id in host_ids:
                        helper.send_error(h_id, '终止发布', False)
                    raise e
    else:
        req.fail_host_ids = []
        helper.send_step('local', 100, f'\r\n{human_time()} ** 发布成功 **')


def _ext3_deploy(req, helper, env):
    extras = json.loads(req.extra)
    
    if extras[0] != 'docker_image':
        if not req.repository_id:
            rep = Repository(
                app_id=req.deploy.app_id,
                env_id=req.deploy.env_id,
                deploy_id=req.deploy_id,
                version=req.version,
                spug_version=req.spug_version,
                extra=req.extra,
                remarks='SPUG AUTO MAKE',
                created_by_id=req.created_by_id
            )
            build_repository(rep, helper)
            req.repository = rep
        else:
            helper.send_info('local', f'\r\n \033[32m使用构建仓库\033[0m \r\n id:[{req.repository_id}] \r\n 环境:[{req.repository.env.name}] \r\n 版本:[{req.repository.version}] \r\n 创建时间:[{req.repository.created_at}] \r\n 创建人:[{req.repository.created_by.nickname}] \r\n 备注:[{req.repository.remarks}] \r\n \033[32m完成√\033[0m\r\n')
    
    if extras[0] == 'repository':
        extras = extras[1:]
    if extras[0] == 'branch':
        env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
    if extras[0] == 'docker_image':
        extras = extras[1:]
        # 设置变量
        if extras[0] == 'repository':
                extras = extras[1:]
        if extras[0] == 'branch':
            env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
        else:
            env.update(SPUG_GIT_TAG=extras[1])
    else:
        env.update(SPUG_GIT_TAG=extras[1])
        
    extend = req.deploy.extend_obj
    
    image_version = render_str_or_empty(extend.image_version, env)
    # 编译镜像的环境变量
    env.update(SPUG_IMAGE_NAME=extend.image_name)
    env.update(SPUG_IMAGE_VERSION=image_version)
    # 查询镜像的仓库
    try:
        container = ContainerRepository.objects.get(env_id=req.deploy.env_id)
    except ContainerRepository.DoesNotExist:
        container = None  # 或者你可以处理不存在的情况
        helper.send_info('image', f'\r\n{human_time()} \033[31m[{req.deploy.env.name}]镜像的仓库配置不存在, 请检查容器仓库对应的环境配置是否存在\033[0m        ')
        raise Exception("镜像的仓库配置不存在, 请检查容器仓库对应的环境配置是否存在")
    except MultipleObjectsReturned:
        # 处理存在多个对象的情况
        helper.send_error('image', f'\033[31m异常x\033[0m\r\n{human_time()} \033[31m镜像仓库配置，存在多条匹配的数据...\033[0m        ')
        raise Exception("镜像仓库配置，存在多条匹配的数据")
    
    if container:
        env.update(SPUG_CONTAINER_REPOSITORY=container.repository)
        env.update(SPUG_CONTAINER_REPOSITORY_NAME_PREFIX=container.repository_name_prefix)
    else:
        env.update(SPUG_CONTAINER_REPOSITORY='')
        env.update(SPUG_CONTAINER_REPOSITORY_NAME_PREFIX='')
    
    # 添加Dockerfile变量
    if extend.dockerfile_params:
        dockerfile_params = json.loads(extend.dockerfile_params)
        if dockerfile_params:
            for d in dockerfile_params:
                for key, value in d.items():
                    env[key]=value
        
    # 镜像编译阶段
    if not req.docker_image_id:
        rep = DockerImage(
            app_id=req.deploy.app_id,
            env_id=req.deploy.env_id,
            deploy_id=req.deploy_id,
            version=req.version,
            spug_version=req.spug_version,
            extra=req.extra,
            remarks='SPUG AUTO MAKE',
            created_by_id=req.created_by_id,
            repository=req.repository
        )
        new_env = AttrDict(env.items())
        build_docker_image(rep, helper, new_env)
        req.docker_image = rep
    else:
        helper.send_info('image', f'\r\n \033[32m使用镜像仓库\033[0m \r\n id:[{req.docker_image_id}] \r\n 环境:[{req.docker_image.env.name}] \r\n 版本:[{req.docker_image.version}] \r\n 镜像URL:[{req.docker_image.url}] \r\n 创建时间:[{req.docker_image.created_at}] \r\n 创建人:[{req.docker_image.created_by.nickname}] \r\n 备注:[{req.docker_image.remarks}] \r\n \033[32m完成√\033[0m\r\n')
        
    # 添加yaml变量
    if extend.yaml_params:
        yaml_params = json.loads(extend.yaml_params)
        if yaml_params:
            for d in yaml_params:
                for key, value in d.items():
                    env[key]=value
                    
    if req.deploy.is_parallel:
        threads, latest_exception = [], None
        max_workers = max(10, os.cpu_count() * 5)
        with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for h_id in req.host_ids:
                new_env = AttrDict(env.items())
                t = executor.submit(_deploy_ext3_host, req, helper, h_id, new_env)
                t.h_id = h_id
                threads.append(t)
            for t in futures.as_completed(threads):
                exception = t.exception()
                if exception:
                    latest_exception = exception
                    if not isinstance(exception, SpugError):
                        helper.send_error(t.h_id, f'Exception: {exception}', False)
                else:
                    req.fail_host_ids.remove(t.h_id)
        if latest_exception:
            raise latest_exception
    else:
        host_ids = sorted(req.host_ids, reverse=True)
        while host_ids:
            h_id = host_ids.pop()
            new_env = AttrDict(env.items())
            try:
                _deploy_ext3_host(req, helper, h_id, new_env)
                req.fail_host_ids.remove(h_id)
            except Exception as e:
                helper.send_error(h_id, f'Exception: {e}', False)
                for h_id in host_ids:
                    helper.send_error(h_id, '终止发布', False)
                raise e


def _deploy_ext1_host(req, helper, h_id, env):
    helper.send_step(h_id, 1, f'\033[32m就绪√\033[0m\r\n{human_time()} 数据准备...        ')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    extend = req.deploy.extend_obj
    extend.dst_dir = render_str(extend.dst_dir, env)
    extend.dst_repo = render_str(extend.dst_repo, env)
    env.update(SPUG_DST_DIR=extend.dst_dir)
    with host.get_ssh(default_env=env) as ssh:
        base_dst_dir = os.path.dirname(extend.dst_dir)
        code, _ = ssh.exec_command_raw(
            f'mkdir -p {extend.dst_repo} {base_dst_dir} && [ -e {extend.dst_dir} ] && [ ! -L {extend.dst_dir} ]')
        if code == 0:
            helper.send_error(host.id, f'检测到该主机的发布目录 {extend.dst_dir!r} 已存在，为了数据安全请自行备份后删除该目录，Spug 将会创建并接管该目录。')
        if req.type == '2':
            helper.send_step(h_id, 1, '\033[33m跳过√\033[0m\r\n')
        else:
            # clean
            clean_command = f'ls -d {extend.deploy_id}_* 2> /dev/null | sort -t _ -rnk2 | tail -n +{extend.versions + 1} | xargs rm -rf'
            helper.remote_raw(host.id, ssh, f'cd {extend.dst_repo} && {clean_command}')
            # transfer files
            tar_gz_file = f'{req.spug_version}.tar.gz'
            try:
                callback = helper.progress_callback(host.id)
                ssh.put_file(
                    os.path.join(BUILD_DIR, tar_gz_file),
                    os.path.join(extend.dst_repo, tar_gz_file),
                    callback
                )
            except Exception as e:
                helper.send_error(host.id, f'Exception: {e}')

            command = f'cd {extend.dst_repo} && rm -rf {req.spug_version} && tar xf {tar_gz_file} && rm -f {req.deploy_id}_*.tar.gz'
            helper.remote_raw(host.id, ssh, command)
            helper.send_step(h_id, 1, '\033[32m完成√\033[0m\r\n')

        # pre host
        repo_dir = os.path.join(extend.dst_repo, req.spug_version)
        if extend.hook_pre_host:
            helper.send_step(h_id, 2, f'{human_time()} 发布前任务...       \r\n')
            command = f'cd {repo_dir} && {extend.hook_pre_host}'
            helper.remote(host.id, ssh, command)

        # do deploy
        helper.send_step(h_id, 3, f'{human_time()} 执行发布...        ')
        helper.remote_raw(host.id, ssh, f'rm -f {extend.dst_dir} && ln -sfn {repo_dir} {extend.dst_dir}')
        helper.send_step(h_id, 3, '\033[32m完成√\033[0m\r\n')

        # post host
        if extend.hook_post_host:
            helper.send_step(h_id, 4, f'{human_time()} 发布后任务...       \r\n')
            command = f'cd {extend.dst_dir} && {extend.hook_post_host}'
            helper.remote(host.id, ssh, command)

        helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m发布成功\033[0m **')


def _deploy_ext2_host(helper, h_id, actions, env, spug_version):
    helper.send_info(h_id, '\033[32m就绪√\033[0m\r\n')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    with host.get_ssh(default_env=env) as ssh:
        for index, action in enumerate(actions):
            helper.send_step(h_id, 1 + index, f'{human_time()} {action["title"]}...\r\n')
            if action.get('type') == 'transfer':
                if action.get('src_mode') == '1':
                    try:
                        dst = action['dst']
                        command = f'[ -e {dst} ] || mkdir -p $(dirname {dst}); [ -d {dst} ]'
                        code, _ = ssh.exec_command_raw(command)
                        if code == 0:  # is dir
                            if not action.get('name'):
                                raise RuntimeError('internal error 1002')
                            dst = dst.rstrip('/') + '/' + action['name']
                        callback = helper.progress_callback(host.id)
                        ssh.put_file(os.path.join(REPOS_DIR, env.SPUG_DEPLOY_ID, spug_version), dst, callback)
                    except Exception as e:
                        helper.send_error(host.id, f'Exception: {e}')
                    helper.send_info(host.id, 'transfer completed\r\n')
                    continue
                else:
                    sp_dir, sd_dst = os.path.split(action['src'])
                    tar_gz_file = f'{spug_version}.tar.gz'
                    try:
                        callback = helper.progress_callback(host.id)
                        ssh.put_file(os.path.join(sp_dir, tar_gz_file), f'/tmp/{tar_gz_file}', callback)
                    except Exception as e:
                        helper.send_error(host.id, f'Exception: {e}')

                    command = f'mkdir -p /tmp/{spug_version} && tar xf /tmp/{tar_gz_file} -C /tmp/{spug_version}/ '
                    command += f'&& rm -rf {action["dst"]} && mv /tmp/{spug_version}/{sd_dst} {action["dst"]} '
                    command += f'&& rm -rf /tmp/{spug_version}* && echo "transfer completed"'
            else:
                command = f'cd /tmp && {action["data"]}'
            helper.remote(host.id, ssh, command)

    helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m发布成功\033[0m **')


def _deploy_ext3_host(req, helper, h_id, env):
    helper.send_step(h_id, 1, f'\033[32m就绪√\033[0m\r\n{human_time()} 数据准备...        ')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    
    # 验证镜像和镜像仓库的URL是否一致（选择镜像发布的时候验证）
    image_url = None
    if env.SPUG_CONTAINER_REPOSITORY is not None:
        image_url = "{}/{}{}{}:{}".format(
                        env.SPUG_CONTAINER_REPOSITORY,
                        env.SPUG_CONTAINER_REPOSITORY_NAME_PREFIX,
                        "/" if env.SPUG_CONTAINER_REPOSITORY_NAME_PREFIX else "",
                        env.SPUG_IMAGE_NAME,
                        env.SPUG_IMAGE_VERSION
                    )
    else:
        image_url = f'{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}'
    
    diurl = req.docker_image.url
    if image_url != diurl:
        helper.send_error(host.id, f'\r\n镜像URL: {diurl} 跟系统配置的不一致 {image_url}！       \033[31m失败x\033[0m\r\n')
    
    extend = req.deploy.extend_obj
    extend.dst_dir = render_str(extend.dst_dir, env)
    extend.dst_repo = render_str(extend.dst_repo, env)
    env.update(SPUG_DST_DIR=extend.dst_dir)
    with host.get_ssh(default_env=env) as ssh:
        base_dst_dir = os.path.dirname(extend.dst_dir)
        code, _ = ssh.exec_command_raw(
            f'mkdir -p {extend.dst_repo} {base_dst_dir}  && mkdir -p "{extend.dst_repo}/{req.spug_version}" && [ -e {extend.dst_dir} ] && [ ! -L {extend.dst_dir} ]')
        
        if _:
            helper.send_error(host.id, f'\r\n在【{host.name}】创建目录{extend.dst_repo}失败，原因:{_} \r\n')
        
        if code == 0:
            helper.send_error(host.id, f'检测到该主机的发布目录 {extend.dst_dir!r} 已存在，为了数据安全请自行备份后删除该目录，Spug 将会创建并接管该目录。')
        if req.type == '2':
            helper.send_step(h_id, 1, '\033[33m跳过√\033[0m\r\n')
        else:
            # clean
            clean_command = f'ls -d {extend.deploy_id}_* 2> /dev/null | sort -t _ -rnk2 | tail -n +{extend.versions + 1} | xargs rm -rf'
            helper.remote_raw(host.id, ssh, f'cd {extend.dst_repo} && {clean_command}')
            # 查询yaml模板文件，有则写入 并上传
            template = FileTemplate.objects.filter(env_id=req.deploy.env_id, type='yaml').first()
            if template is not None:
                helper.send_step(host.id, 1, f'{human_time()} 写入 {template.name} 文件       ')
                helper.send_step(host.id, 1, f'{os.path.join(BUILD_DIR, template.name)}')
                try:
                    with open(os.path.join(BUILD_DIR, template.name), 'w', encoding='utf-8') as file:
                        file.write(template.body)
                    
                    callback = helper.progress_callback(host.id)
                    ssh.put_file(
                        os.path.join(BUILD_DIR, template.name),
                        os.path.join(extend.dst_repo, req.spug_version, template.name),
                        callback
                    )
                except Exception as e:
                    helper.send_error(host.id, f'Exception: {e}')
            else:
                helper.send_step(host.id, 1, f'{human_time()} {template.name} 模板不存在      ')  

            helper.send_step(host.id, 1, '\033[32m完成√\033[0m\r\n')

        # pre host
        repo_dir = os.path.join(extend.dst_repo, req.spug_version)
        
        code, _ = ssh.exec_command_raw(
            f'mkdir -p {repo_dir} {extend.dst_repo} && [ -e {repo_dir} ] && [ ! -L {repo_dir} ]')
        if code == 0:
            helper.send_step(h_id, 1, f'init dir {repo_dir}\r\n')
        
        if extend.hook_pre_host:
            helper.send_step(h_id, 2, f'{human_time()} 发布前任务...       \r\n')
            command = f'cd {repo_dir} && {extend.hook_pre_host}'
            helper.remote(host.id, ssh, command)

        # do deploy
        helper.send_step(h_id, 3, f'{human_time()} 执行发布...        ')
        helper.remote_raw(host.id, ssh, f'rm -f {extend.dst_dir} && ln -sfn {repo_dir} {extend.dst_dir}')
        helper.send_step(h_id, 3, '\033[32m完成√\033[0m\r\n')

        # post host
        if extend.hook_post_host:
            helper.send_step(h_id, 4, f'{human_time()} 发布后任务...       \r\n')
            command = f'cd {extend.dst_dir} && {extend.hook_post_host}'
            helper.remote(host.id, ssh, command)

        helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m发布成功\033[0m **')
        
        ## 后续清理目录
        
        
def _ext3_restart(req, helper, env):
    extend = req.deploy.extend_obj
    # 添加yaml变量
    if extend.yaml_params:
        yaml_params = json.loads(extend.yaml_params)
        if yaml_params:
            for d in yaml_params:
                for key, value in d.items():
                    env[key]=value
                    
    host_ids = sorted(req.host_ids, reverse=True)
    while host_ids:
        h_id = host_ids.pop()
        new_env = AttrDict(env.items())
        try:
            _restart_ext3_host(req, helper, h_id, new_env)
            req.fail_host_ids.remove(h_id)
        except Exception as e:
            helper.send_error(h_id, f'Exception: {e}', False)
            for h_id in host_ids:
                helper.send_error(h_id, '终止重启', False)
            raise e
        
def _restart_ext3_host(req, helper, h_id, env):
    helper.send_step(h_id, 1, f'\033[32m就绪√\033[0m\r\n{human_time()} 数据准备...        ')
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    
    extend = req.deploy.extend_obj
    with host.get_ssh(default_env=env) as ssh:
        helper.send_step(host.id, 1, '\033[32m完成√\033[0m\r\n')

        if extend.hook_restart_host:
            helper.send_step(h_id, 4, f'{human_time()} 执行重启...       \r\n')
            command = f'{extend.hook_restart_host}'
            helper.remote(host.id, ssh, command)
        else:
            helper.send_error(h_id, f'{human_time()} 未配置重启脚本...       \r\n')

        helper.send_step(h_id, 100, f'\r\n{human_time()} ** \033[32m重启成功\033[0m **')
