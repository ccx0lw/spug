# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import connections, transaction
from django.conf import settings
from apps.account.models import History, User
from apps.alarm.models import Alarm
from apps.schedule.models import Task, History as TaskHistory
from apps.deploy.models import DeployRequest
from apps.app.models import DeployExtend1, DeployExtend3
from apps.exec.models import ExecHistory, Transfer
from apps.notify.models import Notify
from apps.deploy.utils import dispatch, lock_deploy_and_get_running_request
from apps.repository.models import Repository
from libs.utils import parse_time, human_datetime, human_date
from datetime import datetime, timedelta
from threading import Thread
from collections import defaultdict
from pathlib import Path
import time
import os


def auto_run_by_day():
    try:
        date_7 = human_date(datetime.now() - timedelta(days=7))
        date_30 = human_date(datetime.now() - timedelta(days=30))
        History.objects.filter(created_at__lt=date_30).delete()
        Notify.objects.filter(created_at__lt=date_7, unread=False).delete()
        Alarm.objects.filter(created_at__lt=date_30).delete()
        for item in DeployExtend1.objects.all():
            index = 0
            for req in DeployRequest.objects.filter(deploy_id=item.deploy_id, repository_id__isnull=False):
                if index > item.versions and req.repository_id:
                    req.repository.delete()
                index += 1
                
        for item in DeployExtend3.objects.all():
            index = 0
            for req in DeployRequest.objects.filter(deploy_id=item.deploy_id, repository_id__isnull=False):
                if index > item.versions and req.repository_id:
                    req.repository.delete()
                index += 1
                
        for item in DeployExtend3.objects.all():
            index = 0
            for req in DeployRequest.objects.filter(deploy_id=item.deploy_id, docker_image_id__isnull=False):
                if index > item.versions and req.docker_image_id:
                    req.docker_image.delete()
                index += 1
                
        timer = defaultdict(int)
        for item in ExecHistory.objects.all():
            if timer[item.user_id] >= 10:
                item.delete()
            else:
                timer[item.user_id] += 1

        timer = defaultdict(int)
        for item in Transfer.objects.all():
            if timer[item.user_id] >= 10:
                item.delete()
            else:
                timer[item.user_id] += 1

        for task in Task.objects.all():
            try:
                record = TaskHistory.objects.filter(task_id=task.id)[50]
                TaskHistory.objects.filter(task_id=task.id, id__lt=record.id).delete()
            except IndexError:
                pass

        timestamp = time.time() - 2 * 3600
        for item in Path(settings.TRANSFER_DIR).iterdir():
            if item.name != '.gitkeep':
                if item.stat().st_atime < timestamp:
                    transfer_dir = item.absolute()
                    os.system(f'umount -f {transfer_dir} &> /dev/null ; rm -rf {transfer_dir}')
    finally:
        connections.close_all()


def auto_run_by_minute():
    try:
        now = datetime.now()
        for req in DeployRequest.objects.filter(status='2'):
            if (now - parse_time(req.do_at)).seconds > 3600:
                req.status = '-3'
                req.failed_at = human_datetime()
                req.save()

        for rep in Repository.objects.filter(status='1'):
            if (now - parse_time(rep.created_at)).seconds > 3600:
                rep.status = '2'
                rep.save()

        planned_request_ids = list(DeployRequest.objects.filter(
            status='1',
            plan__lte=now,
        ).values_list('id', flat=True))
        for request_id in planned_request_ids:
            with transaction.atomic():
                request_snapshot = DeployRequest.objects.filter(
                    pk=request_id,
                    status='1',
                    plan__lte=now,
                ).only('id', 'deploy_id').first()
                if not request_snapshot:
                    continue
                deploy, running_request = lock_deploy_and_get_running_request(
                    request_snapshot.deploy_id
                )
                if not deploy or running_request:
                    continue
                req = DeployRequest.objects.select_for_update().filter(
                    pk=request_snapshot.id,
                    status='1',
                    plan__lte=now,
                ).first()
                if not req:
                    continue
                req.status = '2'
                req.do_at = human_datetime()
                req.do_by = req.created_by
                req.save()
                transaction.on_commit(
                    lambda request_obj=req: Thread(
                        target=dispatch,
                        args=(request_obj,),
                    ).start()
                )
    finally:
        connections.close_all()
