# Generated by Django 2.0.6 on 2018-07-11 15:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0003_auto_20180621_1222'),
    ]

    operations = [
        migrations.AddField(
            model_name='topography',
            name='name',
            field=models.CharField(default='testname', max_length=80),
            preserve_default=False,
        ),
    ]
