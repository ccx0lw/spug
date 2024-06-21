# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.db.models import F
from django.conf import settings
from django_redis import get_redis_connection
from libs import json_response, JsonParser, Argument, human_time, AttrDict, auth
from apps.repository.models import Repository
from apps.deploy.models import DeployRequest
from apps.repository.utils import dispatch
from apps.app.models import Deploy
from threading import Thread
import json


class RepositoryView(View):
    @auth('deploy.repository.view|deploy.request.add|deploy.request.edit')
    def get(self, request):
        apps = request.user.deploy_perms['apps']
        deploy_id = request.GET.get('deploy_id')
        data = Repository.objects.filter(app_id__in=apps).annotate(
            app_name=F('app__name'),
            app_rel_tags=F('app__rel_tags'),
            env_name=F('env__name'),
            env_prod=F('env__prod'),
            created_by_user=F('created_by__nickname'))
        if deploy_id:
            data = data.filter(deploy_id=deploy_id, status='5')
            return json_response([x.to_view() for x in data])

        response = dict()
        for item in data:
            if item.app_id in response:
                response[item.app_id]['child'].append(item.to_view())
            else:
                tmp = item.to_view()
                tmp['child'] = [item.to_view()]
                response[item.app_id] = tmp
        return json_response(list(response.values()))

    @auth('deploy.repository.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('deploy_id', type=int, help='参数错误'),
            Argument('extra', type=list, help='参数错误'),
            Argument('remarks', required=False)
        ).parse(request.body)
        if error is None:
            if form.remarks is not None:
                form.remarks = form.remarks.strip()
                if form.remarks == 'SPUG AUTO MAKE BY IMAGE BUILD' or form.remarks == 'SPUG AUTO MAKE':
                    form.remarks = ''
            
            deploy = Deploy.objects.filter(pk=form.deploy_id).first()
            if not deploy:
                return json_response(error='未找到指定发布配置')
            if form.extra[0] == 'tag':
                if not form.extra[1]:
                    return json_response(error='请选择要发布的版本')
                form.version = form.extra[1]
            elif form.extra[0] == 'branch':
                if not form.extra[2]:
                    return json_response(error='请选择要发布的分支及Commit ID')
                form.version = f'{form.extra[1]}#{form.extra[2][:6]}'
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
            form.spug_version = Repository.make_spug_version(deploy.id)

            # form.version = form.spug_version
            rep = Repository.objects.create(
                app_id=deploy.app_id,
                env_id=deploy.env_id,
                created_by=request.user,
                **form)
            Thread(target=dispatch, args=(rep,)).start()
            return json_response(rep.to_view())
        return json_response(error=error)

    @auth('deploy.repository.add|deploy.repository.build')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('action', help='参数错误')
        ).parse(request.body)
        if error is None:
            rep = Repository.objects.filter(pk=form.id).first()
            if not rep:
                return json_response(error='未找到指定构建记录')
            if form.action == 'rebuild':
                Thread(target=dispatch, args=(rep,)).start()
                return json_response(rep.to_view())
        return json_response(error=error)

    @auth('deploy.repository.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            repository = Repository.objects.filter(pk=form.id).first()
            if not repository:
                return json_response(error='未找到指定构建记录')
            if repository.deployrequest_set.exists():
                return json_response(error='已关联发布申请无法删除')
            repository.delete()
        return json_response(error=error)


@auth('deploy.repository.view')
def get_requests(request):
    form, error = JsonParser(
        Argument('repository_id', type=int, help='参数错误')
    ).parse(request.GET)
    if error is None:
        requests = []
        for item in DeployRequest.objects.filter(repository_id=form.repository_id):
            data = item.to_dict(selects=('id', 'name', 'created_at'))
            data['host_ids'] = json.loads(item.host_ids)
            data['status_alias'] = item.get_status_display()
            requests.append(data)
        return json_response(requests)


@auth('deploy.repository.view')
def get_detail(request, r_id):
    repository = Repository.objects.filter(pk=r_id).first()
    if not repository:
        return json_response(error='未找到指定构建记录')
    rds, counter = get_redis_connection(), 0
    if repository.remarks == 'SPUG AUTO MAKE':
        req = repository.deployrequest_set.filter(repository_id=repository.id, spug_version=repository.spug_version).last()
        key = f'{settings.REQUEST_KEY}:{req.id}'
    elif repository.remarks == 'SPUG AUTO MAKE BY IMAGE BUILD':
        key = f'{settings.BUILD_IMAGE_KEY}:{repository.spug_version}'
    else:
        key = f'{settings.BUILD_KEY}:{repository.spug_version}'
    data = rds.lrange(key, counter, counter + 9)
    response = AttrDict(data='', step=0, s_status='process', status=repository.status)
    while data:
        for item in data:
            counter += 1
            item = json.loads(item.decode())
            if item['key'] == 'local':
                if 'data' in item:
                    response.data += item['data']
                if 'step' in item:
                    response.step = item['step']
                if 'status' in item:
                    response.status = item['status']
        data = rds.lrange(key, counter, counter + 9)
    response.index = counter
    if repository.status in ('0', '1'):
        response.data = f'{human_time()} 建立连接...        ' + response.data
    elif not response.data:
        response.data = f'{human_time()} 读取数据...        \r\n\r\n未读取到数据，Spug 仅保存最近2周的构建日志。'
    else:
        response.data = f'{human_time()} 读取数据...        ' + response.data
    return json_response(response)
