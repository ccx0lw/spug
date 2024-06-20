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
from apps.config.models import ContainerRepository
import json
import uuid
import os

REPOS_DIR = settings.REPOS_DIR
BUILD_DIR = settings.BUILD_DIR


def dispatch(rep: DockerImage, helper=None, env=AttrDict):
    rep.status = '1'
    alone_build = helper is None
    if not helper:
        rds = get_redis_connection()
        rds_key = f'{settings.BUILD_KEY}:{rep.spug_version}'
        helper = Helper.make(rds, rds_key)
        rep.save()
    try:
        api_token = uuid.uuid4().hex
        helper.rds.setex(api_token, 60 * 60, f'{rep.app_id},{rep.env_id}')
        helper.send_info('image', f'\033[32m完成√\033[0m\r\n{human_time()} 编译准备...        ')
        
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
        
        # 如果镜像配置的版本号是取的变量，则检测远程镜像是否存在，如果存在则报错
        if extend.image_version != env.SPUG_IMAGE_VERSION:
            helper.send_info('image', f'\r\n{human_time()} \033[31m镜像的版本是动态的{extend.image_version}  [{env.SPUG_IMAGE_VERSION}]\033[0m        ')
            if container is not None:
                helper.send_info('image', f'\r\n{human_time()} \033[31m检查远程仓库是否存在{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}\033[0m        ')
                # TODO 远程仓库已经存在，则直接抛错终止【不允许覆盖】
                helper.send_info('image', f'\r\n{human_time()} \033[31m远程仓库已经存在对应版本的镜像，编译镜像终止。不允许覆盖镜像 {env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}\033[0m        ')
    

        _build(rep, helper, env)
        if container is not None:
            rep.url = f'{container.repository}/{container.repository_name_prefix}/{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}'
        else:
            rep.url = f'{env.SPUG_IMAGE_NAME}:{env.SPUG_IMAGE_VERSION}'
        rep.status = '5'
    except Exception as e:
        rep.status = '2'
        raise e
    finally:
        # helper.local(f'cd {REPOS_DIR} && rm -rf {rep.spug_version}')
        # close_old_connections()
        if alone_build:
            helper.clear()
            rep.save()
            return rep
        elif rep.status == '5':
            rep.save()


def _build(rep: DockerImage, helper, env):
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
            f'mkdir -p {extend.dst_repo} {base_dst_dir} && [ -e {extend.dst_dir} ] && [ ! -L {extend.dst_dir} ]')
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

        # build image
        repo_dir = os.path.join(extend.dst_repo, rep.spug_version)
        if extend.hook_pre_image:
            helper.send_step('image', 2, f'{human_time()} 编译镜像...       \r\n')
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

