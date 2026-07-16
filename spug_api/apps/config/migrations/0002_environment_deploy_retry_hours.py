from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('config', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='environment',
            name='deploy_retry_hours',
            field=models.PositiveIntegerField(default=24),
        ),
    ]
