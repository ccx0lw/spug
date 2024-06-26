# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.db.models import F
from libs import json_response, JsonParser, Argument, auth
from apps.app.models import Deploy, App
from apps.repository.models import Repository
from apps.config.models import *
import json
import re


class EnvironmentView(View):
    def get(self, request):
        query = {}
        if not request.user.is_supper:
            query['id__in'] = request.user.deploy_perms['envs']
        envs = Environment.objects.filter(**query)
        return json_response(envs)

    @auth('config.env.add|config.env.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入环境名称'),
            Argument('key', help='请输入唯一标识符'),
            Argument('prod', type=bool, default=False, required=False),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if not re.fullmatch(r'\w+', form.key, re.ASCII):
                return json_response(error='标识符必须为字母、数字和下划线的组合')

            env = Environment.objects.filter(key=form.key).first()
            if env and env.id != form.id:
                return json_response(error=f'唯一标识符 {form.key} 已存在，请更改后重试')
            if form.id:
                Environment.objects.filter(pk=form.id).update(**form)
            else:
                env = Environment.objects.create(created_by=request.user, **form)
                env.sort_id = env.id
                env.save()
        return json_response(error=error)

    @auth('config.env.edit')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False)
        ).parse(request.body)
        if error is None:
            env = Environment.objects.filter(pk=form.id).first()
            if not env:
                return json_response(error='未找到指定环境')
            if form.sort:
                if form.sort == 'up':
                    tmp = Environment.objects.filter(sort_id__gt=env.sort_id).last()
                else:
                    tmp = Environment.objects.filter(sort_id__lt=env.sort_id).first()
                if tmp:
                    tmp.sort_id, env.sort_id = env.sort_id, tmp.sort_id
                    tmp.save()
            env.save()
        return json_response(error=error)

    @auth('config.env.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            if Deploy.objects.filter(env_id=form.id).exists():
                return json_response(error='该环境已关联了发布配置，请删除相关发布配置后再尝试删除')
            if Repository.objects.filter(env_id=form.id).exists():
                return json_response(error='该环境关联了构建记录，请在删除应用发布/构建仓库中相关记录后再尝试')
            # auto delete configs
            Config.objects.filter(env_id=form.id).delete()
            ConfigHistory.objects.filter(env_id=form.id).delete()
            Environment.objects.filter(pk=form.id).delete()
        return json_response(error=error)


class ServiceView(View):
    @auth('config.src.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False)
        ).parse(request.GET)
        if error is None:
            if form.id:
                service = Service.objects.get(pk=form.id)
                return json_response(service)
            services = Service.objects.all()
            return json_response(services)
        return json_response(error=error)

    @auth('config.src.add|config.src.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入服务名称'),
            Argument('key', help='请输入唯一标识符'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if not re.fullmatch(r'\w+', form.key, re.ASCII):
                return json_response(error='标识符必须为字母、数字和下划线的组合')

            service = Service.objects.filter(key=form.key).first()
            if service and service.id != form.id:
                return json_response(error='该标识符已存在，请更改后重试')
            app = App.objects.filter(key=form.key).first()
            if app:
                return json_response(error=f'该标识符已被应用 {app.name} 使用，请更改后重试')
            if form.id:
                Service.objects.filter(pk=form.id).update(**form)
            else:
                Service.objects.create(created_by=request.user, **form)
        return json_response(error=error)

    @auth('config.src.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            rel_apps = []
            for app in App.objects.filter(rel_services__isnull=False):
                rel_services = json.loads(app.rel_services)
                if form.id in rel_services:
                    rel_apps.append(app.name)
            if rel_apps:
                return json_response(
                    error=f'该服务在配置中心已被 "{", ".join(rel_apps)}" 依赖，请解除依赖关系后再尝试删除。')
            # auto delete configs
            Config.objects.filter(type='src', o_id=form.id).delete()
            ConfigHistory.objects.filter(type='src', o_id=form.id).delete()
            Service.objects.filter(pk=form.id).delete()
        return json_response(error=error)


class ConfigView(View):
    @auth('config.src.view_config|config.app.view_config')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='未指定操作对象'),
            Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数'),
            Argument('env_id', type=int, help='缺少必要参数'),
        ).parse(request.GET)
        if error is None:
            form.o_id, data = form.pop('id'), []
            for item in Config.objects.filter(**form).annotate(update_user=F('updated_by__nickname')):
                tmp = item.to_dict()
                tmp['update_user'] = item.update_user
                data.append(tmp)
            return json_response(data)
        return json_response(error=error)

    @auth('config.src.edit_config|config.app.edit_config')
    def post(self, request):
        form, error = JsonParser(
            Argument('o_id', type=int, help='缺少必要参数'),
            Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数'),
            Argument('envs', type=list, filter=lambda x: len(x), help='请选择环境'),
            Argument('key', help='请输入Key'),
            Argument('is_public', type=bool, help='缺少必要参数'),
            Argument('value', type=str, default=''),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            # 确保key以_SPUG_开头
            if not form.key.startswith('_SPUG_'):
                return json_response(error='Key必须以_SPUG_开头')
            
            form.value = form.value.strip()
            form.updated_at = human_datetime()
            form.updated_by = request.user
            envs = form.pop('envs')
            for env_id in envs:
                cf = Config.objects.filter(o_id=form.o_id, type=form.type, env_id=env_id, key=form.key).first()
                if cf:
                    raise Exception(f'{cf.env.name} 中已存在该Key')
                Config.objects.create(env_id=env_id, **form)
                ConfigHistory.objects.create(action='1', env_id=env_id, **form)
        return json_response(error=error)

    @auth('config.src.edit_config|config.app.edit_config')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='缺少必要参数'),
            Argument('value', type=str, default=''),
            Argument('is_public', type=bool, help='缺少必要参数'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            form.value = form.value.strip()
            config = Config.objects.filter(pk=form.id).first()
            if not config:
                return json_response(error='未找到指定对象')
            config.desc = form.desc
            config.is_public = form.is_public
            if config.value != form.value:
                old_value = config.value
                config.value = form.value
                config.updated_at = human_datetime()
                config.updated_by = request.user
                ConfigHistory.objects.create(
                    action='2',
                    old_value=old_value,
                    **config.to_dict(excludes=('id',)))
            config.save()
        return json_response(error=error)

    @auth('config.src.edit_config|config.app.edit_config')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='未指定操作对象')
        ).parse(request.GET)
        if error is None:
            config = Config.objects.filter(pk=form.id).first()
            if config:
                ConfigHistory.objects.create(
                    action='3',
                    old_value=config.value,
                    value='',
                    updated_at=human_datetime(),
                    updated_by=request.user,
                    **config.to_dict(excludes=('id', 'value', 'updated_at', 'updated_by_id'))
                )
                config.delete()
        return json_response(error=error)


