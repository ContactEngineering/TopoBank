# Generated by Django 4.2.16 on 2024-09-24 18:13

import tagulous.models.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0063_alter_topography_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='surface',
            name='tags',
            field=tagulous.models.fields.TagField(_set_tag_meta=True, help_text='Enter a comma-separated tag string', to='manager.tag', tree=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='tags',
            field=tagulous.models.fields.TagField(_set_tag_meta=True, help_text='Enter a comma-separated tag string', to='manager.tag', tree=True),
        ),
    ]
