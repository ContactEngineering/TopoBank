# Generated by Django 4.2.7 on 2024-03-14 14:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0025_remove_analysissubject_collection_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisfunction',
            name='memory_offset',
            field=models.FloatField(help_text='Offset b of the linear memory estimator a*x + b.', null=True),
        ),
        migrations.AddField(
            model_name='analysisfunction',
            name='memory_slope',
            field=models.FloatField(help_text='Slope a of the linear memory estimator a*x + b.', null=True),
        ),
    ]
