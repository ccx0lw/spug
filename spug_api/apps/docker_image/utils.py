# Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
# Copyright: (c) <fcjava@163.com>
# Released under the AGPL-3.0 License.
from django_redis import get_redis_connection
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from libs.utils import AttrDict, human_time, render_str
from apps.docker_image.models import DockerImage
from apps.config.utils import compose_configs
from apps.deploy.helper import Helper
from apps.host.models import Host
from apps.config.models import ContainerRepository, FileTemplate
from apps.repository.models import Repository
from apps.repository.utils import dispatch as build_repository
import uuid
import os
import json

REPOS_DIR = settings.REPOS_DIR
BUILD_DIR = settings.BUILD_DIR

def dispatch(rep: DockerImage, helper=None, env=None):
    rep.status = '1'
    alone_build = helper is None
    if not helper:
        rds = get_redis_connection()
        rds_key = f'{settings.BUILD_IMAGE_KEY}:{rep.spug_version}'
        helper = Helper.make(rds, rds_key)
        rep.save()
    try:
        api_token = uuid.uuid4().hex
        helper.rds.setex(api_token, 60 * 60, f'{rep.app_id},{rep.env_id}')
        helper.send_info('image', f'\033[32m完成√\033[0m\r\n{human_time()} 编译准备...        ')
        
        # 通过容器镜像界面直接构建，不带环境
        if env is None:
            env = AttrDict(
                SPUG_APP_NAME=rep.app.name,
                SPUG_APP_KEY=rep.app.key,
                SPUG_APP_ID=str(rep.app_id),
                SPUG_DEPLOY_ID=str(rep.deploy_id),
                SPUG_BUILD_ID=str(rep.id),
                SPUG_ENV_ID=str(rep.env_id),
                SPUG_ENV_KEY=rep.env.key,
                SPUG_VERSION=rep.version,
                SPUG_BUILD_VERSION=rep.spug_version,
                SPUG_API_TOKEN=api_token,
                SPUG_REPOS_DIR=REPOS_DIR,
            )
            
            if not rep.repository_id:
                repi = Repository(
                    app_id=rep.deploy.app_id,
                    env_id=rep.deploy.env_id,
                    deploy_id=rep.deploy_id,
                    version=rep.version,
                    spug_version=rep.spug_version,
                    extra=rep.extra,
                    remarks='SPUG AUTO MAKE BY IMAGE BUILD',
                    created_by_id=rep.created_by_id
                )
                build_repository(repi, helper)
                rep.repository = repi
            else:
                helper.send_info('local', f'\r\n \033[32m使用构建仓库\033[0m \r\n id:[{rep.repository_id}] \r\n 环境:[{rep.repository.env.name}] \r\n version:[{rep.repository.version}] \r\n 创建时间:[{rep.repository.created_at}] \r\n 创建人:[{rep.repository.created_by.nickname}] \r\n \033[32m完成√\033[0m\r\n')
            extras = json.loads(rep.extra)
            if extras[0] == 'repository':
                extras = extras[1:]
            if extras[0] == 'branch':
                env.update(SPUG_GIT_BRANCH=extras[1], SPUG_GIT_COMMIT_ID=extras[2])
            else:
                env.update(SPUG_GIT_TAG=extras[1])
            
            # 查询
            extend = rep.deploy.extend_obj
            image_version = render_str(extend.image_version, env)
            # 编译镜像的环境变量
            env.update(SPUG_IMAGE_NAME=extend.image_name)
            env.update(SPUG_IMAGE_VERSION=image_version)
            # TODO 查询镜像的仓库
            env.update(SPUG_CONTAINER_REPOSITORY='')
            env.update(SPUG_CONTAINER_REPOSITORY_NAME_PREFIX='')
            # 添加Dockerfile变量
            if extend.dockerfile_params:
                dockerfile_params = json.loads(extend.dockerfile_params)
                if dockerfile_params:
                    for d in dockerfile_params:
                        for key, value in d.items():
                            env[key]=value
        
        # 查询镜像的仓库配置
        helper.send_info('image', f'\033[32m完成√\033[0m\r\n{human_time()} 查询{rep.env.name}[{rep.env_id}]镜像的仓库配置...        ')
        try:
            container = ContainerRepository.objects.get(pk=rep.env_id)
        except ContainerRepository.DoesNotExist:
            container = None  # 或者你可以处理不存在的情况
            helper.send_info('image', f'\033[32m完成√\033[0m\r\n{human_time()} \033[31m[{rep.env_id}]镜像的仓库配置不存在\033[0m{rep.env.name}        ')
        except MultipleObjectsReturned:
            # 处理存在多个对象的情况
            helper.send_error('image', f'\033[31m异常x\033[0m\r\n{human_time()} \033[31m镜像仓库配置，存在多条匹配的数据...\033[0m        ')
            raise Exception("镜像仓库配置，存在多条匹配的数据")
        
        extend = rep.deploy.extend_obj
        
        # append configs
        configs = compose_configs(rep.app, rep.env_id)
        configs_env = {f'{k.upper()}': v for k, v in configs.items()}
        env.update(configs_env)
        
        # 镜像地址
        image_url = None
        if container is not None:
            image_url = f'{container.repository}/{container.repository_name_prefix}/{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}'
        else:
            image_url = f'{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}'
        
        # 如果镜像配置的版本号是取的变量，则检测远程镜像是否存在，如果存在则报错
        if extend.image_version != env.SPUG_IMAGE_VERSION:
            helper.send_info('image', f'\r\n{human_time()} \033[31m镜像的版本是动态的{extend.image_version}  [{env.SPUG_IMAGE_VERSION}]\033[0m        ')
            if container is not None:
                helper.send_info('image', f'\r\n{human_time()} \033[31m检查镜像仓库是否存在{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}\033[0m        ')
                # TODO 本地镜像仓库已经存在，则直接抛错终止【不允许覆盖】
                images = DockerImage.objects.filter(app_id=rep.app_id, env_id=rep.env_id, version=rep.version, status='5')
                if images.exists():
                    helper.send_info('image', f'\r\n{human_time()} \033[31m远程仓库已经存在对应版本的镜像，编译镜像终止。不允许覆盖镜像 {env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}。 发布后台服务可以选择当前已经编译上传过的镜像\033[0m        ')
                    raise Exception("远程仓库已经存在对应版本的镜像，编译镜像终止。不允许覆盖镜像。 发布后台服务可以选择当前已经编译上传过的镜像")
                
        helper.send_info('image', f'\033[32m完成√\033[0m\r\n{human_time()} 开始编译镜像...        ')
    
        _build(rep, helper, env, image_url)
        # 保存镜像地址，后续使用yaml发布的时候使用这个地址
        rep.url = image_url
        rep.status = '5'
    except Exception as e:
        rep.status = '2'
        raise e
    finally:
        helper.local(f'cd {REPOS_DIR} && rm -rf {rep.spug_version}')
        if alone_build:
            helper.clear()
            rep.save()
            return rep
        elif rep.status == '5':
            rep.save()


