# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.db.models import F
from django.conf import settings
from django.db import transaction
from django.http.response import HttpResponseBadRequest
from django_redis import get_redis_connection
from libs import json_response, JsonParser, Argument, human_datetime, human_time, auth
from apps.deploy.models import (
    DeployIteration,
    DeployIterationDetail,
    DeployOperationLog,
    DeployRequest,
)
from apps.deploy.audit import format_app_environment_action, record_deploy_operation
from apps.app.models import Deploy, DeployExtend2
from apps.app.utils import scoped_deploys
from apps.repository.models import Repository
from apps.deploy.utils import (
    dispatch,
    Helper,
    get_iteration_detail_status,
    get_iteration_detail_remove_error,
    get_iteration_overall_status,
    get_cross_iteration_warnings,
    get_deploy_retry_error,
    get_deploy_retry_info,
    get_running_deploy_error,
    lock_deploy_and_get_running_request,
    reconcile_iteration_detail_statuses,
)
from apps.host.models import Host
from apps.config.models import Environment
from apps.docker_image.models import DockerImage
from collections import defaultdict
from threading import Thread
from datetime import datetime
from pathlib import Path
import shutil
import json
import os


class OperationLogView(View):
    @auth('deploy.request.view|deploy.iteration.view')
    def get(self, request):
        form, error = JsonParser(
            Argument(
                'target_type',
                filter=lambda value: value in ('request', 'iteration'),
                help='日志对象类型错误',
            ),
            Argument('target_id', type=int, help='日志对象ID错误'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        permission = (
            'deploy.request.view'
            if form.target_type == 'request'
            else 'deploy.iteration.view'
        )
        if not request.user.has_perms([permission]):
            return json_response(error='权限拒绝')

        if not request.user.is_supper:
            perms = request.user.deploy_perms
            if form.target_type == 'request':
                target_visible = DeployRequest.objects.filter(
                    pk=form.target_id,
                    deploy__app_id__in=perms['apps'],
                    deploy__env_id__in=perms['envs'],
                ).exists()
            else:
                target_visible = DeployIteration.objects.filter(
                    pk=form.target_id,
                    env_id__in=perms['envs'],
                ).exists()
            if not target_visible:
                return json_response(error='未找到日志对象或无查看权限')

        data = [
            {
                'id': item.id,
                'operator_name': item.operator_name,
                'action': item.action,
                'created_at': item.created_at,
            }
            for item in DeployOperationLog.objects.filter(
                target_type=form.target_type,
                target_id=form.target_id,
            )[:200]
        ]
        return json_response(data)


class RequestView(View):
    @auth('deploy.request.view')
    def get(self, request):
        data, query, counter = [], {}, {}
        if not request.user.is_supper:
            perms = request.user.deploy_perms
            query['deploy__app_id__in'] = perms['apps']
            query['deploy__env_id__in'] = perms['envs']
        
        # 接收传参查询过滤，避免量太大
        # 时间, 默认查询7天。最多不能超过30天
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if (start_date is None or end_date is None or start_date == 'undefined' or end_date == 'undefined'):
            return json_response(error='必须选择开始和结束日期')
        
        # 判断日期格式
        date_format = "%Y-%m-%d"
        try:
            start_date = datetime.strptime(start_date, date_format)
            end_date = datetime.strptime(end_date, date_format)
        except ValueError:
            return json_response(error='日期格式必须是 YYYY-MM-DD')

        # 判断开始日期是否早于结束日期
        if start_date > end_date:
            return json_response(error='开始日期必须早于结束日期')

        # 判断日期范围是否超过60天
        if (end_date - start_date).days > 60:
            return json_response(error='时间范围不能超过60天')
        
        query['created_at_date__range'] = (start_date, end_date)
        
        for item in DeployRequest.objects.filter(**query).select_related(
                'deploy', 'deploy__env'
        ).annotate(
                env_id=F('deploy__env_id'),
                env_name=F('deploy__env__name'),
                env_prod=F('deploy__env__prod'),
                app_id=F('deploy__app_id'),
                app_name=F('deploy__app__name'),
                app_rel_tags=F('deploy__app__rel_tags'),
                app_host_ids=F('deploy__host_ids'),
                app_extend=F('deploy__extend'),
                rep_extra=F('repository__extra'),
                do_by_user=F('do_by__nickname'),
                approve_by_user=F('approve_by__nickname'),
                created_by_user=F('created_by__nickname')):
            tmp = item.to_dict()
            tmp['env_id'] = item.env_id
            tmp['env_name'] = item.env_name
            tmp['env_prod'] = item.env_prod
            tmp['app_id'] = item.app_id
            tmp['app_name'] = item.app_name
            tmp['app_rel_tags'] = json.loads(item.app_rel_tags) if item.app_rel_tags else []
            tmp['app_extend'] = item.app_extend
            tmp['host_ids'] = json.loads(item.host_ids)
            tmp['fail_host_ids'] = json.loads(item.fail_host_ids)
            tmp['extra'] = json.loads(item.extra) if item.extra else None
            tmp['rep_extra'] = json.loads(item.rep_extra) if item.rep_extra else None
            tmp['app_host_ids'] = json.loads(item.app_host_ids)
            tmp['status_alias'] = item.get_status_display()
            tmp['created_by_user'] = item.created_by_user
            tmp['approve_by_user'] = item.approve_by_user
            tmp['do_by_user'] = item.do_by_user
            tmp.update(get_deploy_retry_info(item))
            if item.app_extend == '1':
                tmp['visible_rollback'] = item.deploy_id not in counter
                counter[item.deploy_id] = True
            data.append(tmp)
        return json_response(data)

    @auth('deploy.request.del|deploy.request.batch_del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('mode', filter=lambda x: x in ('count', 'expire', 'deploy'), required=False, help='参数错误'),
            Argument('value', required=False),
        ).parse(request.GET)
        if error is None:
            # 单个删除：使用 del 权限，只能删除待发布、待审核、已驳回的申请
            if form.id:
                # 验证单个删除权限
                if not request.user.has_perms(['deploy.request.del']):
                    return json_response(error='无删除权限')
                deploy = DeployRequest.objects.filter(pk=form.id).first()
                if not deploy or deploy.status not in ('0', '1', '-1'):
                    return json_response(error='未找到指定发布申请或当前状态不允许删除')
                deploy_id, deploy_name = deploy.id, deploy.name
                deploy.delete()
                record_deploy_operation(
                    'request', deploy_id, deploy_name, '删除发布申请', request.user
                )
                return json_response()

            # 批量删除：使用 batch_del 权限
            if not request.user.has_perms(['deploy.request.batch_del']):
                return json_response(error='无批量删除权限')

            # 发布申请不允许删除（需要保留，避免发布之后删除导致后续无法追溯）
            return json_response(error='系统禁止删除')
            count = 0
            if form.mode == 'count':
                if not str(form.value).isdigit() or int(form.value) < 1:
                    return json_response(error='请输入正确的保留数量')
                counter, form.value = defaultdict(int), int(form.value)
                for item in DeployRequest.objects.all():
                    counter[item.deploy_id] += 1
                    if counter[item.deploy_id] > form.value:
                        count += 1
                        item.delete()
            elif form.mode == 'expire':
                for item in DeployRequest.objects.filter(created_at__lt=form.value):
                    count += 1
                    item.delete()
            elif form.mode == 'deploy':
                app_id, env_id = str(form.value).split(',')
                for item in DeployRequest.objects.filter(deploy__app_id=app_id, deploy__env_id=env_id):
                    count += 1
                    item.delete()
            return json_response(count)
        return json_response(error=error)


class RequestDetailView(View):
    @auth('deploy.request.view')
    def get(self, request, r_id):
        req = DeployRequest.objects.filter(pk=r_id).first()
        if not req:
            return json_response(error='未找到指定发布申请')
        hosts = Host.objects.filter(id__in=json.loads(req.host_ids))
        outputs = {x.id: {'id': x.id, 'title': x.name, 'data': f'{human_time()} 读取数据...        '} for x in hosts}
        response = {'outputs': outputs, 'status': req.status}
        if req.is_quick_deploy:
            outputs['local'] = {'id': 'local', 'data': '', 'title': '代码构建'}
            if req.deploy.extend == '3':
                build_image_host_id = req.deploy.extend_obj.build_image_host_id
                build_image_host = Host.objects.get(id=build_image_host_id)
                outputs['image'] = {'id': 'image', 'data': '', 'title': f'镜像编译&上传 [{build_image_host.name}]'}
        if req.deploy.extend == '2':
            outputs['local'] = {'id': 'local', 'data': f'{human_time()} 读取数据...        '}
            response['s_actions'] = json.loads(req.deploy.extend_obj.server_actions)
            response['h_actions'] = json.loads(req.deploy.extend_obj.host_actions)
            if not response['h_actions']:
                response['outputs'] = {'local': outputs['local']}
        if req.deploy.extend == '3':
            build_image_host_id = req.deploy.extend_obj.build_image_host_id
            build_image_host = Host.objects.get(id=build_image_host_id)
            outputs['local'] = {'id': 'local', 'data': '', 'title': '代码构建'}
            outputs['image'] = {'id': 'image', 'data': '', 'title': f'镜像编译&上传 [{build_image_host.name}]'}
        rds, key, counter = get_redis_connection(), f'{settings.REQUEST_KEY}:{r_id}', 0
        data = rds.lrange(key, counter, counter + 9)
        while data:
            for item in data:
                counter += 1
                item = json.loads(item.decode())
                if item['key'] in outputs:
                    if 'data' in item:
                        outputs[item['key']]['data'] += item['data']
                    if 'step' in item:
                        outputs[item['key']]['step'] = item['step']
                    if 'status' in item:
                        outputs[item['key']]['status'] = item['status']
            data = rds.lrange(key, counter, counter + 9)
        response['index'] = counter
        if counter == 0:
            for item in outputs:
                outputs[item]['data'] += '\r\n\r\n未读取到数据，Spug 仅保存最近30天的日志信息。'

        if req.is_quick_deploy:
            if outputs['local']['data']:
                outputs['local']['data'] = f'{human_time()} 读取数据...        ' + outputs['local']['data']
            else:
                outputs['local'].update(step=100, data=f'{human_time()} 已构建完成忽略执行。')
                
        if req.type == '0':
            del outputs['local']
            del outputs['image']
            
        return json_response(response)

    @auth('deploy.request.do')
    def post(self, request, r_id):
        form, _ = JsonParser(Argument('mode', default='all')).parse(request.body)
        query = {'pk': r_id}
        if not request.user.is_supper:
            perms = request.user.deploy_perms
            query['deploy__app_id__in'] = perms['apps']
            query['deploy__env_id__in'] = perms['envs']
        req_snapshot = DeployRequest.objects.filter(**query).only('id', 'deploy_id').first()
        if not req_snapshot:
            return json_response(error='未找到指定发布申请')

        # 所有入口统一先锁发布配置，再锁申请，避免交叉顺序导致死锁。
        deploy, running_request = lock_deploy_and_get_running_request(
            req_snapshot.deploy_id
        )
        if not deploy:
            return json_response(error='未找到对应的发布配置')
        req = DeployRequest.objects.select_for_update().filter(**query).first()
        if not req:
            return json_response(error='未找到指定发布申请')
        if req.status not in ('1', '-3'):
            return json_response(error='该申请单当前状态还不能执行发布')
        is_retry = req.status == '-3'
        if is_retry:
            retry_error = get_deploy_retry_error(req)
            if retry_error:
                return json_response(error=retry_error)

        env = deploy.env

        if running_request:
            return json_response(error=get_running_deploy_error(deploy))

        # 如果 env.conc_num <= 0，则不限制最大并发发布数量
        if env.conc_num > 0:
            # 获取当前环境正在发布的数量
            current_env_count = DeployRequest.objects.filter(deploy__env=env, status='2').count()

            # 判断是否超过最大并发发布数量
            if current_env_count >= env.conc_num:
                return json_response(error=f'{env.name}环境 最大同时发布数量{env.conc_num}，请等待前面的发布完成')

        host_ids = req.fail_host_ids if form.mode == 'fail' else req.host_ids
        hosts = Host.objects.filter(id__in=json.loads(host_ids))
        message = f'{human_time()} 等待调度...        '
        outputs = {x.id: {'id': x.id, 'title': x.name, 'step': 0, 'data': message} for x in hosts}
        req.status = '2'
        req.do_at = human_datetime()
        req.do_by = request.user
        req.save()
        mode_name = '补偿发布' if form.mode == 'fail' else '全量发布'
        action = f'重试发布申请（{mode_name}）' if is_retry else f'执行发布申请（{mode_name}）'
        record_deploy_operation(
            'request', req.id, req.name, action, request.user
        )
        transaction.on_commit(
            lambda request_obj=req, fail_mode=form.mode == 'fail': Thread(
                target=dispatch,
                args=(request_obj, fail_mode),
            ).start()
        )

        if req.is_quick_deploy:
            if req.repository_id:
                outputs['local'] = {'id': 'local', 'step': 100, 'data': f'{human_time()} 已构建完成忽略执行。', 'title': '代码构建'}
            else:
                outputs['local'] = {'id': 'local', 'step': 0, 'data': f'{human_time()} 建立连接...        ', 'title': '代码构建'}
        if req.deploy.extend == '2':
            outputs['local'] = {'id': 'local', 'step': 0, 'data': f'{human_time()} 建立连接...        '}
            s_actions = json.loads(req.deploy.extend_obj.server_actions)
            h_actions = json.loads(req.deploy.extend_obj.host_actions)
            for item in h_actions:
                if item.get('type') == 'transfer' and item.get('src_mode') == '0':
                    s_actions.append({'title': '执行打包'})
            if not h_actions:
                outputs = {'local': outputs['local']}
            return json_response({'s_actions': s_actions, 'h_actions': h_actions, 'outputs': outputs})
        if req.deploy.extend == '3':
            build_image_host_id = req.deploy.extend_obj.build_image_host_id
            build_image_host = Host.objects.get(id=build_image_host_id)

            if req.repository_id:
                outputs['local'] = {'id': 'local', 'step': 100, 'data': f'{human_time()} 已构建完成忽略执行。', 'title': '代码构建'}
            else:
                outputs['local'] = {'id': 'local', 'step': 0, 'data': f'{human_time()} 建立连接...        ', 'title': '代码构建'}
            if req.docker_image_id:
                outputs['image'] = {'id': 'image', 'step': 100, 'data': f'{human_time()} 已编译完成忽略执行。', 'title': f'镜像编译&上传 [{build_image_host.name}]'}
            else:
                outputs['image'] = {'id': 'image', 'step': 0, 'data': f'{human_time()} 建立连接...        ', 'title': f'镜像编译&上传 [{build_image_host.name}]'}
        
        if req.type == '0':
            del outputs['local']
            del outputs['image']
        
        return json_response({'outputs': outputs})

    @auth('deploy.request.approve')
    def patch(self, request, r_id):
        form, error = JsonParser(
            Argument('reason', required=False),
            Argument('is_pass', type=bool, help='参数错误')
        ).parse(request.body)
        if error is None:
            req = DeployRequest.objects.filter(pk=r_id).first()
            if not req:
                return json_response(error='未找到指定申请')
            if not form.is_pass and not form.reason:
                return json_response(error='请输入驳回原因')
            if req.status != '0':
                return json_response(error='该申请当前状态不允许审核')
            req.approve_at = human_datetime()
            req.approve_by = request.user
            req.status = '1' if form.is_pass else '-1'
            req.reason = form.reason
            req.save()
            record_deploy_operation(
                'request',
                req.id,
                req.name,
                '审核通过发布申请' if form.is_pass else '驳回发布申请',
                request.user,
            )
            Thread(target=Helper.send_deploy_notify, args=(req, 'approve_rst')).start()
        return json_response(error=error)
    
@auth('deploy.request.add|deploy.request.edit')
def post_request_ext1(request):
    form, error = JsonParser(
        Argument('id', type=int, required=False),
        Argument('deploy_id', type=int, help='参数错误'),
        Argument('name', help='请输入申请标题'),
        Argument('extra', type=list, help='请选择发布版本'),
        # Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择要部署的主机'),
        Argument('type', default='1'),
        Argument('plan', required=False),
        Argument('desc', required=False),
    ).parse(request.body)
    if error is None:
        deploy = Deploy.objects.get(pk=form.deploy_id)
        form.spug_version = Repository.make_spug_version(deploy.id)
        if form.extra[0] == 'tag':
            if not form.extra[1]:
                return json_response(error='请选择要发布的版本')
            form.version = form.extra[1]
        elif form.extra[0] == 'branch':
            if not form.extra[2]:
                return json_response(error='请选择要发布的分支及Commit ID')
            form.version = f'{form.extra[1]}#{form.extra[2][:6]}'
        elif form.extra[0] == 'repository':
            if not form.extra[1]:
                return json_response(error='请选择要发布的版本')
            repository = Repository.objects.get(pk=form.extra[1])
            form.repository_id = repository.id
            form.version = repository.version
            form.spug_version = repository.spug_version
            form.extra = ['repository'] + json.loads(repository.extra)
        else:
            return json_response(error='参数错误')

        # 获取环境，对应的环境是否是生产环境。 是则form.extra[0]只能是tag
        if (deploy.env.prod and form.extra[0] != 'tag'):
            if (form.extra[0] == 'repository'):
                if (form.extra[1] != 'tag'):
                    return json_response(error='生产环境只能选择tag代码')
            else:
                return json_response(error='生产环境只能选择tag代码')

        form.extra = json.dumps(form.extra)
        form.status = '0' if deploy.is_audit else '1'
        # form.host_ids = json.dumps(sorted(form.host_ids))
        form.host_ids = deploy.host_ids
        is_edit = bool(form.id)
        if is_edit:
            req = DeployRequest.objects.get(pk=form.id)
            is_required_notify = deploy.is_audit and req.status == '-1'
            DeployRequest.objects.filter(pk=form.id).update(created_by=request.user, reason=None, **form)
        else:
            req = DeployRequest.objects.create(created_by=request.user, **form)
            is_required_notify = deploy.is_audit
        record_deploy_operation(
            'request',
            req.id,
            form.name,
            '修改发布申请' if is_edit else '创建发布申请',
            request.user,
        )
        if is_required_notify:
            Thread(target=Helper.send_deploy_notify, args=(req, 'approve_req')).start()
    return json_response(error=error)


@auth('deploy.request.do')
def post_request_ext1_rollback(request):
    form, error = JsonParser(
        Argument('request_id', type=int, help='请选择要回滚的版本'),
        Argument('name', help='请输入申请标题'),
        # Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择要部署的主机'),
        Argument('desc', required=False),
    ).parse(request.body)
    
    if error is None:
        req = DeployRequest.objects.get(pk=form.pop('request_id'))
        requests = DeployRequest.objects.filter(deploy=req.deploy, status__in=('3', '-3'))
        versions = list({x.spug_version: 1 for x in requests}.keys())
        if req.spug_version not in versions[:req.deploy.extend_obj.versions + 1]:
            return json_response(error='选择的版本超出了发布配置中设置的版本数量，无法快速回滚，可通过新建发布申请选择构建仓库里的该版本再次发布。')

        form.status = '0' if req.deploy.is_audit else '1'
        # form.host_ids = json.dumps(sorted(form.host_ids))
        form.host_ids = req.host_ids
        new_req = DeployRequest.objects.create(
            deploy_id=req.deploy_id,
            repository_id=req.repository_id,
            type='2',
            extra=req.extra,
            version=req.version,
            spug_version=req.spug_version,
            created_by=request.user,
            **form
        )
        record_deploy_operation(
            'request', new_req.id, new_req.name, '创建回滚发布申请', request.user
        )
        if req.deploy.is_audit:
            Thread(target=Helper.send_deploy_notify, args=(new_req, 'approve_req')).start()
    return json_response(error=error)


@auth('deploy.request.add|deploy.request.edit')
def post_request_ext2(request):
    form, error = JsonParser(
        Argument('id', type=int, required=False),
        Argument('deploy_id', type=int, help='缺少必要参数'),
        Argument('name', help='请输申请标题'),
        # Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择要部署的主机'),
        Argument('extra', type=dict, required=False),
        Argument('version', default=''),
        Argument('type', default='1'),
        Argument('plan', required=False),
        Argument('desc', required=False),
    ).parse(request.body)
    if error is None:
        deploy = Deploy.objects.filter(pk=form.deploy_id).first()
        if not deploy:
            return json_response(error='未找到该发布配置')
        extra = form.pop('extra')
        if DeployExtend2.objects.filter(deploy=deploy, host_actions__contains='"src_mode": "1"').exists():
            if not extra:
                return json_response(error='该应用的发布配置中使用了数据传输动作且设置为发布时上传，请上传要传输的数据')
            form.spug_version = extra['path']
            form.extra = json.dumps(extra)
        else:
            form.spug_version = Repository.make_spug_version(deploy.id)
        form.name = form.name.replace("'", '')
        form.status = '0' if deploy.is_audit else '1'
        # form.host_ids = json.dumps(form.host_ids)
        form.host_ids = deploy.host_ids
        is_edit = bool(form.id)
        if is_edit:
            req = DeployRequest.objects.get(pk=form.id)
            is_required_notify = deploy.is_audit and req.status == '-1'
            form.update(created_by=request.user, reason=None)
            req.update_by_dict(form)
        else:
            req = DeployRequest.objects.create(created_by=request.user, **form)
            is_required_notify = deploy.is_audit
        record_deploy_operation(
            'request',
            req.id,
            req.name,
            '修改发布申请' if is_edit else '创建发布申请',
            request.user,
        )
        if is_required_notify:
            Thread(target=Helper.send_deploy_notify, args=(req, 'approve_req')).start()
    return json_response(error=error)

@auth('deploy.request.add|deploy.request.edit')
def post_request_ext3(request):
    form, error = JsonParser(
        Argument('id', type=int, required=False),
        Argument('deploy_id', type=int, help='参数错误'),
        Argument('name', help='请输入申请标题'),
        Argument('extra', type=list, help='请选择发布版本', default=[]),
        # Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择要部署的主机'),
        Argument('type', default='1'),
        Argument('plan', required=False),
        Argument('desc', required=False),
    ).parse(request.body)
    if error is None:
        deploy = Deploy.objects.get(pk=form.deploy_id)
        form.spug_version = Repository.make_spug_version(deploy.id)
        # 不是重启类型才需要验证
        if form.type != '0':
            if form.extra[0] == 'tag':
                if not form.extra[1]:
                    return json_response(error='请选择要发布的版本')
                form.version = form.extra[1]
            elif form.extra[0] == 'branch':
                if not form.extra[2]:
                    return json_response(error='请选择要发布的分支及Commit ID')
                form.version = f'{form.extra[1]}#{form.extra[2][:6]}'
            elif form.extra[0] == 'repository':
                if not form.extra[1]:
                    return json_response(error='请选择要发布的版本')
                repository = Repository.objects.get(pk=form.extra[1])
                form.repository_id = repository.id
                form.version = repository.version
                form.spug_version = repository.spug_version
                form.extra = ['repository'] + json.loads(repository.extra)
            elif form.extra[0] == 'docker_image':
                if not form.extra[1]:
                    return json_response(error='请选择要发布的镜像版本')
                dockerImage = DockerImage.objects.get(id=form.extra[1])
                form.docker_image_id = dockerImage.id
                # form.repository_id = dockerImage.repository.id
                form.version = dockerImage.version
                form.spug_version = dockerImage.spug_version
                form.extra = ['docker_image'] + json.loads(dockerImage.extra)
            else:
                return json_response(error='参数错误')

            # 获取环境，对应的环境是否是生产环境。 是则form.extra[0]只能是tag
            if (deploy.env.prod and form.extra[0] != 'tag'):
                if (form.extra[0] == 'repository'):
                    if (form.extra[1] != 'tag'):
                        return json_response(error='生产环境只能选择tag代码')
                elif (form.extra[0] == 'docker_image'):
                    if (form.extra[1] == 'repository'):
                        if (form.extra[2] != 'tag'):
                            return json_response(error='生产环境只能选择tag代码')
                    elif (form.extra[1] != 'tag'):
                        return json_response(error='生产环境只能选择tag代码')
                else:
                    return json_response(error='生产环境只能选择tag代码')

        form.extra = json.dumps(form.extra)
        form.status = '0' if deploy.is_audit else '1'
        # form.host_ids = json.dumps(sorted(form.host_ids))
        form.host_ids = deploy.host_ids
        is_edit = bool(form.id)
        if is_edit:
            req = DeployRequest.objects.get(pk=form.id)
            is_required_notify = deploy.is_audit and req.status == '-1'
            DeployRequest.objects.filter(pk=form.id).update(created_by=request.user, reason=None, **form)
        else:
            req = DeployRequest.objects.create(created_by=request.user, **form)
            is_required_notify = deploy.is_audit
        record_deploy_operation(
            'request',
            req.id,
            form.name,
            '修改发布申请' if is_edit else '创建发布申请',
            request.user,
        )
        if is_required_notify:
            Thread(target=Helper.send_deploy_notify, args=(req, 'approve_req')).start()
    return json_response(error=error)

@auth('deploy.request.view')
def get_request_info(request):
    form, error = JsonParser(
        Argument('id', type=int, help='参数错误')
    ).parse(request.GET)
    if error is None:
        req = DeployRequest.objects.select_related(
            'deploy',
            'deploy__app',
            'deploy__env',
            'created_by',
            'approve_by',
            'do_by',
        ).filter(pk=form.id).first()
        if not req:
            return json_response(error='未找到指定发布申请')
        response = req.to_dict(selects=(
            'id',
            'name',
            'type',
            'status',
            'reason',
            'version',
            'desc',
            'created_at',
            'approve_at',
            'do_at',
        ))
        response['fail_host_ids'] = json.loads(req.fail_host_ids)
        response['status_alias'] = req.get_status_display()
        response['type_alias'] = req.get_type_display()
        response['app_extend'] = req.deploy.extend
        response['app_name'] = req.deploy.app.name
        response['env_name'] = req.deploy.env.name
        response['env_prod'] = req.deploy.env.prod
        response['created_by_user'] = req.created_by.nickname
        response['approve_by_user'] = req.approve_by.nickname if req.approve_by else None
        response['do_by_user'] = req.do_by.nickname if req.do_by else None
        response.update(get_deploy_retry_info(req))
        return json_response(response)
    return json_response(error=error)


@auth('deploy.request.add')
def do_upload(request):
    file = request.FILES.get('file')
    deploy_id = request.POST.get('deploy_id')
    if not file or not deploy_id:
        return HttpResponseBadRequest()
    try:
        deploy_id = int(deploy_id)
    except (TypeError, ValueError):
        return json_response(error='发布配置参数错误')
    deploy = scoped_deploys(request.user).filter(pk=deploy_id).first()
    if not deploy:
        return json_response(error='未找到发布配置或无操作权限')

    repos_dir = Path(settings.REPOS_DIR).resolve()
    dir_name = repos_dir / str(deploy.id)
    dir_name.mkdir(parents=True, exist_ok=True)
    if dir_name.resolve().parent != repos_dir:
        return json_response(error='发布目录参数错误')

    for path in sorted(dir_name.iterdir(), key=lambda item: item.name, reverse=True)[10:]:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(str(path))

    file_name = datetime.now().strftime("%Y%m%d%H%M%S")
    with (dir_name / file_name).open('wb') as f:
        for chunk in file.chunks():
            f.write(chunk)
    return json_response(file_name)


class IterationView(View):
    @auth('deploy.iteration.view')
    def get(self, request):
        query = {}
        if not request.user.is_supper:
            perms = request.user.deploy_perms
            query['env_id__in'] = perms['envs']
        
        # 如果传入 id 参数，直接返回单个迭代
        iteration_id = request.GET.get('id')
        if iteration_id:
            try:
                query['id'] = int(iteration_id)
            except ValueError:
                return json_response(error='迭代ID格式错误')
            # 若传入 id，则按该 id 查询，保证后续对 qs 的统一处理
            qs = DeployIteration.objects.filter(**query)
        else:
            # 获取时间范围，默认1个月
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            if (start_date is None or end_date is None or start_date == 'undefined' or end_date == 'undefined'):
                # 使用默认的30天范围
                today = datetime.now().date()
                from datetime import timedelta
                start_date = (today - timedelta(days=30)).isoformat()
                end_date = today.isoformat()
            
            date_format = "%Y-%m-%d"
            try:
                start_date = datetime.strptime(start_date, date_format)
                end_date = datetime.strptime(end_date, date_format)
            except ValueError:
                return json_response(error='日期格式必须是 YYYY-MM-DD')

            if start_date > end_date:
                return json_response(error='开始日期必须早于结束日期')

            if (end_date - start_date).days > 60:
                return json_response(error='时间范围不能超过60天')
            
            query['created_at_date__range'] = (start_date, end_date)
            
            # 按迭代名称搜索
            name = request.GET.get('name')
            if name:
                query['name__icontains'] = name
            
            # 按环境搜索
            env_id = request.GET.get('env_id')
            qs = DeployIteration.objects.filter(**query)
            if env_id:
                qs = qs.filter(details__deploy__env_id=env_id).distinct()

        # 使用 prefetch_related 优化查询，避免 N+1 问题
        from django.db.models import Prefetch
        qs = qs.select_related('env', 'created_by', 'updated_by').prefetch_related(
            Prefetch(
                'details',
                queryset=DeployIterationDetail.objects.select_related(
                    'deploy', 'deploy__app', 'deploy__env'
                )
            )
        )

        items = list(qs)
        all_details = []
        for item in items:
            all_details.extend(item.details.all())
        affected_iteration_ids = reconcile_iteration_detail_statuses(all_details)
        if affected_iteration_ids:
            iteration_statuses = dict(DeployIteration.objects.filter(
                pk__in=affected_iteration_ids
            ).values_list('id', 'status'))
            for item in items:
                if item.id in iteration_statuses:
                    item.status = iteration_statuses[item.id]

        data = []
        for item in items:
            tmp = item.to_dict()
            tmp['env_id'] = item.env_id
            tmp['env_name'] = item.env.name if item.env else ''
            # 获取迭代下的所有发布项（使用已预加载的数据）
            details = []
            env_ids = set()
            env_map = {}
            env_prod_map = {}
            for detail in item.details.all():
                deploy = detail.deploy
                if deploy and deploy.env_id:
                    env_ids.add(deploy.env_id)
                    if deploy.env:
                        env_map[deploy.env_id] = deploy.env.name
                        env_prod_map[deploy.env_id] = deploy.env.prod
                detail_dict = {
                    'id': detail.id,
                    'deploy_id': detail.deploy_id,
                    'app_id': deploy.app_id if deploy else None,
                    'env_id': deploy.env_id if deploy else None,
                    'app_name': deploy.app.name if deploy and deploy.app else '',
                    'env_name': deploy.env.name if deploy and deploy.env else '',
                    'env_prod': deploy.env.prod if deploy and deploy.env else False,
                    'version': detail.version,
                    'sequence': detail.sequence,
                    'is_container': deploy.extend == '3' if deploy else False,  # 是否容器发布
                }
                # 兼容处理：字段可能不存在
                try:
                    detail_dict['status'] = detail.status
                    detail_dict['status_alias'] = detail.get_status_display()
                    detail_dict['request_id'] = detail.request_id
                    detail_dict['image_status'] = getattr(detail, 'image_status', '0')
                    detail_dict['docker_image_id'] = getattr(detail, 'docker_image_id', None)
                except AttributeError:
                    detail_dict['status'] = '0'
                    detail_dict['status_alias'] = '待发布'
                    detail_dict['request_id'] = None
                    detail_dict['image_status'] = '0'
                    detail_dict['docker_image_id'] = None
                details.append(detail_dict)
            tmp['details'] = details
            env_ids_list = sorted(list(env_ids))
            tmp['env_ids'] = env_ids_list
            # 使用已收集的环境信息，无需再查询
            env_names = [env_map.get(i, '') for i in env_ids_list]
            tmp['env_name'] = ','.join([n for n in env_names if n])
            # 返回每个环境的详细信息（包含是否生产环境）
            tmp['env_list'] = [{'id': i, 'name': env_map.get(i, ''), 'prod': env_prod_map.get(i, False)} for i in env_ids_list]
            tmp['status_alias'] = item.get_status_display()
            # 计算发布项统计：不同应用数量 / 发布项总数
            app_ids = set([d.get('app_id') for d in details if d.get('app_id')])
            tmp['publish_apps_count'] = len(app_ids)
            tmp['publish_total_count'] = len(details)
            tmp['created_by_user'] = item.created_by.nickname if item.created_by else ''
            tmp['updated_by_user'] = item.updated_by.nickname if item.updated_by else ''
            # 计算已发布数量（发布成功的）- 使用已加载的数据
            published_count = sum(1 for d in details if d.get('status') == '2')
            tmp['published_count'] = published_count
            data.append(tmp)
        
        return json_response(data)

    @auth('deploy.iteration.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', required=True, help='迭代名称必填'),
            Argument('env_ids', type=list, required=True, help='环境ID列表必填'),
            Argument('desc', required=False),
            Argument('details', type=list, required=True, help='发布项必填'),
        ).parse(request.body)
        
        if error is None:
            try:
                # 使用第一个环境作为迭代的主环境
                main_env_id = form.env_ids[0] if form.env_ids else None
                if not main_env_id:
                    return json_response(error='请选择至少一个环境')

                iteration = DeployIteration.objects.create(
                    name=form.name,
                    env_id=main_env_id,
                    desc=form.desc,
                    status='0',  # 默认设置为待发布
                    created_by=request.user
                )
                
                # 添加迭代明细 - 根据 app_id 和 env_id 查询对应的 deploy_id
                from apps.app.models import Deploy
                for item in form.details:
                    app_id = item.get('app_id')
                    env_id = item.get('env_id')
                    version = item.get('version')
                    
                    if not app_id or not env_id:
                        continue
                    
                    # 查找该应用在该环境的部署配置
                    deploy = Deploy.objects.filter(app_id=app_id, env_id=env_id).first()
                    if not deploy:
                        continue
                    
                    DeployIterationDetail.objects.create(
                        iteration=iteration,
                        deploy_id=deploy.id,
                        version=version,
                        sequence=item.get('sequence', 0),
                        created_by=request.user
                    )

                record_deploy_operation(
                    'iteration', iteration.id, iteration.name, '创建迭代', request.user
                )
                
                result = iteration.to_dict()
                result['env_name'] = iteration.env.name
                result['env_ids'] = form.env_ids
                result['details'] = []
                for detail in iteration.details.all():
                    result['details'].append({
                        'id': detail.id,
                        'deploy_id': detail.deploy_id,
                        'app_id': detail.deploy.app_id if detail.deploy else None,
                        'env_id': detail.deploy.env_id if detail.deploy else None,
                        'app_name': detail.deploy.app.name if detail.deploy and detail.deploy.app else '',
                        'env_name': detail.deploy.env.name if detail.deploy and detail.deploy.env else '',
                        'version': detail.version,
                        'sequence': detail.sequence,
                    })
                result['status_alias'] = iteration.get_status_display()
                result['created_by_user'] = request.user.nickname
                return json_response(result)
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)

    @auth('deploy.iteration.edit')
    def put(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=True, help='迭代ID必填'),
            Argument('name', required=True, help='迭代名称必填'),
            Argument('env_ids', type=list, required=True, help='环境ID列表必填'),
            Argument('desc', required=False),
            Argument('details', type=list, required=True, help='发布项必填'),
            Argument('status', required=False),
        ).parse(request.body)
        
        if error is None:
            try:
                iteration = DeployIteration.objects.filter(pk=form.id).first()
                if not iteration:
                    return json_response(error='未找到指定迭代')
                
                # 只有待发布状态才能编辑
                if iteration.status != '0':
                    status_map = {'0': '待发布', '1': '发布中', '2': '发布成功', '-1': '部分失败', '-3': '发布失败'}
                    return json_response(error=f'当前状态为"{status_map.get(iteration.status, iteration.status)}"，只有待发布状态才能编辑')
                
                iteration.name = form.name
                # 使用第一个环境作为主环境
                if form.env_ids:
                    iteration.env_id = form.env_ids[0]
                iteration.desc = form.desc
                if form.status:
                    iteration.status = form.status
                iteration.updated_by = request.user
                iteration.save()
                
                # 更新迭代明细 - 保留已发布成功的明细，只更新待发布的
                from apps.app.models import Deploy
                
                # 获取已发布成功的明细（不能删除和修改版本）- 兼容处理
                published_details = {}
                try:
                    published_details = {
                        (d.deploy.app_id, d.deploy.env_id): d 
                        for d in iteration.details.filter(status='2')
                    }
                    # 删除未发布成功的明细
                    iteration.details.exclude(status='2').delete()
                except Exception:
                    # 字段不存在时删除所有明细
                    iteration.details.all().delete()
                
                for item in form.details:
                    app_id = item.get('app_id')
                    env_id = item.get('env_id')
                    version = item.get('version')
                    
                    if not app_id or not env_id:
                        continue
                    
                    # 查找该应用在该环境的部署配置
                    deploy = Deploy.objects.filter(app_id=app_id, env_id=env_id).first()
                    if not deploy:
                        continue
                    
                    # 检查是否是已发布成功的明细
                    key = (app_id, env_id)
                    if key in published_details:
                        # 只更新 sequence，不修改版本
                        existing = published_details[key]
                        existing.sequence = item.get('sequence', 0)
                        existing.save()
                    else:
                        # 创建新的明细
                        DeployIterationDetail.objects.create(
                            iteration=iteration,
                            deploy_id=deploy.id,
                            version=version,
                            sequence=item.get('sequence', 0),
                            created_by=request.user
                        )

                record_deploy_operation(
                    'iteration', iteration.id, iteration.name, '修改迭代', request.user
                )
                
                result = iteration.to_dict()
                result['env_name'] = iteration.env.name
                result['env_ids'] = form.env_ids
                result['details'] = []
                for detail in iteration.details.all():
                    result['details'].append({
                        'id': detail.id,
                        'deploy_id': detail.deploy_id,
                        'app_id': detail.deploy.app_id if detail.deploy else None,
                        'env_id': detail.deploy.env_id if detail.deploy else None,
                        'app_name': detail.deploy.app.name if detail.deploy and detail.deploy.app else '',
                        'env_name': detail.deploy.env.name if detail.deploy and detail.deploy.env else '',
                        'version': detail.version,
                        'sequence': detail.sequence,
                    })
                result['status_alias'] = iteration.get_status_display()
                result['created_by_user'] = iteration.created_by.nickname
                result['updated_by_user'] = request.user.nickname
                return json_response(result)
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)

    @auth('deploy.iteration.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=True, help='迭代ID必填')
        ).parse(request.GET)
        
        if error is None:
            try:
                iteration = DeployIteration.objects.filter(pk=form.id).first()
                if not iteration:
                    return json_response(error='未找到指定迭代')
                
                # 只有待发布状态才能删除
                if iteration.status != '0':
                    status_map = {'0': '待发布', '1': '发布中', '2': '发布成功', '-1': '已取消', '-3': '发布异常'}
                    return json_response(error=f'当前状态为"{status_map.get(iteration.status, iteration.status)}"，只有待发布状态才能删除')
                
                iteration_id, iteration_name = iteration.id, iteration.name
                iteration.delete()
                record_deploy_operation(
                    'iteration',
                    iteration_id,
                    iteration_name,
                    '删除迭代',
                    request.user,
                )
                return json_response()
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)


