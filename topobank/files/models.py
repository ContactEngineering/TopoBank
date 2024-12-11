"""
Basic models for handling files and folders, including upload/download logic.
"""

import logging

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone
from rest_framework.reverse import reverse
from storages.utils import clean_name

from ..authorization.mixins import PermissionMixin
from ..authorization.models import AuthorizedManager, PermissionSet
from .utils import file_storage_path

_log = logging.getLogger(__name__)


class Folder(PermissionMixin, models.Model):
    #
    # Manager
    #
    objects = AuthorizedManager()

    #
    # Permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Folder parameters
    #
    read_only = models.BooleanField("read_only", default=True)

    def __str__(self) -> str:
        return "Folder"

    def __len__(self) -> int:
        return self.files.count()

    def __getitem__(self, item):
        return self.files.all()[item]

    def open_file(self, filename: str, mode: str = "r"):
        return self.files.get(folder=self, filename=filename).open(mode)

    def save_file(self, filename: str, kind: str, fobj):
        # Check whether file exists, and delete if it does
        fobj.name = filename  # Make sure the filenames are the same
        manifest, created = Manifest.objects.get_or_create(
            folder=self, filename=filename
        )
        manifest.permissions = self.permissions
        manifest.folder = self
        manifest.kind = kind
        if not created:
            manifest.file.delete()
        manifest.file = fobj
        manifest.save()

    def exists(self, filename: str) -> bool:
        return self.files.filter(filename=filename).count() > 0

    def get_files(self) -> models.QuerySet["Manifest"]:
        return self.files.all()

    def get_valid_files(self) -> models.QuerySet["Manifest"]:
        # NOTE: "files" is the reverse `related_name` for the relation to `FileManifest`
        return self.get_files().filter(upload_confirmed__isnull=False)

    def find_file(self, filename: str) -> models.QuerySet["Manifest"]:
        return Manifest.objects.get(folder=self, filename=filename)

    def get_absolute_url(self, request=None) -> str:
        """URL of API endpoint for this folder"""
        return reverse(
            "files:folder-api-detail", kwargs=dict(pk=self.pk), request=request
        )

    def remove_files(self):
        """Clear this folder by removing all files"""
        self.files.all().delete()

    def deepcopy(self, permissions=None):
        copy = Folder.objects.get(pk=self.pk)
        copy.pk = None
        # TODO: handle permissions
        copy.save()

        for filemanifest in self.get_valid_files():
            filemanifest_copy = filemanifest.deepcopy()
            filemanifest_copy.folder = copy
            filemanifest_copy.save()

        return copy


