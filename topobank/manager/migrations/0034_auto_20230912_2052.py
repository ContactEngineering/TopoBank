# Generated by Django 3.2.18 on 2023-09-12 18:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0033_surfacecollection'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topography',
            name='measurement_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='size_x',
            field=models.FloatField(null=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='unit',
            field=models.TextField(choices=[('km', 'kilometers'), ('m', 'meters'), ('mm', 'millimeters'), ('µm', 'micrometers'), ('nm', 'nanometers'), ('Å', 'angstrom'), ('pm', 'picometers')], null=True),
        ),
        migrations.AlterField(
            model_name='topography',
            name='data_source',
            field=models.IntegerField(null=True),
        ),
    ]