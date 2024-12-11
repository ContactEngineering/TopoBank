import pint
from django.core.exceptions import ValidationError
from django.db import models

from topobank.authorization.mixins import PermissionMixin
from topobank.authorization.models import PermissionSet
from topobank.manager.models import Surface

_ureg = pint.UnitRegistry()


class Property(PermissionMixin, models.Model):
    class Meta:
        unique_together = (("surface", "name"),)
        verbose_name_plural = "properties"

    #
    # Model hierarchy and permissions
    #
    surface = models.ForeignKey(
        Surface, on_delete=models.CASCADE, related_name="properties"
    )
    permissions = models.ForeignKey(PermissionSet, on_delete=models.CASCADE, null=True)

    #
    # Model data
    #
    name = models.TextField(default="prop")
    value_categorical = models.CharField(blank=True, null=True)
    value_numerical = models.FloatField(blank=True, null=True)
    unit = models.TextField(null=True, blank=True)

    @property
    def value(self):
        if self.value_numerical is None:
            return str(self.value_categorical)
        return float(self.value_numerical)

    @value.setter
    def value(self, value):
        """
        Set the value of the property.

        Parameters:
        - value (int, float, str): The value to be assigned. Should be of type int, float, or str.

        Raises:
        - TypeError: If the provided value is not of type int, float, or str.

        Notes:
        - If the value is of type str, it will be assigned to the 'value_categorical' attribute.
        - If the value is of type int or float, it will be assigned to the 'value_numerical' attribute.
        """
        if isinstance(value, str):
            self.value_categorical = value
            self.value_numerical = None
        elif isinstance(value, float) or isinstance(value, int):
            self.value_numerical = value
            self.value_categorical = None
        else:
            raise TypeError(
                f"The value must be of type int, float or str, got {type(value)}"
            )

    def validate(self):
        """
        Checks the invariants of this Model.
        If any invariant is broken, a ValidationError is raised

        Invariants:
        - 1. `value_categorical` or `value_numerical` are `None`
        - 2. `value_categorical` or `value_numerical` are not `None`
        This results in a 'XOR' logic and exaclty one of the value fields has to hold a value
        - 3. if `value_categorical` is not `None`, unit is `None`

        This enforces the definition of a categorical values -> no units.

        IMPORTANT!
        The opposite is not the case!
        If a unit is `None` this could also mean that its a numerical value, with no dimension
        """

        # Invariant 1
        if not (self.value_categorical is None or self.value_numerical is None):
            raise ValidationError(
                "Either 'value_categorical' or 'value_numerical' must be None."
            )
        # Invariant 2
        if not (self.value_categorical is not None or self.value_numerical is not None):
            raise ValidationError(
                "Either 'value_categorical' or 'value_numerical' must be not None."
            )
        # Invariant 3
        if self.value_categorical is not None and self.unit is not None:
            raise ValidationError(
                "If the Property is categorical, the unit must be 'None'"
            )
        # Check unit
        if self.unit is not None:
            try:
                _ureg.check(str(self.unit))
            except pint.errors.UndefinedUnitError:
                raise ValidationError(f"Unit '{self.unit}' is not a physical unit")

    def save(self, *args, **kwargs):
        self.validate()
        created = self.pk is None
        if created:
            self.permissions = self.surface.permissions
        super().save(*args, **kwargs)

    def deepcopy(self, to_surface):
        """Creates a copy of this property.

        Parameters
        ----------
        to_surface: Surface
            target surface

        Returns
        -------
        The copied property.

        """
        copy = Property.objects.get(pk=self.pk)
        copy.pk = None
        copy.surface = to_surface
        copy.permissions = to_surface.permissions
        copy.save()

    @property
    def is_numerical(self):
        return self.value_numerical is not None

    @property
    def is_categorical(self):
        return not self.is_numerical

    def __str__(self):
        if self.is_numerical:
            return f"{self.name}: {self.value} {self.unit}"
        else:
            return f"{self.name}: {self.value}"

    def to_dict(self):
        d = {"name": str(self.name), "value": self.value}
        if self.unit is not None:
            d["unit"] = str(self.unit)
        return d
