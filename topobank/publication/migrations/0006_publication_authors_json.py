# Generated by Django 3.2.11 on 2022-02-11 10:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publication', '0005_publication_container'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='authors_json',
            field=models.JSONField(default=list),
        ),
    ]