class IterationPublishView(View):
    """迭代按环境发布视图"""
    
    @auth('deploy.iteration.do')
    def post(self, request):
        """按环境发布"""
        form, error = JsonParser(
            Argument('iteration_id', type=int, required=True, help='迭代ID必填'),
            Argument('env_id', type=int, required=True, help='环境ID必填'),
        ).parse(request.body)
        
        if error is None:
            try:
                iteration = DeployIteration.objects.select_for_update().filter(pk=form.iteration_id).first()
                if not iteration:
                    return json_response(error='未找到指定迭代')
                
                # 获取该环境下的所有待发布项 - 兼容处理
                try:
                    details = list(iteration.details.select_for_update().filter(
                        deploy__env_id=form.env_id,
                        status='0'  # 待发布
                    ).order_by('sequence'))
                except Exception:
                    # 字段不存在时获取所有该环境的明细
                    details = list(iteration.details.select_for_update().filter(
                        deploy__env_id=form.env_id
                    ).order_by('sequence'))
                
                if not details:
                    return json_response(error='该环境下没有待发布的项目')

                # 按固定顺序锁定所有发布配置，避免不同迭代或普通发布并发穿透。
                deploy_ids = [detail.deploy_id for detail in details]
                if len(deploy_ids) != len(set(deploy_ids)):
                    return json_response(error='迭代中存在重复的应用环境发布项，请先移除重复项')
                locked_deploys = {}
                for deploy_id in sorted(deploy_ids):
                    locked_deploy, running_request = lock_deploy_and_get_running_request(
                        deploy_id
                    )
                    if not locked_deploy:
                        return json_response(error='未找到迭代明细对应的发布配置')
                    if running_request:
                        return json_response(error=get_running_deploy_error(locked_deploy))
                    locked_deploys[deploy_id] = locked_deploy
                
                # 获取环境配置，用于设置并发数
                env = Environment.objects.filter(pk=form.env_id).first()
                
                # 计算可用并发槽位
                if env and env.conc_num > 0:
                    current_env_count = DeployRequest.objects.filter(deploy__env_id=form.env_id, status='2').count()
                    available_slots = max(0, env.conc_num - current_env_count)
                    if available_slots == 0:
                        return json_response(error=f'{env.name}环境 最大同时发布数量为{env.conc_num}，当前已满，请等待前面的发布完成')
                else:
                    available_slots = None  # 不限制
                
                # 为每个待发布项创建发布申请
                created_requests = []
                pending_dispatches = []  # 收集需要立即启动的发布任务
                dispatched_count = 0
                for detail in details:
                    # 检查是否已有进行中的发布申请 - 兼容处理
                    try:
                        if detail.request_id:
                            existing_req = DeployRequest.objects.filter(pk=detail.request_id).first()
                            if existing_req and existing_req.status in ['-1', '0', '1', '2']:  # 待审核、待发布、发布中
                                continue
                    except AttributeError:
                        pass
                    
                    deploy = locked_deploys[detail.deploy_id]
                    version = detail.version

                    # 校验版本不能为空（迭代创建时若加载未完成可能存储了空字符串）
                    if not version:
                        return json_response(error=f'应用【{deploy.app.name}】未设置发布版本，请先编辑迭代并选择版本后再发布')

                    # 根据发布类型构建 extra 字段和关联镜像
                    # extend: '1' 常规发布, '2' 自定义发布, '3' 容器发布
                    docker_image_id = None
                    if deploy.extend == '3':
                        # 容器发布：检查是否有预传的成功镜像
                        from apps.docker_image.models import DockerImage
                        detail_docker_image_id = getattr(detail, 'docker_image_id', None)
                        detail_image_status = getattr(detail, 'image_status', '0')
                        
                        # 只有镜像上传成功（status='2'）且镜像确实存在且成功（status='5'）时才使用镜像
                        use_prebuilt_image = False
                        if detail_docker_image_id and detail_image_status == '2':
                            docker_image = DockerImage.objects.filter(pk=detail_docker_image_id, status='5').first()
                            if docker_image:
                                # 有可用的预传镜像，使用镜像方式
                                docker_image_id = docker_image.id
                                extra = json.dumps(['docker_image'] + json.loads(docker_image.extra))
                                spug_version = docker_image.spug_version
                                use_prebuilt_image = True
                        
                        if not use_prebuilt_image:
                            # 没有可用的预传镜像，使用常规 tag 方式编译（不是 docker_image 方式）
                            extra = json.dumps(['tag', version, None])
                            spug_version = Repository.make_spug_version(deploy.id)
                    else:
                        # 常规发布/自定义发布: ["tag", "v0.6.3", null]
                        extra = json.dumps(['tag', version, None])
                        spug_version = Repository.make_spug_version(deploy.id)
                    
                    # 获取 host_ids
                    host_ids = deploy.host_ids
                    
                    # 判断是否在并发限制内，可以立即执行
                    can_dispatch = available_slots is None or dispatched_count < available_slots
                    
                    # 创建发布申请
                    deploy_request = DeployRequest.objects.create(
                        deploy=deploy,
                        name=f'迭代：{iteration.name}',
                        type='1',  # 常规发布
                        extra=extra,
                        host_ids=host_ids,
                        version=version,
                        spug_version=spug_version,
                        docker_image_id=docker_image_id,
                        status='2' if can_dispatch else '1',  # 在并发限制内立即发布，否则排队等待
                        do_at=human_datetime() if can_dispatch else None,
                        do_by=request.user or iteration.created_by,  # 优先取点击发布的人，取不到则取迭代创建者
                        desc=f'迭代发布: {iteration.name}',
                        created_by=request.user
                    )
                    record_deploy_operation(
                        'request',
                        deploy_request.id,
                        deploy_request.name,
                        '由迭代发布创建申请',
                        request.user,
                    )
                    
                    # 更新明细状态和关联的发布申请ID - 兼容处理
                    try:
                        detail.status = '1'  # 发布中（含排队等待）
                        detail.request_id = deploy_request.id
                        detail.save()
                    except Exception:
                        pass
                    
                    # 在并发限制内的任务收集起来，事务提交后统一启动
                    if can_dispatch:
                        pending_dispatches.append(deploy_request)
                        dispatched_count += 1
                    
                    created_requests.append({
                        'detail_id': detail.id,
                        'request_id': deploy_request.id,
                        'app_name': deploy.app.name
                    })
                
                # 更新迭代状态为发布中
                iteration.status = '1'  # 发布中
                iteration.save()
                env_name = env.name if env else str(form.env_id)
                record_deploy_operation(
                    'iteration',
                    iteration.id,
                    iteration.name,
                    f'发布迭代环境【{env_name}】',
                    request.user,
                )
                
                # 使用 on_commit 确保事务提交后再启动发布线程
                for req_obj in pending_dispatches:
                    transaction.on_commit(lambda r=req_obj: Thread(target=dispatch, args=(r, False)).start())
                
                queued_count = len(created_requests) - len(pending_dispatches)
                if queued_count > 0:
                    msg = f'已创建 {len(created_requests)} 个发布申请，{len(pending_dispatches)} 个立即执行，{queued_count} 个排队等待'
                else:
                    msg = f'已创建 {len(created_requests)} 个发布申请'
                return json_response({
                    'message': msg,
                    'requests': created_requests
                })
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)
    
    @auth('deploy.iteration.view')
    def get(self, request):
        """获取迭代发布状态"""
        form, error = JsonParser(
            Argument('iteration_id', type=int, required=True, help='迭代ID必填'),
        ).parse(request.GET)
        
        if error is None:
            try:
                iteration = DeployIteration.objects.filter(pk=form.iteration_id).first()
                if not iteration:
                    return json_response(error='未找到指定迭代')
                
                # 使用 prefetch_related 预加载所有关联数据
                details = list(DeployIterationDetail.objects.filter(
                    iteration=iteration
                ).select_related(
                    'deploy', 'deploy__app', 'deploy__env'
                ))

                # 发布申请是状态源，先校准明细再统计，避免本次响应继续返回旧的“发布中”状态
                reconcile_iteration_detail_statuses(details)

                # 仅用于页面风险提示，不改变发布申请的创建和调度规则。
                cross_iteration_warnings = get_cross_iteration_warnings(
                    iteration,
                    details,
                )
                
                # 批量获取所有关联的发布申请
                request_ids = [d.request_id for d in details if d.request_id]
                requests_map = {}
                if request_ids:
                    requests_qs = DeployRequest.objects.filter(pk__in=request_ids).select_related(
                        'deploy', 'deploy__env'
                    )
                    requests_map = {r.id: r for r in requests_qs}
                
                # 批量获取所有关联的 Docker 镜像
                from apps.docker_image.models import DockerImage
                docker_image_ids = [getattr(d, 'docker_image_id', None) for d in details if getattr(d, 'docker_image_id', None)]
                docker_images_map = {}
                if docker_image_ids:
                    docker_images_qs = DockerImage.objects.filter(pk__in=docker_image_ids)
                    docker_images_map = {img.id: img for img in docker_images_qs}
                
                # 需要更新状态的明细列表
                details_to_update = []
                
                # 按环境分组统计发布状态
                env_status = {}
                for detail in details:
                    if not detail.deploy or not detail.deploy.env_id:
                        continue
                    
                    env_id = detail.deploy.env_id
                    is_container = detail.deploy.extend == '3'
                    if env_id not in env_status:
                        env = detail.deploy.env
                        env_status[env_id] = {
                            'env_id': env_id,
                            'env_name': env.name if env else '',
                            'is_prod': env.prod if env else False,
                            'has_container': False,  # 环境是否有容器应用
                            'total': 0,
                            'pending': 0,
                            'publishing': 0,
                            'success': 0,
                            'failed': 0,
                            'image_uploading': 0,  # 镜像上传中数量
                            'image_success': 0,    # 镜像上传成功数量
                            'image_failed': 0,     # 镜像上传失败数量
                            'details': []
                        }
                    
                    # 更新环境是否有容器应用
                    if is_container:
                        env_status[env_id]['has_container'] = True
                    
                    env_status[env_id]['total'] += 1
                    # 兼容处理：字段可能不存在
                    try:
                        detail_status = detail.status
                        detail_status_alias = detail.get_status_display()
                        detail_request_id = detail.request_id
                        detail_image_status = getattr(detail, 'image_status', '0')
                        detail_docker_image_id = getattr(detail, 'docker_image_id', None)
                    except AttributeError:
                        detail_status = '0'
                        detail_status_alias = '待发布'
                        detail_request_id = None
                        detail_image_status = '0'
                        detail_docker_image_id = None
                    
                    # 如果有关联的发布申请，获取其状态并同步更新明细状态
                    request_status = None
                    request_status_alias = None
                    request_retry_allowed = False
                    request_retry_deadline = None
                    request_retry_error = ''
                    if detail_request_id:
                        req = requests_map.get(detail_request_id)
                        if req:
                            request_status = req.status
                            request_status_alias = req.get_status_display()
                            retry_info = get_deploy_retry_info(req)
                            request_retry_allowed = retry_info['retry_allowed']
                            request_retry_deadline = retry_info['retry_deadline']
                            request_retry_error = retry_info['retry_error']
                            expected_detail_status = get_iteration_detail_status(req.status)
                            if expected_detail_status and expected_detail_status != detail_status:
                                detail.status = expected_detail_status
                                detail_status = expected_detail_status
                                detail_status_alias = dict(
                                    DeployIterationDetail.STATUS_CHOICES
                                ).get(expected_detail_status, detail_status_alias)
                                details_to_update.append(detail)

                    # 必须在发布申请状态校准之后统计，保证本次响应的汇总和明细一致
                    if detail_status == '0':
                        env_status[env_id]['pending'] += 1
                    elif detail_status == '1':
                        env_status[env_id]['publishing'] += 1
                    elif detail_status == '2':
                        env_status[env_id]['success'] += 1
                    elif detail_status == '3':
                        env_status[env_id]['failed'] += 1

                    # 镜像上传状态统计
                    if detail_image_status == '1':
                        env_status[env_id]['image_uploading'] += 1
                    elif detail_image_status == '2':
                        env_status[env_id]['image_success'] += 1
                    elif detail_image_status == '3':
                        env_status[env_id]['image_failed'] += 1
                    
                    # 获取镜像信息（从预加载的map中获取）
                    docker_image_info = None
                    if detail_docker_image_id:
                        docker_image = docker_images_map.get(detail_docker_image_id)
                        if docker_image:
                            docker_image_info = {
                                'id': docker_image.id,
                                'status': docker_image.status,
                                'status_alias': docker_image.get_status_display(),
                                'version': docker_image.version,
                            }
                    
                    env_status[env_id]['details'].append({
                        'id': detail.id,
                        'deploy_id': detail.deploy_id,
                        'app_id': detail.deploy.app_id if detail.deploy else None,
                        'env_id': detail.deploy.env_id if detail.deploy else None,
                        'app_name': detail.deploy.app.name if detail.deploy and detail.deploy.app else '',
                        'version': detail.version,
                        'status': detail_status,
                        'status_alias': detail_status_alias,
                        'request_id': detail_request_id,
                        'request_status': request_status,
                        'request_status_alias': request_status_alias,
                        'request_retry_allowed': request_retry_allowed,
                        'request_retry_deadline': request_retry_deadline,
                        'request_retry_error': request_retry_error,
                        'sequence': detail.sequence,
                        'is_container': detail.deploy.extend == '3',  # 是否容器发布
                        'image_status': detail_image_status,
                        'image_status_alias': dict(DeployIterationDetail.IMAGE_STATUS_CHOICES).get(detail_image_status, '未上传'),
                        'docker_image_id': detail_docker_image_id,
                        'docker_image': docker_image_info,
                        'cross_iteration_warning': cross_iteration_warnings.get(detail.id, {
                            'has_warning': False,
                            'level': 'none',
                            'kind': 'none',
                            'label': '',
                            'message': '',
                            'latest_success': None,
                            'related_iterations': [],
                        }),
                    })
                
                # 批量更新需要同步的明细状态
                if details_to_update:
                    try:
                        DeployIterationDetail.objects.bulk_update(details_to_update, ['status'])
                    except Exception:
                        pass
                
                # 使用统一规则更新迭代主状态，避免发布查询和后台同步出现不同结果
                new_status = get_iteration_overall_status([detail.status for detail in details])
                if new_status and iteration.status != new_status:
                    iteration.status = new_status
                    iteration.save()
                
                # 查询状态时触发僵死清理和排队调度（处理进程崩溃/SSH假死等异常场景）
                try:
                    from apps.deploy.utils import _try_dispatch_queued_requests
                    for env_id_key in env_status:
                        _try_dispatch_queued_requests(iteration, env_id_key)
                except Exception:
                    pass
                
                return json_response(list(env_status.values()))
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)
    
    @auth('deploy.iteration.do')
    def patch(self, request):
        """重试单个发布申请"""
        form, error = JsonParser(
            Argument('detail_id', type=int, required=True, help='明细ID必填'),
        ).parse(request.body)
        
        if error is None:
            try:
                detail = DeployIterationDetail.objects.select_for_update().filter(pk=form.detail_id).first()
                if not detail:
                    return json_response(error='未找到指定明细')
                
                # 检查是否有关联的发布申请
                if not detail.request_id:
                    return json_response(error='该明细没有关联的发布申请，请先点击发布')

                deploy, running_request = lock_deploy_and_get_running_request(
                    detail.deploy_id
                )
                if not deploy:
                    return json_response(error='未找到对应的发布配置')
                deploy_request = DeployRequest.objects.select_for_update().filter(pk=detail.request_id).first()
                if not deploy_request:
                    return json_response(error='未找到关联的发布申请')
                if deploy_request.deploy_id != deploy.id:
                    return json_response(error='迭代明细与发布申请的应用环境不一致')
                
                # 检查发布申请状态，只有失败状态才能重试
                if deploy_request.status not in ['-3', '-2', '0']:  # 失败、异常、审核驳回
                    status_map = {
                        '-3': '发布失败',
                        '-2': '发布异常', 
                        '-1': '待审核',
                        '0': '审核驳回',
                        '1': '待发布',
                        '2': '发布中',
                        '3': '发布成功'
                    }
                    return json_response(error=f'当前状态为"{status_map.get(deploy_request.status, deploy_request.status)}"，不能重试')
                if deploy_request.status in ('-3', '-2'):
                    retry_error = get_deploy_retry_error(deploy_request)
                    if retry_error:
                        return json_response(error=retry_error)

                if running_request:
                    return json_response(error=get_running_deploy_error(deploy))
                
                # 检查环境并发限制
                retry_env = deploy.env
                if retry_env and retry_env.conc_num > 0:
                    current_env_count = DeployRequest.objects.filter(deploy__env_id=retry_env.id, status='2').count()
                    if current_env_count >= retry_env.conc_num:
                        return json_response(error=f'{retry_env.name}环境 最大同时发布数量为{retry_env.conc_num}，当前已满，请等待前面的发布完成')
                
                # 需求3: 容器服务发布失败重试时，判断是否已成功预传镜像，并与记录匹配
                if deploy.extend == '3':  # 容器发布
                    from apps.docker_image.models import DockerImage
                    
                    # 获取原发布申请的发布方式
                    original_extra = json.loads(deploy_request.extra) if deploy_request.extra else []
                    original_is_image_deploy = original_extra and original_extra[0] == 'docker_image'
                    
                    # 检查当前明细是否有成功的预传镜像
                    has_prebuilt_image = False
                    prebuilt_image = None
                    detail_docker_image_id = getattr(detail, 'docker_image_id', None)
                    detail_image_status = getattr(detail, 'image_status', '0')
                    
                    if detail_docker_image_id and detail_image_status == '2':
                        prebuilt_image = DockerImage.objects.filter(pk=detail_docker_image_id, status='5').first()
                        if prebuilt_image:
                            has_prebuilt_image = True
                    
                    # 判断是否需要新建发布申请
                    need_new_request = False
                    if has_prebuilt_image and not original_is_image_deploy:
                        # 有成功的预传镜像，但原发布申请是tag发布方式，需要新建镜像发布申请
                        need_new_request = True
                    elif not has_prebuilt_image and original_is_image_deploy:
                        # 原发布是镜像发布，但现在没有可用镜像（可能被删除），需要新建tag发布申请
                        need_new_request = True
                    elif has_prebuilt_image and original_is_image_deploy:
                        # 原发布是镜像发布，检查镜像ID是否匹配
                        if deploy_request.docker_image_id != detail_docker_image_id:
                            # 镜像ID不匹配，需要新建发布申请
                            need_new_request = True
                    
                    if need_new_request:
                        # 创建新的发布申请
                        iteration = detail.iteration
                        version = detail.version
                        
                        if has_prebuilt_image:
                            # 使用镜像发布方式
                            docker_image_id = prebuilt_image.id
                            extra = json.dumps(['docker_image'] + json.loads(prebuilt_image.extra))
                            spug_version = prebuilt_image.spug_version
                        else:
                            # 使用tag发布方式
                            docker_image_id = None
                            extra = json.dumps(['tag', version, None])
                            spug_version = Repository.make_spug_version(deploy.id)
                        
                        # 创建新发布申请
                        new_request = DeployRequest.objects.create(
                            deploy=deploy,
                            name=f'迭代重试：{iteration.name}',
                            type='1',
                            extra=extra,
                            host_ids=deploy.host_ids,
                            version=version,
                            spug_version=spug_version,
                            docker_image_id=docker_image_id,
                            status='2',  # 发布中
                            do_at=human_datetime(),
                            do_by=request.user,
                            desc=f'迭代发布重试: {iteration.name}',
                            created_by=request.user
                        )
                        
                        # 更新明细关联的发布申请
                        detail.request_id = new_request.id
                        detail.status = '1'  # 发布中
                        detail.save()
                        
                        # 更新迭代状态
                        if iteration.status not in ['1']:
                            iteration.status = '1'
                            iteration.save()
                        record_deploy_operation(
                            'request',
                            new_request.id,
                            new_request.name,
                            '由迭代重试创建申请',
                            request.user,
                        )
                        record_deploy_operation(
                            'iteration',
                            iteration.id,
                            iteration.name,
                            format_app_environment_action('重试', deploy, '发布'),
                            request.user,
                        )
                        
                        # 使用 on_commit 确保事务提交后再启动发布线程
                        _new_req = new_request
                        transaction.on_commit(lambda: Thread(target=dispatch, args=(_new_req, False)).start())
                        
                        return json_response({
                            'message': '已创建新的发布申请并启动发布' + ('（镜像发布）' if has_prebuilt_image else '（标签发布）'),
                            'request_id': new_request.id
                        })
                
                # 普通重试逻辑（非容器或不需要新建）
                deploy_request.status = '2'  # 发布中
                deploy_request.do_at = human_datetime()
                deploy_request.do_by = request.user
                deploy_request.save()
                
                # 更新明细状态
                detail.status = '1'  # 发布中
                detail.save()
                
                # 更新迭代状态为发布中
                iteration = detail.iteration
                if iteration.status != '1':
                    iteration.status = '1'
                    iteration.save()
                record_deploy_operation(
                    'request',
                    deploy_request.id,
                    deploy_request.name,
                    '通过迭代重试发布申请',
                    request.user,
                )
                record_deploy_operation(
                    'iteration',
                    iteration.id,
                    iteration.name,
                    format_app_environment_action('重试', deploy, '发布'),
                    request.user,
                )
                
                # 使用 on_commit 确保事务提交后再启动发布线程
                _retry_req = deploy_request
                transaction.on_commit(lambda: Thread(target=dispatch, args=(_retry_req, False)).start())
                
                return json_response({
                    'message': '已重新启动发布',
                    'request_id': deploy_request.id
                })
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)


