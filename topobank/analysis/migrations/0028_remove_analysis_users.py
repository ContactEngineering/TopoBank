# Generated by Django 4.2.14 on 2024-08-13 20:31

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("analysis", "0027_analysis_users_to_user"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="analysis",
            name="users",
        ),
    ]
