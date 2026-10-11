from django.urls import path
from rest_framework.routers import DefaultRouter

from .collab_views import AttachmentFileViewSet, ChecklistViewSet, TaskAttachmentViewSet, TaskCommentViewSet
from .views import TaskViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("task-attachments", AttachmentFileViewSet, basename="task-attachment")

# Children of one task: /tasks/{task_pk}/checklist/, /comments/, /attachments/
urlpatterns = [
    path("tasks/<int:task_pk>/checklist/", ChecklistViewSet.as_view({"get": "list", "post": "create"}), name="task-checklist"),
    path("tasks/<int:task_pk>/checklist/reorder/", ChecklistViewSet.as_view({"post": "reorder"}), name="task-checklist-reorder"),
    path(
        "tasks/<int:task_pk>/checklist/<int:pk>/",
        ChecklistViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="task-checklist-item",
    ),
    path("tasks/<int:task_pk>/comments/", TaskCommentViewSet.as_view({"get": "list", "post": "create"}), name="task-comments"),
    path(
        "tasks/<int:task_pk>/comments/<int:pk>/",
        TaskCommentViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="task-comment",
    ),
    path("tasks/<int:task_pk>/attachments/", TaskAttachmentViewSet.as_view({"get": "list", "post": "create"}), name="task-attachments"),
    *router.urls,
]