class IterationImageView(View):
    """迭代镜像预传视图"""
    
    @staticmethod
    def _sequential_build_images(details_data, iteration_name):
        """按顺序编译镜像，单个失败不影响后续"""
        from apps.docker_image.models import DockerImage
        from apps.docker_image.utils import dispatch
        from apps.deploy.models import DeployIterationDetail
        import logging
        
        logger = logging.getLogger(__name__)
        
        for data in details_data:
            try:
                detail_id = data['detail_id']
                docker_image_id = data['docker_image_id']
                app_name = data['app_name']
                
                # 获取镜像记录
                docker_image = DockerImage.objects.filter(pk=docker_image_id).first()
                if not docker_image:
                    logger.error(f'镜像记录不存在: {docker_image_id}')
                    # 更新明细状态为失败
                    try:
                        detail = DeployIterationDetail.objects.filter(pk=detail_id).first()
                        if detail:
                            detail.image_status = '3'  # 上传失败
                            detail.save()
                    except Exception:
                        pass
                    continue
                
                # 检查同一 deploy 是否有其他正在构建中的镜像（排除当前镜像）
                # 同一时间同一个 deploy（同环境、同应用）只能执行一个构建
                building_image = DockerImage.objects.filter(
                    deploy_id=docker_image.deploy_id,
                    status='1'  # 构建中
                ).exclude(id=docker_image_id).first()
                
                if building_image:
                    logger.warning(f'同一deploy存在构建中的镜像任务，当前任务失败: {app_name} (构建中镜像ID: {building_image.id})')
                    # 将当前镜像标记为失败
                    docker_image.status = '2'  # 失败
                    docker_image.save()
                    # 更新明细状态为失败
                    try:
                        detail = DeployIterationDetail.objects.filter(pk=detail_id).first()
                        if detail:
                            detail.image_status = '3'  # 上传失败
                            detail.save()
                    except Exception:
                        pass
                    continue
                
                # 在编译前再次检查是否已有该 deploy_id + version 的成功镜像
                existing_success_image = DockerImage.objects.filter(
                    deploy_id=docker_image.deploy_id,
                    version=docker_image.version,
                    status='5'  # 成功
                ).exclude(id=docker_image_id).order_by('-id').first()
                
                if existing_success_image:
                    # 找到已成功的镜像，直接复用
                    logger.info(f'发现已有成功镜像，直接复用: {app_name} (镜像ID: {existing_success_image.id})')
                    try:
                        detail = DeployIterationDetail.objects.filter(pk=detail_id).first()
                        if detail:
                            detail.image_status = '2'  # 上传成功
                            detail.docker_image_id = existing_success_image.id
                            detail.save()
                        # 删除当前创建的未使用镜像记录
                        docker_image.delete()
                    except Exception as e:
                        logger.error(f'复用镜像失败: {str(e)}')
                    continue
                
                logger.info(f'开始编译镜像: {app_name} (迭代: {iteration_name})')
                
                # 同步执行镜像编译
                try:
                    dispatch(docker_image)
                    logger.info(f'镜像编译成功: {app_name}')
                except Exception as e:
                    logger.error(f'镜像编译失败: {app_name}, 错误: {str(e)}')
                    # dispatch 内部已经设置了状态为 '2' (失败) 并更新了迭代明细状态
                    # 继续下一个
                    continue
                    
            except Exception as e:
                logger.error(f'处理镜像任务失败: {str(e)}')
                continue
    
    @auth('deploy.iteration.do')
    def post(self, request):
        """预传镜像 - 为指定环境的容器应用创建镜像编译任务"""
        form, error = JsonParser(
            Argument('iteration_id', type=int, required=True, help='迭代ID必填'),
            Argument('env_id', type=int, required=True, help='环境ID必填'),
        ).parse(request.body)
        
        if error is None:
            try:
                from apps.docker_image.models import DockerImage
                from threading import Thread
                
                iteration = DeployIteration.objects.select_for_update().filter(pk=form.iteration_id).first()
                if not iteration:
                    return json_response(error='未找到指定迭代')
                
                # 获取该环境下所有容器发布类型的待发布项
                details = iteration.details.select_for_update().filter(
                    deploy__env_id=form.env_id,
                    deploy__extend='3',  # 容器发布
                ).order_by('sequence')
                
                if not details.exists():
                    return json_response(error='该环境下没有容器发布类型的项目')
                
                created_images = []
                skipped = []
                failed = []
                
                for detail in details:
                    try:
                        deploy = detail.deploy
                        version = detail.version
                        app_name = deploy.app.name if deploy and deploy.app else f'应用ID:{detail.deploy_id}'
                        
                        # 检查是否已有镜像或正在上传
                        try:
                            if detail.image_status in ['1', '2']:  # 上传中或已上传
                                skipped.append({'app_name': app_name, 'reason': '镜像已上传或正在上传中'})
                                continue
                        except AttributeError:
                            pass
                        
                        # 检查是否存在该 deploy_id + version 的成功镜像（可以直接复用）
                        existing_success_image = DockerImage.objects.filter(
                            deploy_id=deploy.id,
                            version=version,
                            status='5'  # 成功
                        ).order_by('-id').first()
                        
                        if existing_success_image:
                            # 找到已成功的镜像，直接复用
                            try:
                                detail.image_status = '2'  # 上传成功
                                detail.docker_image_id = existing_success_image.id
                                detail.save()
                                skipped.append({'app_name': app_name, 'reason': f'复用已有镜像 (ID:{existing_success_image.id})'})
                                continue
                            except Exception:
                                pass
                        
                        # 检查是否存在未完成的编译任务（同一deploy同时只能有一个构建）
                        building_image = DockerImage.objects.filter(
                            deploy_id=deploy.id, 
                            status__in=['0', '1']  # 未开始或构建中
                        ).order_by('-id').first()
                        if building_image:
                            failed.append({'app_name': app_name, 'reason': f'存在构建中的任务(镜像ID:{building_image.id})，同一应用同时只能执行一个构建'})
                            continue
                        
                        # 创建镜像编译任务
                        extra = ['tag', version, None]
                        spug_version = DockerImage.make_spug_version(deploy.id)
                        
                        docker_image = DockerImage.objects.create(
                            app_id=deploy.app_id,
                            env_id=deploy.env_id,
                            deploy_id=deploy.id,
                            version=version,
                            spug_version=spug_version,
                            url='',
                            extra=json.dumps(extra),
                            remarks=f'迭代发布预传: {iteration.name}',
                            created_by=request.user
                        )
                        
                        # 更新明细的镜像状态
                        try:
                            detail.image_status = '1'  # 上传中
                            detail.docker_image_id = docker_image.id
                            detail.save()
                        except Exception:
                            pass
                        
                        created_images.append({
                            'detail_id': detail.id,
                            'docker_image_id': docker_image.id,
                            'app_name': app_name
                        })
                    except Exception as e:
                        # 单个应用失败不影响其他应用
                        app_name = deploy.app.name if deploy and deploy.app else f'应用ID:{detail.deploy_id}'
                        failed.append({
                            'app_name': app_name, 
                            'reason': str(e)
                        })
                        continue
                
                # 启动后台线程按顺序编译镜像
                # 使用 on_commit 确保事务提交后再启动线程，避免子线程读不到刚写入的 DockerImage 记录
                if created_images:
                    _created = created_images[:]
                    _name = iteration.name
                    transaction.on_commit(lambda: Thread(target=self._sequential_build_images, args=(_created, _name)).start())
                
                # 点击预传镜像后，将迭代状态改为发布中
                # 只要有创建任务或有复用镜像，都更新状态
                has_image_action = len(created_images) > 0 or any('复用已有镜像' in s.get('reason', '') for s in skipped)
                if has_image_action and iteration.status == '0':  # 只有待发布状态才更新
                    iteration.status = '1'  # 发布中
                    iteration.save()
                if has_image_action:
                    env_name = Environment.objects.filter(
                        pk=form.env_id
                    ).values_list('name', flat=True).first() or str(form.env_id)
                    record_deploy_operation(
                        'iteration',
                        iteration.id,
                        iteration.name,
                        f'预传环境【{env_name}】镜像',
                        request.user,
                    )
                
                result_msg = f'已创建 {len(created_images)} 个镜像编译任务'
                if skipped:
                    result_msg += f'，跳过 {len(skipped)} 个'
                if failed:
                    fail_details = '\n'.join(f'应用[{f["app_name"]}] 错误[{f["reason"]}]' for f in failed)
                    result_msg += f'，失败 {len(failed)} 个\n{fail_details}'
                
                return json_response({
                    'message': result_msg,
                    'created': created_images,
                    'skipped': skipped,
                    'failed': failed
                })
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)
    
    @auth('deploy.iteration.do')
    def patch(self, request):
        """重试单个镜像上传"""
        form, error = JsonParser(
            Argument('detail_id', type=int, required=True, help='明细ID必填'),
        ).parse(request.body)
        
        if error is None:
            try:
                from apps.docker_image.models import DockerImage
                from apps.docker_image.utils import dispatch
                from threading import Thread
                
                detail = DeployIterationDetail.objects.select_related(
                    'iteration', 'deploy__app', 'deploy__env'
                ).filter(pk=form.detail_id).first()
                if not detail:
                    return json_response(error='未找到指定明细')
                
                deploy = detail.deploy
                version = detail.version
                iteration = detail.iteration
                app_name = deploy.app.name if deploy.app else str(deploy.app_id)
                
                if deploy.extend != '3':
                    return json_response(error='该应用不是容器发布类型')
                
                # 先检查是否已有该 deploy_id + version 的成功镜像
                existing_success_image = DockerImage.objects.filter(
                    deploy_id=deploy.id,
                    version=version,
                    status='5'  # 成功
                ).order_by('-id').first()
                
                if existing_success_image:
                    # 找到已成功的镜像，直接复用
                    detail.image_status = '2'  # 上传成功
                    detail.docker_image_id = existing_success_image.id
                    detail.save()
                    record_deploy_operation(
                        'iteration',
                        iteration.id,
                        iteration.name,
                        format_app_environment_action('重试', deploy, '镜像'),
                        request.user,
                    )
                    return json_response({
                        'message': f'已复用已有成功镜像 (ID: {existing_success_image.id})',
                        'docker_image_id': existing_success_image.id
                    })
                
                # 如果已有镜像记录，检查状态并重新编译
                if detail.docker_image_id:
                    docker_image = DockerImage.objects.filter(pk=detail.docker_image_id).first()
                    if docker_image:
                        if docker_image.status in ['0', '1']:
                            return json_response(error='镜像正在编译中，请稍后')
                        if docker_image.status == '5':
                            # 镜像已成功，直接更新状态
                            detail.image_status = '2'  # 上传成功
                            detail.save()
                            record_deploy_operation(
                                'iteration',
                                iteration.id,
                                iteration.name,
                                format_app_environment_action('重试', deploy, '镜像'),
                                request.user,
                            )
                            return json_response({
                                'message': '镜像已编译成功，无需重试',
                                'docker_image_id': docker_image.id
                            })
                        # 失败状态（'2'），检查同一deploy是否有其他构建中的任务
                        building_image = DockerImage.objects.filter(
                            deploy_id=deploy.id,
                            status__in=['0', '1']  # 未开始或构建中
                        ).exclude(id=docker_image.id).first()
                        if building_image:
                            return json_response(error=f'存在构建中的任务(镜像ID:{building_image.id})，同一应用同时只能执行一个构建')
                        # 重新编译
                        docker_image.status = '0'
                        docker_image.save()
                        detail.image_status = '1'  # 上传中
                        detail.save()
                        record_deploy_operation(
                            'iteration',
                            iteration.id,
                            iteration.name,
                            format_app_environment_action('重试', deploy, '镜像'),
                            request.user,
                        )
                        Thread(target=dispatch, args=(docker_image,)).start()
                        return json_response({
                            'message': '已重新启动镜像编译',
                            'docker_image_id': docker_image.id
                        })
                
                # 创建新的镜像编译任务前，检查同一deploy是否有构建中的任务
                building_image = DockerImage.objects.filter(
                    deploy_id=deploy.id,
                    status__in=['0', '1']  # 未开始或构建中
                ).first()
                if building_image:
                    return json_response(error=f'存在构建中的任务(镜像ID:{building_image.id})，同一应用同时只能执行一个构建')
                
                # 创建新的镜像编译任务
                extra = ['tag', version, None]
                spug_version = DockerImage.make_spug_version(deploy.id)
                
                docker_image = DockerImage.objects.create(
                    app_id=deploy.app_id,
                    env_id=deploy.env_id,
                    deploy_id=deploy.id,
                    version=version,
                    spug_version=spug_version,
                    url='',
                    extra=json.dumps(extra),
                    remarks=f'迭代发布重试: {detail.iteration.name}',
                    created_by=request.user
                )
                
                detail.image_status = '1'
                detail.docker_image_id = docker_image.id
                detail.save()
                record_deploy_operation(
                    'iteration',
                    iteration.id,
                    iteration.name,
                    format_app_environment_action('重试', deploy, '镜像'),
                    request.user,
                )
                
                Thread(target=dispatch, args=(docker_image,)).start()
                
                return json_response({'message': '已创建镜像编译任务', 'docker_image_id': docker_image.id})
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)


