import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Department, User

PASSWORD = "Str0ng!Pass#2026"


@pytest.fixture
def departments(db):
    return {
        "sales": Department.objects.create(name="Sales"),
        "ops": Department.objects.create(name="Operations"),
    }


@pytest.fixture
def make_user(db, departments):
    def _make(email, role=User.Role.STAFF, department="sales", **extra):
        return User.objects.create_user(
            email=email,
            password=PASSWORD,
            full_name=extra.pop("full_name", email.split("@")[0].title()),
            role=role,
            department=departments.get(department) if department else None,
            **extra,
        )

    return _make


@pytest.fixture
def admin(make_user):
    return make_user("admin@test.com", User.Role.ADMIN, department=None)


@pytest.fixture
def manager(make_user):
    return make_user("manager@test.com", User.Role.MANAGER)


@pytest.fixture
def staff(make_user):
    return make_user("staff@test.com", User.Role.STAFF)


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def client_for(api):
    def _client(user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    return _client


@pytest.fixture(autouse=True)
def _clear_cache():
    # Cached organization settings (and rate limits) must not leak between tests.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
