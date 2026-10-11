"""A realistic task dataset for query-count and performance tests.

Tasks spread over people in two departments, with several assignees, links to contacts and
companies, checklists, comments and activity, built with bulk inserts so thousands stay fast.
"""
import random
from datetime import timedelta

from apps.contacts.models import Company, Contact
from apps.core.office_time import office_today
from apps.tasks.models import ChecklistItem, Task, TaskActivity, TaskComment

STATUSES = ["todo", "in_progress", "review", "done"]
PRIORITIES = ["low", "medium", "high", "urgent"]


def build(people, n_tasks, *, seed=1, companies=5, contacts_per_company=4):
    """Create `n_tasks` tasks for `people` (a list of users). Returns the companies and contacts."""
    rnd = random.Random(seed)
    owner = people[0]
    comps = [Company.objects.create(name=f"Company {i}", assigned_to=owner) for i in range(companies)]
    conts = [
        Contact.objects.create(first_name=f"Person{c}", last_name=f"Of{i}", company=comp, assigned_to=owner)
        for i, comp in enumerate(comps) for c in range(contacts_per_company)
    ]
    today = office_today()
    first_pk = (Task.objects.order_by("-pk").values_list("pk", flat=True).first() or 0) + 1
    tasks = []
    for i in range(n_tasks):
        status = STATUSES[i % 4]
        link = i % 3
        tasks.append(Task(
            title=f"Task {i}",
            description="Details " * 5,
            status=status,
            priority=PRIORITIES[i % 4],
            due_date=None if i % 10 == 0 else today + timedelta(days=rnd.randint(-20, 20)),
            contact=conts[i % len(conts)] if link == 0 else None,
            company=comps[i % len(comps)] if link == 1 else None,
            created_by=people[i % len(people)],
        ))
    Task.objects.bulk_create(tasks, batch_size=500)
    tasks = list(Task.objects.filter(pk__gte=first_pk).order_by("pk"))
    Task.objects.filter(pk__gte=first_pk, status="done").update(completed_at=tasks[0].created_at)

    Through = Task.assignees.through
    links = []
    for i, task in enumerate(tasks):
        chosen = rnd.sample(people, k=1 + i % 3)  # one to three assignees
        links += [Through(task_id=task.pk, user_id=u.pk) for u in chosen]
    Through.objects.bulk_create(links, batch_size=1000)

    items, comments, events = [], [], []
    for i, task in enumerate(tasks):
        for j in range(i % 5):
            items.append(ChecklistItem(task=task, text=f"Step {j}", done=j % 2 == 0, position=j, created_by=task.created_by))
        for j in range(i % 3):
            comments.append(TaskComment(task=task, author=task.created_by, body=f"Comment {j}"))
        events.append(TaskActivity(task=task, actor=task.created_by, kind="created", data={}))
        if task.status == "done":
            events.append(TaskActivity(task=task, actor=task.created_by, kind="status", data={"old": "todo", "new": "done"}))
    ChecklistItem.objects.bulk_create(items, batch_size=1000)
    TaskComment.objects.bulk_create(comments, batch_size=1000)
    TaskActivity.objects.bulk_create(events, batch_size=1000)
    return {"companies": comps, "contacts": conts}
