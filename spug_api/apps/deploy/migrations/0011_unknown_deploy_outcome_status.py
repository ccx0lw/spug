from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deploy', '0010_deployupload'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deployrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('-3', '发布异常'),
                    ('-2', '结果未知'),
                    ('-1', '已驳回'),
                    ('0', '待审核'),
                    ('1', '待发布'),
                    ('2', '发布中'),
                    ('3', '发布成功'),
                ],
                max_length=2,
            ),
        ),
        migrations.AlterField(
            model_name='deployiteration',
            name='status',
            field=models.CharField(
                choices=[
                    ('0', '待发布'),
                    ('1', '发布中'),
                    ('2', '发布成功'),
                    ('-1', '部分失败'),
                    ('-2', '结果未知'),
                    ('-3', '发布失败'),
                ],
                default='0',
                max_length=2,
            ),
        ),
        migrations.AlterField(
            model_name='deployiterationdetail',
            name='status',
            field=models.CharField(
                choices=[
                    ('0', '待发布'),
                    ('1', '发布中'),
                    ('2', '发布成功'),
                    ('3', '发布失败'),
                    ('4', '结果未知'),
                ],
                default='0',
                help_text='发布状态',
                max_length=2,
            ),
        ),
    ]
