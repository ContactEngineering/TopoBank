# Generated by Django 3.2.16 on 2022-10-19 11:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0030_topography_short_reliability_cutoff'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='topography',
            options={'ordering': ['measurement_date', 'pk'], 'verbose_name_plural': 'topographies'},
        ),
    ]
