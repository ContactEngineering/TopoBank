# Generated by Django 3.2.13 on 2022-07-08 13:24

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0009_remove_analysis_result'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AnalysisFunctionImplementation',
        ),
    ]
