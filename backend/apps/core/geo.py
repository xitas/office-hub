"""A place's pin (latitude/longitude) on contacts, companies, vendors and visits, for the map.

A pin marks where a client, vendor or site is: a place, not a person's position, so it isn't removed after 90 days
like check-in locations are. It's optional, set by dropping it on the map or "use my location" at the place.
"""
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext as _
from rest_framework import serializers


def pin_fields():
    """latitude and longitude model fields (decimal degrees, 6 places ≈ 10 cm)."""
    return (
        models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True),
        models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True),
    )


def pin_constraint(name: str) -> models.CheckConstraint:
    """Both or neither, and in range."""
    return models.CheckConstraint(
        condition=Q(latitude__isnull=True, longitude__isnull=True)
        | Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
        name=name,
    )


def serializer_fields() -> dict:
    return {
        "latitude": serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False, allow_null=True),
        "longitude": serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, required=False, allow_null=True),
    }


def check_pin(attrs: dict, instance=None):
    """Raise a ValidationError unless latitude and longitude come together (or are both cleared)."""
    if "latitude" not in attrs and "longitude" not in attrs:
        return
    lat = attrs.get("latitude", getattr(instance, "latitude", None))
    lng = attrs.get("longitude", getattr(instance, "longitude", None))
    if (lat is None) != (lng is None):
        raise serializers.ValidationError({"latitude": _("Give both latitude and longitude, or neither.")})


class PinSerializerMixin:
    """For ModelSerializers of records with a pin: list "latitude", "longitude" in Meta.fields and
    PIN_KWARGS in extra_kwargs."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        check_pin(attrs, getattr(self, "instance", None))
        return attrs


PIN_KWARGS = {
    "latitude": {"min_value": -90, "max_value": 90},
    "longitude": {"min_value": -180, "max_value": 180},
}
