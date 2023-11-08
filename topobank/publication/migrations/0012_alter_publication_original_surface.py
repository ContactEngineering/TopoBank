# Generated by Django 3.2.18 on 2023-11-05 21:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0041_auto_20231024_2107'),
        ('publication', '0011_auto_20220228_1503'),
    ]

    operations = [
        migrations.AlterField(
            model_name='publication',
            name='original_surface',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='derived_publications', to='manager.surface'),
        ),
    ]
