# Generated by Django 3.2.18 on 2023-10-17 08:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0038_alter_topography_datafile'),
    ]

    operations = [
        migrations.AlterField(
            model_name='surface',
            name='name',
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
