"""The shared office calendar: meetings, office events and holidays.

- Meetings: an organizer, attendees, optionally a room (a booking made through the bookings app, so
  the room's rules, approvals and "no double booking" apply). Anyone organizes meetings.
- Events: office happenings (a training, the annual dinner) for everyone or chosen departments;
  managers add them for their department, admins for anyone.
- Holidays: office closed, whole days, for everyone; admins add them.
Times are stored in UTC; all-day items run from the office's midnight to the next midnight(s).
Task deadlines and bookings appear on the calendar too, read from their own apps (see feed.py).
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Event(models.Model):
    class Kind(models.TextChoices):
        MEETING = "meeting", _("Meeting")
        EVENT = "event", _("Office event")
        HOLIDAY = "holiday", _("Holiday")

    class Audience(models.TextChoices):
        EVERYONE = "everyone", _("Everyone")
        DEPARTMENTS = "departments", _("Chosen departments")

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MEETING, db_index=True)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=150, blank=True)
    all_day = models.BooleanField(default=False)
    start = models.DateTimeField()
    end = models.DateTimeField()
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="organized_events")
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="calendar_invites")
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.EVERYONE)
    departments = models.ManyToManyField("accounts.Department", blank=True, related_name="calendar_events")
    # A meeting's room: the booking holds the room (and goes through its approval if the room needs it).
    booking = models.OneToOneField("bookings.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="meeting")
    # The start time the 15-minute reminder went out for (a moved meeting gets a new one).
    reminded_start = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start", "id"]
        indexes = [models.Index(fields=["start", "end"], name="event_range_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="event_ends_after_start")]
        verbose_name = _("calendar event")
        verbose_name_plural = _("calendar events")

    def __str__(self):
        return self.title
