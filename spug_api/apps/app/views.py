# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.db.models import F
from django.db import transaction
from django.conf import settings
from libs import JsonParser, Argument, json_response, auth
from apps.app.models import App, Deploy, DeployExtend1, DeployExtend2, DeployExtend3
from apps.config.models import Config, ConfigHistory, Service, Tag
from apps.app.utils import (
    fetch_versions,
    clean_deploy_repo,
    has_app_env_scope,
    remove_repo,
    scoped_deploys,
)
from apps.apis.deploy import get_deploy_webhook_key
from apps.account.utils import has_host_perm
from apps.setting.utils import AppSetting
from pathlib import Path
import json
import logging
import re


logger = logging.getLogger(__name__)


class AppView(View):
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False)
        ).parse(request.GET)
        if error is None:
            if request.user.is_supper:
                apps = App.objects.all()
            else:
                ids = request.user.deploy_perms['apps']
                apps = App.objects.filter(id__in=ids)

            if form.id:
                app = apps.filter(pk=form.id).first()
                return json_response(app)
            return json_response(apps)
        return json_response(error=error)

    @auth('deploy.app.add|deploy.app.edit|config.app.add|config.app.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入服务名称'),
            Argument('rel_tags', type=list, required=False),
            Argument('key', help='请输入唯一标识符'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if not re.fullmatch(r'\w+', form.key, re.ASCII):
                return json_response(error='标识符必须为字母、数字和下划线的组合')

            app = App.objects.filter(key=form.key).first()
            if app and app.id != form.id:
                return json_response(error='该识符已存在，请更改后重试')
            service = Service.objects.filter(key=form.key).first()
            if service:
                return json_response(error=f'该标识符已被服务 {service.name} 使用，请更改后重试')
            if form.id:
                App.objects.filter(pk=form.id).update(**form)
            else:
                app = App.objects.create(created_by=request.user, **form)
                if form.rel_tags is not None:
                    app.rel_tags = json.dumps(form.rel_tags)
                app.sort_id = app.id
                app.save()
        return json_response(error=error)

    @auth('deploy.app.edit|config.app.edit_config')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('rel_tags', type=list, required=False),
            Argument('rel_apps', type=list, required=False),
            Argument('rel_services', type=list, required=False),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False)
        ).parse(request.body)
        if error is None:
            app = App.objects.filter(pk=form.id).first()
            if not app:
                return json_response(error='未找到指定应用')
            if form.rel_tags is not None:
                app.rel_tags = json.dumps(form.rel_tags)
            if form.rel_apps is not None:
                app.rel_apps = json.dumps(form.rel_apps)
            if form.rel_services is not None:
                app.rel_services = json.dumps(form.rel_services)
            if form.sort:
                if form.sort == 'up':
                    tmp = App.objects.filter(sort_id__gt=app.sort_id).last()
                else:
                    tmp = App.objects.filter(sort_id__lt=app.sort_id).first()
                if tmp:
                    tmp.sort_id, app.sort_id = app.sort_id, tmp.sort_id
                    tmp.save()
            app.save()
        return json_response(error=error)

    @auth('deploy.app.del|config.app.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            if Deploy.objects.filter(app_id=form.id).exists():
                return json_response(error='该应用在应用发布中已存在关联的发布配置，请删除相关发布配置后再尝试删除')
            # auto delete configs
            Config.objects.filter(type='app', o_id=form.id).delete()
            ConfigHistory.objects.filter(type='app', o_id=form.id).delete()
            for app in App.objects.filter(rel_apps__isnull=False):
                rel_apps = json.loads(app.rel_apps)
                if form.id in rel_apps:
                    rel_apps.remove(form.id)
                    app.rel_apps = json.dumps(rel_apps)
                    app.save()
            App.objects.filter(pk=form.id).delete()
        return json_response(error=error)


class DeployView(View):
    @auth('deploy.app.view|deploy.request.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('app_id', type=int, required=False)
        ).parse(request.GET, True)
        if not request.user.is_supper:
            perms = request.user.deploy_perms
            form.app_id__in = perms['apps']
            form.env_id__in = perms['envs']
        deploys = Deploy.objects.filter(**form) \
            .annotate(app_name=F('app__name'), app_key=F('app__key'), app_rel_tags=F('app__rel_tags'), env_name=F('env__name'), env_prod=F('env__prod')) \
            .order_by('-app__sort_id')
        return json_response(deploys)

    @auth('deploy.app.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('app_id', type=int, help='请选择应用'),
            Argument('env_id', type=int, help='请选择环境'),
            Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择要部署的主机'),
            Argument('rst_notify', type=dict, help='请选择发布结果通知方式'),
            Argument('extend', filter=lambda x: x in dict(Deploy.EXTENDS), help='请选择发布类型'),
            Argument('is_parallel', type=bool, default=True),
            Argument('is_audit', type=bool, default=False)
        ).parse(request.body)
        if error is None:
            if not has_app_env_scope(
                    request.user, form.app_id, form.env_id):
                return json_response(error='未找到发布配置或无操作权限')
            if form.id and not scoped_deploys(request.user).filter(
                    pk=form.id).exists():
                return json_response(error='未找到发布配置或无操作权限')
            if not has_host_perm(request.user, form.host_ids):
                return json_response(error='无权访问目标主机')
            deploy = Deploy.objects.filter(app_id=form.app_id, env_id=form.env_id).first()
            if deploy and deploy.id != form.id:
                return json_response(error='应用在该环境下已经存在发布配置')
            form.host_ids = json.dumps(form.host_ids)
            form.rst_notify = json.dumps(form.rst_notify)
            if form.extend == '1':
                extend_form, error = JsonParser(
                    Argument('git_repo', handler=str.strip, help='请输入git仓库地址'),
                    Argument('dst_dir', handler=str.strip, help='请输入发布部署路径'),
                    Argument('dst_repo', handler=str.strip, help='请输入发布存储路径'),
                    Argument('versions', type=int, filter=lambda x: x > 0, help='请输入发布保留版本数量'),
                    Argument('filter_rule', type=dict, help='参数错误'),
                    Argument('hook_pre_server', handler=str.strip, default=''),
                    Argument('hook_post_server', handler=str.strip, default=''),
                    Argument('hook_pre_host', handler=str.strip, default=''),
                    Argument('hook_post_host', handler=str.strip, default='')
                ).parse(request.body)
                if error:
                    return json_response(error=error)
                extend_form.dst_dir = extend_form.dst_dir.rstrip('/')
                extend_form.filter_rule = json.dumps(extend_form.filter_rule)
                if form.id:
                    extend = DeployExtend1.objects.filter(deploy_id=form.id).first()
                    if extend.git_repo != extend_form.git_repo:
                        remove_repo(form.id)
                    Deploy.objects.filter(pk=form.id).update(**form)
                    DeployExtend1.objects.filter(deploy_id=form.id).update(**extend_form)
                else:
                    deploy = Deploy.objects.create(created_by=request.user, **form)
                    DeployExtend1.objects.create(deploy=deploy, **extend_form)
            elif form.extend == '2':
                extend_form, error = JsonParser(
                    Argument('server_actions', type=list, help='请输入执行动作'),
                    Argument('host_actions', type=list, help='请输入执行动作')
                ).parse(request.body)
                if error:
                    return json_response(error=error)
                if len(extend_form.server_actions) + len(extend_form.host_actions) == 0:
                    return json_response(error='请至少设置一个执行的动作')
                extend_form.require_upload = any(x.get('src_mode') == '1' for x in extend_form.host_actions)
                extend_form.server_actions = json.dumps(extend_form.server_actions)
                extend_form.host_actions = json.dumps(extend_form.host_actions)
                if form.id:
                    Deploy.objects.filter(pk=form.id).update(**form)
                    DeployExtend2.objects.filter(deploy_id=form.id).update(**extend_form)
                else:
                    deploy = Deploy.objects.create(created_by=request.user, **form)
                    DeployExtend2.objects.create(deploy=deploy, **extend_form)
            if form.extend == '3':
                extend_form, error = JsonParser(
                    Argument('git_repo', handler=str.strip, help='请输入git仓库地址'),
                    Argument('dst_dir', handler=str.strip, help='请输入发布部署路径'),
                    Argument('dst_repo', handler=str.strip, help='请输入发布存储路径'),
                    Argument('versions', type=int, filter=lambda x: x > 0, help='请输入发布保留版本数量'),
                    Argument('filter_rule', type=dict, help='filter_rule 参数错误'),
                    Argument('hook_pre_server', handler=str.strip, default=''),
                    Argument('hook_post_server', handler=str.strip, default=''),
                    Argument('hook_pre_image', handler=str.strip, default=''),
                    Argument('hook_post_image', handler=str.strip, default=''),
                    Argument('hook_pre_host', handler=str.strip, default=''),
                    Argument('hook_post_host', handler=str.strip, default=''),
                    Argument('hook_restart_host', handler=str.strip, default=''),
                    Argument('image_name', handler=str.strip, default=''),
                    Argument('image_version', handler=str.strip, default=''),
                    Argument('build_image_host_id', handler=str.strip, default=''),
                    Argument('dockerfile_params', type=list, help='dockerfile_params参数错误'),
                    Argument('yaml_params', type=list, help='yaml_params参数错误')
                ).parse(request.body)
                if error:
                    return json_response(error=error)
                if not has_host_perm(
                        request.user, extend_form.build_image_host_id):
                    return json_response(error='无权访问镜像构建主机')
                extend_form.dst_dir = extend_form.dst_dir.rstrip('/')
                extend_form.filter_rule = json.dumps(extend_form.filter_rule)
                extend_form.dockerfile_params = json.dumps(extend_form.dockerfile_params)
                extend_form.yaml_params = json.dumps(extend_form.yaml_params)
                
                if form.id:
                    extend = DeployExtend3.objects.filter(deploy_id=form.id).first()
                    if extend.git_repo != extend_form.git_repo:
                        remove_repo(form.id)
                    Deploy.objects.filter(pk=form.id).update(**form)
                    DeployExtend3.objects.filter(deploy_id=form.id).update(**extend_form)
                else:
                    deploy = Deploy.objects.create(created_by=request.user, **form)
                    DeployExtend3.objects.create(deploy=deploy, **extend_form)
        return json_response(error=error)

    @auth('deploy.app.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            deploy = scoped_deploys(request.user).filter(pk=form.id).first()
            if not deploy:
                return json_response(error='未找到发布配置或无操作权限')
            if deploy.deployrequest_set.exists():
                return json_response(error='已存在关联的发布记录，请删除关联的发布记录后再尝试删除发布配置')
            for item in deploy.repository_set.all():
                item.delete()
            for item in deploy.dockerimage_set.all():
                item.delete()
            deploy.delete()
        return json_response(error=error)
    
@auth('deploy.app.view|deploy.request.view')
def get_info(request, deploy_id):
    deploys = scoped_deploys(request.user).filter(pk=deploy_id) \
        .annotate(app_name=F('app__name'), app_key=F('app__key'), app_rel_tags=F('app__rel_tags'), env_name=F('env__name'), env_prod=F('env__prod')) \
        .order_by('-app__sort_id').first()
    if not deploys:
        return json_response(error='未找到发布配置或无操作权限')
    return json_response(deploys)

@auth('deploy.app.config|deploy.repository.add|deploy.request.add|deploy.request.edit')
def get_versions(request, d_id):
    from django.core.cache import cache
    deploy = scoped_deploys(request.user).filter(pk=d_id).first()
    if not deploy:
        return json_response(error='未找到发布配置或无操作权限')
    if deploy.extend == '2':
        return json_response(error='该应用不支持此操作')
    # 强制刷新参数：?refresh=1 时跳过缓存重新拉取
    force_refresh = request.GET.get('refresh') == '1'
    cache_key = f'app_versions_{d_id}'
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return json_response(cached)
    branches, tags = fetch_versions(deploy)
    result = {'branches': branches, 'tags': tags}
    cache.set(cache_key, result, 60)    # 缓存 1 分钟
    return json_response(result)


@auth('deploy.app.clean')
def clean_repo(request):
    form, error = JsonParser(
        Argument('deploy_id', type=int, help='请指定发布配置'),
        Argument(
            'target',
            filter=lambda x: x in ('repo', 'node_modules'),
            help='请选择正确的清理范围',
        ),
    ).parse(request.body)
    if error:
        return json_response(error=error)

    operator_id = getattr(request.user, 'id', None)
    with transaction.atomic():
        deploy = scoped_deploys(request.user).select_for_update() \
            .select_related('app').filter(pk=form.deploy_id).first()
        if not deploy:
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s reason=not_found_or_out_of_scope',
                operator_id, form.deploy_id, form.target,
            )
            return json_response(error='未找到发布配置或无操作权限')

        try:
            tag_ids = json.loads(deploy.app.rel_tags or '[]')
        except (TypeError, ValueError):
            tag_ids = []
        if not Tag.objects.filter(pk__in=tag_ids, key='front').exists():
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s reason=not_frontend',
                operator_id, deploy.id, form.target,
            )
            return json_response(error='仅标记为前端的应用可以清理发布目录')

        if deploy.extend == '2' and form.target == 'repo':
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s reason=custom_deploy_uploads',
                operator_id, deploy.id, form.target,
            )
            return json_response(error='自定义发布的目录可能包含上传制品，仅允许清理 node_modules')

        from apps.deploy.models import DeployRequest
        if DeployRequest.objects.filter(
                deploy_id=deploy.id,
                status__in=('2', '-2')).exists():
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s reason=active_deploy',
                operator_id, deploy.id, form.target,
            )
            return json_response(
                error='该发布配置存在发布中或结果未知的申请，暂不能清理目录',
            )

        from apps.repository.models import Repository
        from apps.docker_image.models import DockerImage
        if Repository.objects.filter(
                deploy_id=deploy.id, status__in=('0', '1')).exists() \
                or DockerImage.objects.filter(
                    deploy_id=deploy.id, status__in=('0', '1')).exists():
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s reason=active_build',
                operator_id, deploy.id, form.target,
            )
            return json_response(error='该发布配置存在未完成的构建任务，暂不能清理目录')

        clean_path = Path(settings.REPOS_DIR).resolve() / str(deploy.id)
        if form.target == 'node_modules':
            clean_path /= 'node_modules'
        logger.warning(
            'deploy_repo_cleanup started operator_id=%s deploy_id=%s '
            'app_id=%s env_id=%s target=%s path=%s',
            operator_id, deploy.id, deploy.app_id, deploy.env_id,
            form.target, clean_path,
        )
        try:
            removed = clean_deploy_repo(deploy.id, form.target)
        except ValueError as exc:
            logger.warning(
                'deploy_repo_cleanup rejected operator_id=%s deploy_id=%s '
                'target=%s path=%s reason=%s',
                operator_id, deploy.id, form.target, clean_path, exc,
            )
            return json_response(error=f'清理失败：{exc}')
        except OSError as exc:
            logger.exception(
                'deploy_repo_cleanup failed operator_id=%s deploy_id=%s '
                'target=%s path=%s',
                operator_id, deploy.id, form.target, clean_path,
            )
            return json_response(error=f'清理失败：{exc}')

        logger.warning(
            'deploy_repo_cleanup finished operator_id=%s deploy_id=%s '
            'target=%s path=%s result=%s',
            operator_id, deploy.id, form.target, clean_path,
            'removed' if removed else 'not_found',
        )
        return json_response({
            'removed': removed,
            'target': form.target,
        })


@auth('deploy.app.config|deploy.app.edit')
def kit_key(request):
    form, error = JsonParser(
        Argument('key', filter=lambda x: x in ('api_key', 'public_key'), help='参数错误'),
        Argument('deploy_id', type=int, required=False),
    ).parse(request.body)
    if error is None:
        if form.key == 'public_key':
            return json_response(AppSetting.get_default('public_key'))
        if not form.deploy_id:
            return json_response(error='缺少发布配置参数')
        deploy = scoped_deploys(request.user).filter(pk=form.deploy_id).first()
        if not deploy:
            return json_response(error='未找到发布配置或无操作权限')
        return json_response(get_deploy_webhook_key(deploy.id))
    return json_response(error=error)
