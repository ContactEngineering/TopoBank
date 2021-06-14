# Generated by Django 2.2.24 on 2021-06-14 12:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0021_topography_squeezed_datafile'),
    ]

    operations = [
        migrations.AlterField(
            model_name='topography',
            name='detrend_mode',
            field=models.TextField(choices=[('center', 'No detrending, but substract mean height'), ('height', 'Remove tilt'), ('curvature', 'Remove curvature and tilt')], default='center'),
        ),
    ]
