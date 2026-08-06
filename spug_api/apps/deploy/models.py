# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from libs import ModelMixin, human_datetime
from apps.account.models import User
from apps.app.models import Deploy
from apps.repository.models import Repository
from apps.docker_image.models import DockerImage
from apps.config.models import Environment
from apps.deploy.uploads import resolve_upload_path
import json
from datetime import datetime

class DeployRequest(models.Model, ModelMixin):
    STATUS = (
        ('-3', '发布异常'),
        ('-2', '结果未知'),
        ('-1', '已驳回'),
        ('0', '待审核'),
        ('1', '待发布'),
        ('2', '发布中'),
        ('3', '发布成功'),
    )
    TYPES = (
        ('0', '重启'),
        ('1', '正常发布'),
        ('2', '回滚'),
        ('3', '自动发布'),
    )
    deploy = models.ForeignKey(Deploy, on_delete=models.CASCADE)
    repository = models.ForeignKey(Repository, null=True, on_delete=models.SET_NULL)
    docker_image = models.ForeignKey(DockerImage, null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=2, choices=TYPES, default='1')
    extra = models.TextField()
    host_ids = models.TextField()
    desc = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=2, choices=STATUS)
    reason = models.CharField(max_length=255, null=True)
    version = models.CharField(max_length=100, null=True)
    spug_version = models.CharField(max_length=50, null=True)
    plan = models.DateTimeField(null=True)
    fail_host_ids = models.TextField(default='[]')

    created_at = models.CharField(max_length=20, default=human_datetime)
    created_at_date = models.DateField(null=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    approve_at = models.CharField(max_length=20, null=True)
    approve_at_date = models.DateField(null=True)
    approve_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    do_at = models.CharField(max_length=20, null=True)
    failed_at = models.CharField(max_length=20, null=True)
    do_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    @property
    def is_quick_deploy(self):
        if self.type in ('1', '3') and self.deploy.extend == '1' and self.extra:
            extra = json.loads(self.extra)
            return extra[0] in ('branch', 'tag')
        return False
    
    def save(self, *args, **kwargs):
        if self.created_at:
            self.created_at_date = datetime.strptime(self.created_at, '%Y-%m-%d %H:%M:%S').date()
        if self.approve_at:
            self.approve_at_date = datetime.strptime(self.approve_at, '%Y-%m-%d %H:%M:%S').date()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        deploy_id = self.deploy_id
        deploy_extend = self.deploy.extend
        spug_version = self.spug_version
        super().delete(using, keep_parents)
        if self.repository_id:
            if not DeployRequest.objects.filter(repository=self.repository).exists():
                self.repository.delete()
        if deploy_extend == '2':
            try:
                resolve_upload_path(deploy_id, spug_version).unlink()
            except (FileNotFoundError, ValueError):
                pass

    def __repr__(self):
        return f'<DeployRequest name={self.name}>'

    class Meta:
        db_table = 'deploy_requests'
        ordering = ('-id',)


class DeployUpload(models.Model):
    token = models.CharField(max_length=64, unique=True)
    deploy = models.ForeignKey(Deploy, on_delete=models.CASCADE)
    storage_name = models.CharField(max_length=64)
    original_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        models.PROTECT,
        related_name='+',
    )
    consumed_request_id = models.PositiveIntegerField(null=True)
    consumed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'deploy_uploads'
        ordering = ('-id',)


class DeployIteration(models.Model, ModelMixin):
    STATUS = (
        ('0', '待发布'),
        ('1', '发布中'),
        ('2', '发布成功'),
        ('-1', '部分失败'),
        ('-2', '结果未知'),
        ('-3', '发布失败'),
    )
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=2, choices=STATUS, default='0')
    desc = models.TextField(blank=True, null=True)
    plan_time = models.DateTimeField(null=True, blank=True)
    upload_time = models.DateTimeField(null=True, blank=True, help_text='镜像上传时间')
    env = models.ForeignKey(Environment, on_delete=models.CASCADE)
    
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_at_date = models.DateField(null=True)
    updated_at = models.CharField(max_length=20, null=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def save(self, *args, **kwargs):
        if self.created_at:
            self.created_at_date = datetime.strptime(self.created_at, '%Y-%m-%d %H:%M:%S').date()
        self.updated_at = human_datetime()
        super().save(*args, **kwargs)

    def __repr__(self):
        return f'<DeployIteration name={self.name}>'

    class Meta:
        db_table = 'deploy_iterations'
        ordering = ('-id',)


class DeployIterationDetail(models.Model, ModelMixin):
    STATUS_CHOICES = (
        ('0', '待发布'),
        ('1', '发布中'),
        ('2', '发布成功'),
        ('3', '发布失败'),
        ('4', '结果未知'),
    )
    IMAGE_STATUS_CHOICES = (
        ('0', '未上传'),
        ('1', '上传中'),
        ('2', '上传成功'),
        ('3', '上传失败'),
    )
    
    iteration = models.ForeignKey(DeployIteration, on_delete=models.CASCADE, related_name='details')
    deploy = models.ForeignKey(Deploy, on_delete=models.CASCADE)
    version = models.CharField(max_length=100)
    sequence = models.IntegerField(default=0, help_text='发布顺序')
    status = models.CharField(max_length=2, choices=STATUS_CHOICES, default='0', help_text='发布状态')
    request_id = models.IntegerField(null=True, blank=True, help_text='关联的发布申请ID')
    # 镜像上传相关字段
    image_status = models.CharField(max_length=2, choices=IMAGE_STATUS_CHOICES, default='0', help_text='镜像上传状态')
    docker_image_id = models.IntegerField(null=True, blank=True, help_text='关联的镜像ID')
    
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')

    def __repr__(self):
        return f'<DeployIterationDetail iteration={self.iteration_id} deploy={self.deploy_id}>'

    class Meta:
        db_table = 'deploy_iteration_details'
        ordering = ('sequence',)
        unique_together = ('iteration', 'deploy')


class DeployOperationLog(models.Model):
    TARGET_TYPES = (
        ('request', '发布申请'),
        ('iteration', '迭代'),
        ('deploy', '发布配置'),
    )

    target_type = models.CharField(max_length=20, choices=TARGET_TYPES)
    target_id = models.IntegerField()
    target_name = models.CharField(max_length=100)
    action = models.CharField(max_length=255)
    operator = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    operator_name = models.CharField(max_length=100)
    created_at = models.CharField(max_length=20, default=human_datetime)

    class Meta:
        db_table = 'deploy_operation_logs'
        ordering = ('-id',)
        indexes = [
            models.Index(
                fields=('target_type', 'target_id'),
                name='deploy_op_target_idx',
            ),
        ]