def _build(rep: DockerImage, helper, env, image_url):
    extend = rep.deploy.extend_obj
    build_image_host_id = extend.build_image_host_id
    helper.send_step('image', 1, f'\033[32m就绪√\033[0m\r\n{human_time()} 数据准备...        ')
    host = Host.objects.filter(pk=build_image_host_id).first()
    if not host:
        helper.send_error(build_image_host_id, 'no such 编译镜像 host')
    env.update({'SPUG_HOST_ID': build_image_host_id, 'SPUG_HOST_NAME': host.hostname})
    extend.dst_dir = render_str(extend.dst_dir, env)
    extend.dst_repo = render_str(extend.dst_repo, env)
    env.update(SPUG_DST_DIR=extend.dst_dir)
    with host.get_ssh(default_env=env) as ssh:
        base_dst_dir = os.path.dirname(extend.dst_dir)
        code, _ = ssh.exec_command_raw(
            f'mkdir -p {extend.dst_repo}/{rep.spug_version} {base_dst_dir} && [ -e {extend.dst_dir} ] && [ ! -L {extend.dst_dir} ]')
        if code == 0:
            helper.send_error('image', f'检测到该主机的编译目录 {extend.dst_dir!r} 已存在，为了数据安全请自行备份后删除该目录，Spug 将会创建并接管该目录。')
        # clean
        clean_command = f'ls -d {extend.deploy_id}_* 2> /dev/null | sort -t _ -rnk2 | tail -n +{extend.versions + 1} | xargs rm -rf'
        helper.remote_raw('image', ssh, f'cd {extend.dst_repo} && {clean_command}')
        # transfer files
        tar_gz_file = f'{rep.spug_version}.tar.gz'   
        
        try:
            callback = helper.progress_callback('image')
            ssh.put_file(
                os.path.join(BUILD_DIR, tar_gz_file),
                os.path.join(extend.dst_repo, tar_gz_file),
                callback
            )
        except Exception as e:
            helper.send_error('image', f'Exception: {e}')
            
        command = f'cd {extend.dst_repo} && rm -rf {rep.spug_version} && tar xf {tar_gz_file} && rm -f {rep.deploy_id}_*.tar.gz'
        helper.remote_raw('image', ssh, command)
        helper.send_step('image', 1, '\033[32m完成√\033[0m\r\n')
            
        # 查询dockerfile模板文件，有则写入
        template = FileTemplate.objects.filter(env_id=rep.env_id, type='dockerfile').first()
        if template is not None:
            helper.send_step('image', 1, f'{human_time()} 写入 {template.name} 文件       ')
            helper.remote_raw('image', ssh, f'cd {extend.dst_repo} && {clean_command}')
            helper.send_step('image', 1, f'{os.path.join(BUILD_DIR, template.name)}')
            try:
                with open(os.path.join(BUILD_DIR, template.name), 'w', encoding='utf-8') as file:
                    file.write(template.body)
                
                callback = helper.progress_callback('image')
                ssh.put_file(
                    os.path.join(BUILD_DIR, template.name),
                    os.path.join(extend.dst_repo, rep.spug_version, template.name),
                    callback
                )
            except Exception as e:
                helper.send_error('image', f'Exception: {e}')
        else:
            helper.send_step('image', 1, f'{human_time()} {template.name} 模板不存在      ')     

        helper.send_step('image', 1, '\033[32m完成√\033[0m\r\n')
        
        # build image
        repo_dir = os.path.join(extend.dst_repo, rep.spug_version)
        if extend.hook_pre_image:
            helper.send_step('image', 2, f'{human_time()} 编译镜像...       {repo_dir}\r\n')
            command = f'cd {repo_dir} && {extend.hook_pre_image}'
            helper.remote('image', ssh, command)

        # do rm
        helper.send_step('image', 3, f'{human_time()} 清理数据...        ')
        helper.remote_raw('image', ssh, f'rm -f {extend.dst_dir} && ln -sfn {repo_dir} {extend.dst_dir}')
        helper.send_step('image', 3, '\033[32m完成√\033[0m\r\n')

        # post host, upload image
        if extend.hook_post_image:
            helper.send_step('image', 4, f'{human_time()} 镜像上传...       \r\n')
            command = f'cd {extend.dst_dir} && {extend.hook_post_image}'
            helper.remote('image', ssh, command)

        helper.send_step('image', 100, f'\r\n{human_time()} ** \033[32m镜像编译上传成功\033[0m **')

