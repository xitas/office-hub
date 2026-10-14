"""Who sees, books, changes and approves.

- Everyone sees and books active resources open to everyone or to their department.
  Admins see every resource (also inactive ones) and manage them.
- Bookings of the resources you can see are visible to you (the office calendar), with title and booker.
- The person who booked, or an admin, edits and cancels a booking.
- A pending booking is approved or rejected by an admin, or by a manager of the requester's
  department (not by the requester).
"""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER

from .models import Booking, Resource


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def visible_resources(user):
    if is_admin(user):
        return Resource.objects.all()
    q = Q(bookable_by=Resource.BookableBy.EVERYONE)
    if user.department_id:
        opened = Resource.departments.through.objects.filter(department_id=user.department_id).values("resource_id")
        q |= Q(bookable_by=Resource.BookableBy.DEPARTMENTS, pk__in=opened)
    return Resource.objects.filter(q, is_active=True)


def can_book(user, resource) -> bool:
    if not resource.is_active:
        return False
    if is_admin(user) or resource.bookable_by == Resource.BookableBy.EVERYONE:
        return True
    return user.department_id is not None and resource.departments.filter(pk=user.department_id).exists()


def visible_bookings(user):
    return Booking.objects.filter(resource__in=visible_resources(user))


def can_manage(user, booking) -> bool:
    return is_admin(user) or booking.booked_by_id == user.pk


def can_decide(user, booking) -> bool:
    if booking.status != Booking.Status.PENDING:
        return False
    if booking.booked_by_id == user.pk and not is_admin(user):
        return False  # nobody but an admin approves their own request
    if is_admin(user):
        return True
    return user.role == MANAGER and user.department_id is not None and user.department_id == booking.booked_by.department_id


def decidable_bookings(user):
    """Pending bookings this person may approve or reject."""
    pending = Booking.objects.filter(status=Booking.Status.PENDING)
    if is_admin(user):
        return pending
    if user.role == MANAGER and user.department_id:
        return pending.filter(booked_by__department_id=user.department_id).exclude(booked_by=user)
    return pending.none()


def approvers_for(requester):
    """Who is asked: managers of the requester's department; admins when there are none."""
    managers = User.objects.filter(is_active=True, role=MANAGER, department_id=requester.department_id).exclude(pk=requester.pk)
    if requester.department_id and managers.exists():
        return list(managers)
    return list(User.objects.filter(is_active=True, role=ADMIN).exclude(pk=requester.pk))