# The Flow for "direct file upload" is heavily inspired from here:
# https://www.hacksoft.io/blog/direct-to-s3-file-upload-with-django
class Manifest(PermissionMixin, models.Model):
    class Meta:
        unique_together = ("folder", "filename")

    #
    # Manager
    #
    objects = AuthorizedManager()

    #
    # Permissions
    #
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Model data
    #

    FILE_KIND_CHOICES = [
        ("N/A", "Kind is unknown"),
        ("att", "Attachment"),  # Attachments are not processed by the system
        ("der", "Data derived from a raw data file"),
        ("raw", "Raw data file as uploaded by a user"),
    ]

    # The actual file
    file = models.FileField(
        upload_to=file_storage_path, max_length=512, blank=True, null=True
    )
    # The name of the file without any storage location
    filename = models.CharField(max_length=255)  # The filename

    # User that uploaded this file (if the file is not automatically generated as
    # indicated by file kind "der")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )

    # Folder can be null, in which case this is a single file that belongs to some
    # model (e.g. a raw data file or a thumbnail of a measurement)
    folder = models.ForeignKey(
        Folder, related_name="files", on_delete=models.CASCADE, null=True
    )

    # File kind, indicating where the file came from
    kind = models.CharField(max_length=3, choices=FILE_KIND_CHOICES, default="N/A")

    #
    # Dates - all three dates are typically similar
    #

    # The date the upload was confirmed by the `finish_upload` method. This is typically
    # the date the file was uploaded.
    upload_confirmed = models.DateTimeField(blank=True, null=True)
    # The date the manifest was created
    created = models.DateTimeField(auto_now_add=True)
    # The date the manifest was last updated
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Manifest <{self.filename}>"

    @property
    def url(self):
        return self.file.url

    def finish_upload(self, file=None):
        if file is None:
            if not settings.USE_S3_STORAGE:
                # Do nothing; without S3 uploads are finished through a special route
                # that provides the file here
                return
            try:
                storage_path = self.generate_storage_path()
            except SuspiciousFileOperation:
                # Could not create a storage path! This is likely because the file
                # name is invalid
                _log.info(
                    f"Manifest {self.id} has no file associated with it, and the "
                    f"filename '{self.filename}' appears invalid. Cannot finish "
                    "upload."
                )
                return
            _log.debug(
                f"Manifest {self.id} has no file associated with it. Checking if one "
                f"exists at the likely storage location '{storage_path}'..."
            )
            if default_storage.exists(storage_path):
                _log.debug("Found file, updating manifest...")
                # Set storage location to file that was just uploaded
                self.file = self.file.field.attr_class(
                    self, self.file.field, storage_path
                )
                self.upload_confirmed = timezone.now()
                self.save(update_fields=["file", "upload_confirmed"])
        else:
            self.file.save(self.filename, file, save=False)
            self.upload_confirmed = timezone.now()
            self.save(update_fields=["file", "upload_confirmed"])

    def exists(self):
        """Check if a file exists"""
        if not self.file:
            self.finish_upload()
        return bool(self.file)

    is_valid = exists

    def assert_exists(self):
        if not self.exists():
            raise OSError(
                f"Manifest {self.id} does not have a file associated with it."
            )

    def open(self, *args, **kwargs):
        self.assert_exists()
        return self.file.open(*args, **kwargs)

    def read(self, *args, **kwargs):
        self.assert_exists()
        return self.file.read(*args, **kwargs)

    def save(self, *args, **kwargs):
        created = self.pk is None  # True on creation of the manifest
        file = None
        if created and self.file:
            # We have a file but no id yet hence cannot create a storage path
            file = self.file
            self.file = None
        super().save(*args, **kwargs)
        if file:
            # No set the file name; we have an id and can create a storaga path and
            # upload the file
            self.file = file
            super().save(update_fields=["file"])
        # We have no file but a file name; make sure no file with the same name already
        # exists at the targeted storage location
        if created and not self.file and self.filename:
            # We just created this manifest and no file was passed on creation
            try:
                storage_path = self.generate_storage_path()
            except SuspiciousFileOperation:
                # We ignore this
                _log.info(
                    f"Manifest {self.id} has no file associated with it, and the "
                    f"filename '{self.filename}' appears invalid."
                )
                return
            if default_storage.exists(storage_path):
                if settings.DELETE_EXISTING_FILES:
                    default_storage.delete(storage_path)
                else:
                    raise RuntimeError(
                        "A new manifest was generated, but an existing file was found "
                        f"at the storage path {storage_path}. Set "
                        f"DELETE_EXISTING_FILES to True to ignore this error."
                    )

    def save_file(self, fobj):
        if self.exists():
            self.file.delete()
        self.file.save(self.filename, fobj)

    def deepcopy(self, permissions=None):
        copy = Manifest.objects.get(pk=self.pk)
        copy.pk = None  # This will lead to the creation of a new instance on save
        copy.file = None
        copy.folder = None

        # Set permissions
        if permissions is not None:
            copy.permissions = permissions

        # Save to get a pk
        copy.save()

        # Copy the actual data file
        with self.file.open(mode="rb") as file:
            copy.save_file(file)

        # Save again
        copy.save()

        return copy

    def get_absolute_url(self, request=None):
        """URL of API endpoint for this manifest"""
        return reverse(
            "manifest:folder-api-detail", kwargs=dict(pk=self.pk), request=request
        )

    def generate_storage_path(self):
        """Full path of the file on the storage backend"""
        return self.file.field.generate_filename(self, clean_name(self.filename))

    def get_upload_instructions(self, expire=3600, method=None):
        """Generate a presigned URL for an upload directly to S3"""
        # Preserve the trailing slash after normalizing the path.
        if method is None:
            method = settings.UPLOAD_METHOD

        if settings.USE_S3_STORAGE:
            # _normalize_name attaches the MEDIA_ROOT to the path. This is
            # typically done by default_storage.path, but S3 complains that
            # it does not support absolute paths if we use this method.
            try:
                storage_path = default_storage._normalize_name(
                    self.generate_storage_path()
                )
            except SuspiciousFileOperation:
                # This happens after migrations, when the file name is not yet set
                _log.info(
                    f"Manifest {self.id} has no file associated with it, and the "
                    f"filename '{self.filename}' appears invalid. Cannot generate "
                    "upload instructions."
                )
                return {}
            if method == "POST":
                upload_instructions = (
                    default_storage.bucket.meta.client.generate_presigned_post(
                        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                        Key=storage_path,
                        ExpiresIn=expire,
                    )
                )
                upload_instructions["method"] = "POST"
            elif method == "PUT":
                upload_instructions = {
                    "method": "PUT",
                    "url": default_storage.bucket.meta.client.generate_presigned_url(
                        ClientMethod="put_object",
                        Params={
                            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                            "Key": storage_path,
                            # ContentType must match content type of put request
                            "ContentType": "binary/octet-stream",
                        },
                        ExpiresIn=expire,
                    ),
                }
            else:
                raise RuntimeError(f"Unknown upload method: {method}")
        else:
            if method != "POST":
                raise RuntimeError("Only POST uploads are supported without S3")
            upload_instructions = {
                "method": "POST",
                "url": reverse(
                    "files:upload-direct-local", kwargs=dict(manifest_id=self.id)
                ),
                "fields": {},
            }
        return upload_instructions