class HistoryView(View):
    @auth('config.src.view_config|config.app.view_config')
    def post(self, request):
        form, error = JsonParser(
            Argument('o_id', type=int, help='缺少必要参数'),
            Argument('env_id', type=int, help='缺少必要参数'),
            Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数')
        ).parse(request.body)
        if error is None:
            data = []
            for item in ConfigHistory.objects.filter(**form).annotate(update_user=F('updated_by__nickname')):
                tmp = item.to_dict()
                tmp['action_alias'] = item.get_action_display()
                tmp['update_user'] = item.update_user
                data.append(tmp)
            return json_response(data)
        return json_response(error=error)


@auth('config.src.view_config|config.app.view_config')
def post_diff(request):
    form, error = JsonParser(
        Argument('o_id', type=int, help='缺少必要参数'),
        Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数'),
        Argument('envs', type=list, filter=lambda x: len(x), help='缺少必要参数'),
    ).parse(request.body)
    if error is None:
        data, form.env_id__in = {}, form.pop('envs')
        for item in Config.objects.filter(**form).order_by('key'):
            if item.key in data:
                data[item.key][item.env_id] = item.value
            else:
                data[item.key] = {'key': item.key, item.env_id: item.value}
        return json_response(list(data.values()))
    return json_response(error=error)


@auth('config.src.edit_config|config.app.edit_config')
def parse_json(request):
    form, error = JsonParser(
        Argument('o_id', type=int, help='缺少必要参数'),
        Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数'),
        Argument('env_id', type=int, help='缺少必要参数'),
        Argument('data', type=dict, help='缺少必要参数')
    ).parse(request.body)
    if error is None:
        data = form.pop('data')
        _parse(request, form, data)
    return json_response(error=error)


