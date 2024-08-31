# Generated by Django 3.2.18 on 2023-10-15 15:51

from django.db import migrations, models


def storage_prefix(instance):
    return f"topographies/{instance.id}"


def topography_datafile_path(instance, filename):
    return f"{storage_prefix(instance)}/raw/{filename}"


class Migration(migrations.Migration):

    dependencies = [
        ("manager", "0037_alter_surface_category"),
    ]

    operations = [
        migrations.AlterField(
            model_name="topography",
            name="datafile",
            field=models.FileField(
                blank=True, max_length=250, upload_to=topography_datafile_path
            ),
        ),
    ]
