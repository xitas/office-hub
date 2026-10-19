from django.urls import path

from . import views

urlpatterns = [
    path("reports/people/", views.PeopleView.as_view(), name="report-people"),
    path("reports/task-completion/", views.TaskCompletionView.as_view(), name="report-task-completion"),
    path("reports/task-completion/export/", views.TaskCompletionExportView.as_view(), name="report-task-completion-export"),
    path("reports/overdue-tasks/", views.OverdueTasksView.as_view(), name="report-overdue-tasks"),
    path("reports/overdue-tasks/export/", views.OverdueTasksExportView.as_view(), name="report-overdue-tasks-export"),
]
