# Generated by Django 3.2.18 on 2023-09-15 20:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0034_auto_20230912_2052'),
    ]

    operations = [
        migrations.AddField(
            model_name='topography',
            name='channel_names',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='topography',
            name='creation_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='topography',
            name='end_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='topography',
            name='start_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='topography',
            name='task_id',
            field=models.CharField(max_length=155, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='topography',
            name='task_state',
            field=models.CharField(choices=[('pe', 'pending'), ('st', 'started'), ('re', 'retry'), ('fa', 'failure'), ('su', 'success')], max_length=7, null=True),
        ),
    ]
