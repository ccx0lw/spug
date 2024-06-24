# Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
# Copyright: (c) <fcjava@163.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.conf import settings
from libs.mixins import ModelMixin
from apps.app.models import App, Environment, Deploy
from apps.repository.models import Repository
from apps.account.models import User
from datetime import datetime
import json
import os


class DockerImage(models.Model, ModelMixin):
    STATUS = (
        ('0', '未开始'),
        ('1', '构建中'),
        ('2', '失败'),
        ('5', '成功'),
    )
    app = models.ForeignKey(App, on_delete=models.PROTECT)
    env = models.ForeignKey(Environment, on_delete=models.PROTECT)
    deploy = models.ForeignKey(Deploy, on_delete=models.PROTECT)
    repository = models.ForeignKey(Repository, on_delete=models.SET_NULL, null=True)
    version = models.CharField(max_length=100)
    spug_version = models.CharField(max_length=50)
    url = models.TextField()
    remarks = models.CharField(max_length=255, null=True)
    extra = models.TextField()
    status = models.CharField(max_length=2, choices=STATUS, default='0')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    @staticmethod
    def make_spug_version(deploy_id):
        return f'{deploy_id}_{datetime.now().strftime("%Y%m%d%H%M%S")}'

    def to_view(self):
        tmp = self.to_dict()
        tmp['extra'] = json.loads(self.extra)
        tmp['status_alias'] = self.get_status_display()
        if hasattr(self, 'app_name'):
            tmp['app_name'] = self.app_name
        if hasattr(self, 'app_rel_tags'):
            tmp['app_rel_tags'] = json.loads(self.app_rel_tags) if self.app_rel_tags else []
        if hasattr(self, 'env_name'):
            tmp['env_name'] = self.env_name
        if hasattr(self, 'env_prod'):
            tmp['env_prod'] = self.env_prod
        if hasattr(self, 'created_by_user'):
            tmp['created_by_user'] = self.created_by_user
        return tmp

    def delete(self, using=None, keep_parents=False):
        super().delete(using, keep_parents)
        try:
            build_file = f'{self.spug_version}.tar.gz'
            os.remove(os.path.join(settings.BUILD_DIR, build_file))
        except FileNotFoundError:
            pass

    class Meta:
        db_table = 'docker_images'
        ordering = ('-id',)
        # 去掉唯一
        # unique_together = (('app', 'env', 'version'),)
