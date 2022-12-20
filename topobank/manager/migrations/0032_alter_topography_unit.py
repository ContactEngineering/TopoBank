# Generated by Django 3.2.16 on 2022-12-19 15:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0031_alter_topography_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topography',
            name='unit',
            field=models.TextField(choices=[('km', 'kilometers'), ('m', 'meters'), ('mm', 'millimeters'), ('µm', 'micrometers'), ('nm', 'nanometers'), ('Å', 'angstrom'), ('pm', 'picometers')]),
        ),
    ]
