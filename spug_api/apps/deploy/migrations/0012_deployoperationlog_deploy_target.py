from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deploy', '0011_unknown_deploy_outcome_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deployoperationlog',
            name='target_type',
            field=models.CharField(
                choices=[
                    ('request', '发布申请'),
                    ('iteration', '迭代'),
                    ('deploy', '发布配置'),
                ],
                max_length=20,
            ),
        ),
    ]
