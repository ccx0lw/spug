from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0002_user_totp_mfa'),
        ('app', '0001_initial'),
        ('deploy', '0009_deployoperationlog'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeployUpload',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('token', models.CharField(max_length=64, unique=True)),
                ('storage_name', models.CharField(max_length=64)),
                ('original_name', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('consumed_request_id', models.PositiveIntegerField(null=True)),
                ('consumed_at', models.DateTimeField(null=True)),
                (
                    'created_by',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='+',
                        to='account.user',
                    ),
                ),
                (
                    'deploy',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='app.deploy',
                    ),
                ),
            ],
            options={
                'db_table': 'deploy_uploads',
                'ordering': ('-id',),
            },
        ),
    ]
