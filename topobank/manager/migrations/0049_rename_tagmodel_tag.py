# Generated by Django 4.2.7 on 2024-02-04 07:25

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0048_alter_surface_creation_datetime_and_more'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='TagModel',
            new_name='Tag',
        ),
    ]
