# Generated by Django 4.2.7 on 2024-01-22 16:45

from django.db import migrations, models
from django.db.migrations.recorder import MigrationRecorder


def forward_func(apps, schema_editor):
    # This forward func fixes an issue with the creation_datetime and modification_datetime fields of surfaces and
    # topographies, there are set to the date of the migration 0034_auto_20231107_1729 and 0035_auto_20231108_1315.
    # We here set them to the date of the publication of the surface, if it exists, or to zero if the date is before
    # the original migration date.

    # Get migration dates, but add one day as a safety margin
    surface_date = MigrationRecorder.Migration.objects.get(app='manager', name='0034_auto_20231107_1729').applied
    topography_date = MigrationRecorder.Migration.objects.get(app='manager', name='0035_auto_20231108_1315').applied

    # Fix surface dates
    Surface = apps.get_model('manager', 'surface')
    for s in Surface.objects.all():
        if s.creation_datetime and s.creation_datetime < surface_date:
            if hasattr(s, 'publication'):
                # If it is published, use publication date as creation date
                s.creation_datetime = s.publication.datetime
            else:
                s.creation_datetime = None
        if s.modification_datetime and s.modification_datetime < surface_date:
            s.modification_datetime = None
        s.save()

    # Fix topography dates
    Topography = apps.get_model('manager', 'topography')
    for t in Topography.objects.all():
        if t.creation_datetime and t.creation_datetime < topography_date:
            t.creation_datetime = None
        if t.modification_datetime and t.modification_datetime < topography_date:
            t.modification_datetime = None
        t.save()


class Migration(migrations.Migration):
    dependencies = [
        ('manager', '0047_alter_topography_task_memory'),
    ]

    operations = [
        migrations.AlterField(
            model_name='surface',
            name='creation_datetime',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name='surface',
            name='modification_datetime',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='creation_datetime',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='modification_datetime',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(
            forward_func
        ),
    ]