@auth('config.src.edit_config|config.app.edit_config')
def parse_text(request):
    form, error = JsonParser(
        Argument('o_id', type=int, help='缺少必要参数'),
        Argument('type', filter=lambda x: x in dict(Config.TYPES), help='缺少必要参数'),
        Argument('env_id', type=int, help='缺少必要参数'),
        Argument('data', handler=str.strip, help='缺少必要参数')
    ).parse(request.body)
    if error is None:
        data = {}
        for line in form.pop('data').split('\n'):
            line = line.strip()
            if not line or line[0] in ('#', ';'):
                continue
            fields = line.split('=', 1)
            if len(fields) != 2 or fields[0].strip() == '':
                return json_response(error=f'解析配置{line!r}失败，确认其遵循 key = value 格式')
            data[fields[0].strip()] = fields[1].strip()
        _parse(request, form, data)
    return json_response(error=error)


def _parse(request, query, data):
    for item in Config.objects.filter(**query):
        if item.key in data:
            value = _filter_value(data.pop(item.key))
            if item.value != value:
                old_value = item.value
                item.value = value
                item.updated_at = human_datetime()
                item.updated_by = request.user
                item.save()
                ConfigHistory.objects.create(
                    action='2',
                    old_value=old_value,
                    **item.to_dict(excludes=('id',)))
        else:
            ConfigHistory.objects.create(
                action='3',
                old_value=item.value,
                value='',
                updated_at=human_datetime(),
                updated_by=request.user,
                **item.to_dict(excludes=('id', 'value', 'updated_at', 'updated_by_id'))
            )
            item.delete()
    for key, value in data.items():
        query.key = key
        query.is_public = False
        query.value = _filter_value(value)
        query.updated_at = human_datetime()
        query.updated_by = request.user
        Config.objects.create(**query)
        ConfigHistory.objects.create(action='1', **query)


def _filter_value(value):
    if isinstance(value, (str, int)):
        value = str(value).strip()
    else:
        value = json.dumps(value)
    return value

