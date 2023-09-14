# Generated by Django 3.2.12 on 2022-04-13 15:25

from django.db import migrations, models
import topobank.manager.models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0028_auto_20211209_1239'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topography',
            name='datafile',
            field=models.FileField(max_length=250, upload_to=topobank.manager.models.Topography.datafile_path),
        ),
        migrations.AlterField(
            model_name='topography',
            name='squeezed_datafile',
            field=models.FileField(max_length=260, null=True, upload_to=topobank.manager.models.Topography.squeezed_datafile_path),
        ),
        migrations.AlterField(
            model_name='topography',
            name='thumbnail',
            field=models.ImageField(null=True, upload_to=topobank.manager.models.Topography.thumbnail_path),
        ),
    ]
