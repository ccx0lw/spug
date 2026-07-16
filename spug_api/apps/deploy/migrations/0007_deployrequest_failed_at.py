from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('config', '0002_environment_deploy_retry_hours'),
        ('deploy', '0006_auto_20260203_0710'),
    ]

    operations = [
        migrations.AddField(
            model_name='deployrequest',
            name='failed_at',
            field=models.CharField(max_length=20, null=True),
        ),
    ]
