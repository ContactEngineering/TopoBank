# Generated by Django 2.2.20 on 2021-05-22 15:52

from django.db import migrations, models
import topobank.manager.models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0020_topography_thumbnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='topography',
            name='squeezed_datafile',
            field=models.FileField(max_length=260, null=True, upload_to=topobank.manager.models.user_directory_path),
        ),
    ]