class IterationDetailView(View):
    """迭代详情管理视图 - 更新版本等"""
    
    @auth('deploy.iteration.edit')
    def put(self, request):
        """更新迭代详情的版本"""
        form, error = JsonParser(
            Argument('detail_id', type=int, required=True, help='详情ID必填'),
            Argument('version', type=str, required=True, help='版本必填'),
        ).parse(request.body)
        if error is None:
            try:
                detail = DeployIterationDetail.objects.select_for_update().select_related(
                    'iteration', 'deploy__app', 'deploy__env'
                ).get(pk=form.detail_id)
                iteration = detail.iteration
                
                # 检查迭代状态 - 已完全成功的迭代不允许修改
                if iteration.status == '2':
                    return json_response(error='迭代已全部发布成功，无法修改版本')
                
                # 检查是否可以修改版本
                # 如果镜像正在上传中，不允许修改
                if detail.image_status == '1':
                    return json_response(error='镜像正在上传中，无法修改版本')
                
                # 如果镜像已成功上传，不允许修改
                if detail.image_status == '2':
                    return json_response(error='镜像已成功上传，无法修改版本')
                
                # 如果发布已成功，不允许修改
                if detail.status == '2':
                    return json_response(error='该应用已发布成功，无法修改版本')

                if detail.status == '1':
                    return json_response(error='该应用正在发布中，无法修改版本')

                # 发布失败后修改版本会重置为待发布，必须受同一重试窗口约束。
                if detail.status == '3':
                    if not detail.request_id:
                        return json_response(error='该应用没有关联的失败发布申请，无法修改版本')
                    deploy_request = DeployRequest.objects.select_for_update().select_related(
                        'deploy__env'
                    ).filter(
                        pk=detail.request_id,
                        deploy_id=detail.deploy_id,
                    ).first()
                    if not deploy_request:
                        return json_response(error='未找到该应用关联的失败发布申请，无法修改版本')
                    retry_error = get_deploy_retry_error(deploy_request)
                    if retry_error:
                        return json_response(error=retry_error)
                
                # 更新版本
                detail.version = form.version
                # 重置镜像状态（如果有）
                if detail.image_status in ['3']:  # 只重置失败状态
                    detail.image_status = '0'
                    detail.docker_image_id = None
                # 重置发布状态（如果是失败状态）
                if detail.status == '3':
                    detail.status = '0'
                    detail.request_id = None
                detail.save()
                record_deploy_operation(
                    'iteration',
                    iteration.id,
                    iteration.name,
                    format_app_environment_action('修改', detail.deploy, '版本'),
                    request.user,
                )
                
                return json_response({'message': '版本更新成功'})
            except DeployIterationDetail.DoesNotExist:
                return json_response(error='详情不存在')
            except Exception as e:
                return json_response(error=str(e))
        return json_response(error=error)

    @auth('deploy.iteration.do')
    def delete(self, request):
        """移除尚未开始镜像预传或发布的迭代明细。"""
        form, error = JsonParser(
            Argument('detail_id', type=int, required=True, help='详情ID必填'),
        ).parse(request.GET)
        if error is not None:
            return json_response(error=error)

        try:
            detail_snapshot = DeployIterationDetail.objects.filter(pk=form.detail_id).only(
                'iteration_id'
            ).first()
            if not detail_snapshot:
                return json_response(error='详情不存在')

            with transaction.atomic():
                iteration = DeployIteration.objects.select_for_update().get(
                    pk=detail_snapshot.iteration_id
                )
                detail = DeployIterationDetail.objects.select_for_update().select_related(
                    'deploy', 'deploy__app', 'deploy__env'
                ).filter(pk=form.detail_id, iteration=iteration).first()
                if not detail:
                    return json_response(error='详情不存在或已被移除')
                remove_error = get_iteration_detail_remove_error(detail)
                if remove_error:
                    return json_response(error=remove_error)
                if iteration.details.count() <= 1:
                    return json_response(error='迭代至少需要保留一个应用')

                app_name = detail.deploy.app.name if detail.deploy and detail.deploy.app else ''
                detail.delete()
                remaining_statuses = iteration.details.values_list('status', flat=True)
                new_status = get_iteration_overall_status(remaining_statuses)
                if new_status and iteration.status != new_status:
                    iteration.status = new_status
                    iteration.save()
                iteration_status = new_status or iteration.status
                record_deploy_operation(
                    'iteration',
                    iteration.id,
                    iteration.name,
                    format_app_environment_action('移除', detail.deploy),
                    request.user,
                )

            return json_response({
                'message': f'应用【{app_name}】已从迭代中移除',
                'iteration_status': iteration_status,
            })
        except DeployIteration.DoesNotExist:
            return json_response(error='迭代不存在')
        except Exception as e:
            return json_response(error=str(e))
