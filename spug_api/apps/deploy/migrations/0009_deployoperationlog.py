from django.db import migrations, models
import django.db.models.deletion
import libs.utils


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0001_initial'),
        ('deploy', '0008_auto_20260721_1728'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeployOperationLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_type', models.CharField(choices=[('request', '发布申请'), ('iteration', '迭代')], max_length=20)),
                ('target_id', models.IntegerField()),
                ('target_name', models.CharField(max_length=100)),
                ('action', models.CharField(max_length=255)),
                ('operator_name', models.CharField(max_length=100)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('operator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.User')),
            ],
            options={
                'db_table': 'deploy_operation_logs',
                'ordering': ('-id',),
            },
        ),
        migrations.AddIndex(
            model_name='deployoperationlog',
            index=models.Index(fields=['target_type', 'target_id'], name='deploy_op_target_idx'),
        ),
    ]
