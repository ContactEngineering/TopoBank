# Generated by Django 4.2.16 on 2024-12-04 13:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0032_analysis_name_alter_analysis_function"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysis",
            name="dependencies",
            field=models.JSONField(default=dict),
        ),
    ]