class TagView(View):
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False)
        ).parse(request.GET)
        if error is None:
            tags = Tag.objects.all()
            if form.id:
                tag = tags.filter(pk=form.id).first()
                return json_response(tag)
            return json_response(tags)
        return json_response(error=error)

    @auth('config.tag.add|deploy.app.add|deploy.app.edit|config.app.add|config.app.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入标签名称'),
            Argument('key', help='请输入唯一标识符'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if not re.fullmatch(r'\w+', form.key, re.ASCII):
                return json_response(error='标识符必须为字母、数字和下划线的组合')

            tag = Tag.objects.filter(key=form.key).first()
            if tag and tag.id != form.id:
                return json_response(error='该识符已存在，请更改后重试')
            if form.id:
                Tag.objects.filter(pk=form.id).update(**form)
            else:
                tag = Tag.objects.create(created_by=request.user, **form)
                tag.sort_id = tag.id
                tag.save()
        return json_response(error=error)

    @auth('config.tag.edit|deploy.app.edit|config.app.edit_config')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('sort', filter=lambda x: x in ('up', 'down'), required=False)
        ).parse(request.body)
        if error is None:
            tag = Tag.objects.filter(pk=form.id).first()
            if not tag:
                return json_response(error='未找到指定应用')
            if tag.sort:
                if tag.sort == 'up':
                    tmp = Tag.objects.filter(sort_id__gt=tag.sort_id).last()
                else:
                    tmp = Tag.objects.filter(sort_id__lt=tag.sort_id).first()
                if tmp:
                    tmp.sort_id, tag.sort_id = tag.sort_id, tmp.sort_id
                    tmp.save()
            tag.save()
        return json_response(error=error)

    @auth('config.tag.del|deploy.app.del|config.app.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            # TODO 在应用中关联不能删除
            # if App.objects.filter(app_id=form.id).exists():
            #     return json_response(error='该应用在应用发布中已存在关联的发布配置，请删除相关发布配置后再尝试删除')
            # Config.objects.filter(type='app', o_id=form.id).delete()
            # ConfigHistory.objects.filter(type='app', o_id=form.id).delete()
            # for tag in Tag.objects.filter(rel_apps__isnull=False):
            #     rel_apps = json.loads(app.rel_apps)
            #     if form.id in rel_apps:
            #         rel_apps.remove(form.id)
            #         app.rel_apps = json.dumps(rel_apps)
            #         app.save()
            Tag.objects.filter(pk=form.id).delete()
        return json_response(error=error)
    
    
def clean_strip(parameters):
    if isinstance(parameters, list):
        return [{k.strip(): v.strip() if isinstance(v, str) else v for k, v in param.items()} for param in parameters]
    return parameters
    
class FileTemplateView(View):
    @auth('file.template.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('env_id', type=int, required=False),
            Argument('type', filter=lambda x: x in dict(FileTemplate.TYPES), help='请选择模版类型', required=False)
        ).parse(request.GET)
        if error is None:
            templates = FileTemplate.objects.annotate(env_name=F('env__name'), env_prod=F('env__prod')).all()
            if form.id:
                template = templates.filter(pk=form.id).first()
                if template:
                    return json_response(template.to_view())
                else:
                    return json_response()
            elif form.env_id is not None and form.type is not None:
                template = templates.filter(env_id=form.env_id, type=form.type).first()
                if template:
                    return json_response(template.to_view())
                else:
                    return json_response()
            else:
                templates = [t.to_view() for t in templates]
        return json_response(templates)

    @auth('file.template.add|file.template.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('type', filter=lambda x: x in dict(FileTemplate.TYPES), help='请选择模版类型'),
            Argument('env_id', help='请选择环境'),
            Argument('body', help='请输入模版内容'),
            Argument('parameters', type=list, handler=lambda x: json.dumps(clean_strip(x)), default=[]),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            if form.id:
                form.updated_at = human_datetime()
                form.updated_by = request.user
                name = FileTemplate.get_name_from_type(form.type)
                FileTemplate.objects.filter(pk=form.pop('id')).update(name=name,**form)
            else:
                form.created_by = request.user
                FileTemplate.objects.create(**form)
        return json_response(error=error)

    @auth('file.template.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            FileTemplate.objects.filter(pk=form.id).delete()
        return json_response(error=error)
    
class ContainerRepositoryView(View):
    @auth('container.repository.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False)
        ).parse(request.GET)
        if error is None:
            repositorys = ContainerRepository.objects.annotate(env_name=F('env__name'), env_prod=F('env__prod')).all()
            if form.id:
                repository = repositorys.filter(pk=form.id).first()
                return json_response(repository)
        return json_response(repositorys)

    @auth('container.repository.add|container.repository.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('env_id', help='请选择环境'),
            Argument('repository', help='请输入仓库地址'),
            Argument('repository_name_prefix', required=False, help='请输入镜像前缀'),
            Argument('desc', required=False)
        ).parse(request.body)
        if error is None:
            form.repository = form.repository.strip('/')
            if form.repository_name_prefix:
                # 去掉前后/
                form.repository_name_prefix = form.repository_name_prefix.strip('/')
            if form.id:
                form.updated_at = human_datetime()
                form.updated_by = request.user
                ContainerRepository.objects.filter(pk=form.pop('id')).update(**form)
            else:
                form.created_by = request.user
                ContainerRepository.objects.create(**form)
        return json_response(error=error)

    @auth('container.repository.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            ContainerRepository.objects.filter(pk=form.id).delete()
        return json_response(error=error)