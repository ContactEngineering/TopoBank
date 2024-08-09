from django.contrib import admin

from .models import FileManifest, FileParent, Property, Surface, Topography


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'value_categorical', 'value_numerical', 'unit')


@admin.register(Surface)
class SurfaceAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'creation_datetime')
    ordering = ['-creation_datetime']


@admin.register(Topography)
class TopographyAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'creation_datetime', 'task_state', 'task_id')
    list_filter = ('task_state',)
    ordering = ['-creation_datetime']


@admin.register(FileManifest)
class FileManifestAdmin(admin.ModelAdmin):
    list_display = ('id', 'file', 'parent', 'kind', 'is_valid', 'created', 'updated')
    list_filter = ('kind', )
    ordering = ['-created']


@admin.register(FileParent)
class FileParentAdmin(admin.ModelAdmin):
    list_display = ('id', 'surface', 'topography')
