# Generated by Django 2.2.13 on 2021-01-19 09:41

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0006_auto_20210113_0931'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisfunction',
            name='card_view_flavor',
            field=models.CharField(choices=[('simple', 'Simple display of the results as raw data structure'), ('plot', 'Display results in a plot with multiple datasets'), ('power spectrum', 'Display results in a plot suitable for power spectrum'), ('contact mechanics', 'Display suitable for contact mechanics including special widgets'), ('rms table', 'Display a table with RMS values.')], default='simple', max_length=50),
        ),
        migrations.CreateModel(
            name='AnalysisFunctionImplementation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject_type', models.CharField(choices=[('t', 'topography'), ('s', 'surface')], max_length=1)),
                ('pyfunc', models.CharField(max_length=256)),
                ('function', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='implementations', to='analysis.AnalysisFunction')),
            ],
        ),
        migrations.AddConstraint(
            model_name='analysisfunctionimplementation',
            constraint=models.UniqueConstraint(fields=('function', 'subject_type'), name='distinct_implementation'),
        ),
    ]
