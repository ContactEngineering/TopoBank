# Generated by Django 2.2.24 on 2021-06-25 12:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publication', '0004_auto_20210510_1252'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='container',
            field=models.FileField(default='', max_length=50, upload_to=''),
        ),
    ]