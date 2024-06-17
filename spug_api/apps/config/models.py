# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.db.models import UniqueConstraint
from libs import ModelMixin, human_datetime
from apps.account.models import User
import json


class Environment(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    key = models.CharField(max_length=50)
    prod = models.BooleanField(default=False)
    desc = models.CharField(max_length=255, null=True)
    sort_id = models.IntegerField(default=0, db_index=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def __repr__(self):
        return f'<Environment {self.name!r}>'

    class Meta:
        db_table = 'environments'
        ordering = ('-sort_id',)


class Service(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    key = models.CharField(max_length=50, unique=True)
    desc = models.CharField(max_length=255, null=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def __repr__(self):
        return f'<Service {self.name!r}>'

    class Meta:
        db_table = 'services'
        ordering = ('-id',)


class Config(models.Model, ModelMixin):
    TYPES = (
        ('app', 'App'),
        ('src', 'Service')
    )
    type = models.CharField(max_length=5, choices=TYPES)
    o_id = models.IntegerField()
    key = models.CharField(max_length=50)
    env = models.ForeignKey(Environment, on_delete=models.PROTECT)
    value = models.TextField(null=True)
    desc = models.CharField(max_length=255, null=True)
    is_public = models.BooleanField(default=False)
    updated_at = models.CharField(max_length=20)
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def __repr__(self):
        return f'<Config {self.key!r}>'

    class Meta:
        db_table = 'configs'
        ordering = ('-key',)


class ConfigHistory(models.Model, ModelMixin):
    ACTIONS = (
        ('1', '新增'),
        ('2', '更新'),
        ('3', '删除')
    )
    type = models.CharField(max_length=5)
    o_id = models.IntegerField()
    key = models.CharField(max_length=50)
    env_id = models.IntegerField()
    value = models.TextField(null=True)
    desc = models.CharField(max_length=255, null=True)
    is_public = models.BooleanField()
    old_value = models.TextField(null=True)
    action = models.CharField(max_length=2, choices=ACTIONS)
    updated_at = models.CharField(max_length=20)
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def __repr__(self):
        return f'<ConfigHistory {self.key!r}>'

    class Meta:
        db_table = 'config_histories'
        ordering = ('key',)

class Tag(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    key = models.CharField(max_length=50, unique=True)
    desc = models.CharField(max_length=255, null=True)
    sort_id = models.IntegerField(default=0, db_index=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        return tmp

    def __repr__(self):
        return f'<App {self.name!r}>'

    class Meta:
        db_table = 'tags'
        ordering = ('-sort_id',)
        
class FileTemplate(models.Model, ModelMixin):
    TYPES = (
        ('dockerfile', 'Dockerfile'),
        ('yaml', 'k8s.yaml')
    )
    name = models.CharField(max_length=50)
    env_id = models.IntegerField()
    type = models.CharField(max_length=5, choices=TYPES)
    body = models.TextField()
    parameters = models.TextField(default='[]')
    desc = models.CharField(max_length=255, null=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)
    
    def __repr__(self):
        return f'<FileTemplate {self.name!r}>'
    
    def to_view(self):
        tmp = self.to_dict()
        tmp['parameters'] = json.loads(self.parameters)
        return tmp
    
    @classmethod
    def get_name_from_type(cls, type_key):
        """根据类型获取名称的方法"""
        type_to_name = dict(cls.TYPES)
        return type_to_name.get(type_key, 'Default Name')
    
    def save(self, *args, **kwargs):
        type_to_name = dict(self.TYPES)
        self.name = self.get_name_from_type(self.type)
        super(FileTemplate, self).save(*args, **kwargs)

    class Meta:
        db_table = 'file_template'
        ordering = ('-id',)
        constraints = [
            UniqueConstraint(fields=['env_id', 'type'], name='unique_env_id_type')
        ]
        
# 容器仓库地址,每个环境一个
class ContainerRepository(models.Model, ModelMixin):
    env_id = models.IntegerField(unique=True)
    repository = models.CharField(max_length=255)
    repository_name_prefix = models.CharField(max_length=255, null=True)
    desc = models.CharField(max_length=255, null=True)
    created_at = models.CharField(max_length=20, default=human_datetime)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    updated_at = models.CharField(max_length=20, null=True)
    updated_by = models.ForeignKey(User, models.PROTECT, related_name='+', null=True)

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        return tmp

    def __repr__(self):
        return f'<App {self.name!r}>'

    class Meta:
        db_table = 'container_repository'
        ordering = ('-id',)