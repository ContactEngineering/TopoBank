# Generated by Django 3.2.16 on 2022-10-19 11:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0011_remove_analysisfunction_card_view_flavor'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='analysis',
            options={'verbose_name_plural': 'analyses'},
        ),
    ]