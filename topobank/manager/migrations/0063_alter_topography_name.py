# Generated by Django 4.2.16 on 2024-09-19 13:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0062_topography_task_traceback_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topography',
            name='name',
            field=models.TextField(),
        ),
    ]