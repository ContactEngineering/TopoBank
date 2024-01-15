# Generated by Django 3.2.18 on 2023-11-25 19:26
import logging

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import migrations, models
import django.db.models.deletion
from guardian.shortcuts import UserObjectPermission, GroupObjectPermission

from topobank.manager.models import SurfaceUserObjectPermission, SurfaceGroupObjectPermission

_log = logging.getLogger(__name__)


def forward_func(apps, schema_editor):
    # Migrating user permissions
    user_object_perms = UserObjectPermission.objects.all()  # 'old' user perms
    _log.info(f"Migrating {user_object_perms.count()} UserObjectPermissions...")
    for user_object_perm in user_object_perms:
        # Check whether content_object actually exists. It may not exist because there is no contraint/key linking
        # those together in the standard guardian permissions, i.e. we may have dangling permissions in the database.
        if user_object_perm.content_object is not None:
            SurfaceUserObjectPermission.objects.create(user=user_object_perm.user,
                                                       content_object=user_object_perm.content_object,
                                                       permission=user_object_perm.permission)
    _log.info(f"{SurfaceUserObjectPermission.objects.count()} SurfaceUserObjectPermissions after migration.")

    # Migrating group permissions
    group_object_perms = GroupObjectPermission.objects.all()  # 'old' group perms
    _log.info(f"Migrating {group_object_perms.count()} GroupObjectPermissions...")
    for group_object_perm in group_object_perms:
        # Check whether content_object actually exists. It may not exist because there is no contraint/key linking
        # those together in the standard guardian permissions, i.e. we may have dangling permissions in the database.
        if group_object_perm.content_object is not None:
            SurfaceGroupObjectPermission.objects.create(group=group_object_perm.group,
                                                        content_object=group_object_perm.content_object,
                                                        permission=group_object_perm.permission)
    _log.info(f"{SurfaceGroupObjectPermission.objects.count()} SurfaceGroupObjectPermissions after migration.")

def reverse_func(apps, schema_editor):
    surface_content_type = ContentType.objects.get(app_label='manager', model='surface')
    # Reversing User permission migration
    user_object_perms = SurfaceUserObjectPermission.objects.all()  # 'old' user perms
    _log.info(f"Migrating {user_object_perms.count()} SurfaceUserObjectPermissions")
    for user_object_perm in user_object_perms:
        UserObjectPermission.objects.get_or_create(user=user_object_perm.user,
                                                   content_type=surface_content_type,
                                                   object_pk= user_object_perm.content_object.id,
                                                   permission=user_object_perm.permission)
    # Migrating group permissions
    group_object_perms = SurfaceGroupObjectPermission.objects.all()  # 'old' group perms
    _log.info(f"Migrating {group_object_perms.count()} SurfaceGroupObjectPermissions")
    for group_object_perm in group_object_perms:
        GroupObjectPermission.objects.get_or_create(group=group_object_perm.group,
                                                    content_type=surface_content_type,
                                                    object_pk=group_object_perm.content_object.id,
                                                    permission=group_object_perm.permission)

class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('manager', '0044_alter_topography_instrument_parameters'),
    ]

    operations = [
        migrations.CreateModel(
            name='SurfaceUserObjectPermission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'content_object',
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='manager.surface')),
                ('permission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='auth.permission')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'unique_together': {('user', 'permission', 'content_object')},
            },
        ),
        migrations.CreateModel(
            name='SurfaceGroupObjectPermission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'content_object',
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='manager.surface')),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='auth.group')),
                ('permission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='auth.permission')),
            ],
            options={
                'abstract': False,
                'unique_together': {('group', 'permission', 'content_object')},
            },
        ),
        migrations.RunPython(
            forward_func,
            reverse_func
        )
    ]
