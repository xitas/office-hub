from django.apps import AppConfig


class ExpensesConfig(AppConfig):
    name = "apps.expenses"
    label = "expenses"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files

        from . import integration
        from .models import ExpenseReceipt

        post_delete.connect(remove_attachment_files, sender=ExpenseReceipt, dispatch_uid="expenses.receipt.files")
        integration.register()  # claims in "Pending approvals"
