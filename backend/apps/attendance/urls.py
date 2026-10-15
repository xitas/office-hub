from django.urls import path

from . import views

urlpatterns = [
    path("attendance/today/", views.TodayView.as_view(), name="attendance-today"),
    path("attendance/check-in/", views.CheckInView.as_view(), name="attendance-check-in"),
    path("attendance/check-out/", views.CheckOutView.as_view(), name="attendance-check-out"),
    path("attendance/month/", views.MonthView.as_view(), name="attendance-month"),
    path("attendance/team/", views.TeamDayView.as_view(), name="attendance-team"),
    path("attendance/team-month/", views.TeamMonthView.as_view(), name="attendance-team-month"),
    path("attendance/correct/", views.CorrectView.as_view(), name="attendance-correct"),
]
