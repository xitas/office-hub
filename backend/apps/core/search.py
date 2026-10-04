"""Global search registry.

Each app registers what it wants searchable, e.g. in its AppConfig.ready():

    search.register(
        "users", queryset=lambda user: User.objects.filter(is_active=True),
        fields=["full_name", "email"], serialize=lambda u, viewer: {...}, permission=("users", "view"),
    )
"""
from dataclasses import dataclass
from typing import Callable

from django.db import connection
from django.db.models import Q

from .permissions import has_perm


@dataclass
class SearchSource:
    key: str
    queryset: Callable  # (user) -> QuerySet, already scoped to what the user may see
    fields: list[str]
    serialize: Callable  # (obj, user) -> dict with at least id, title, subtitle, url
    permission: tuple[str, str]


_registry: dict[str, SearchSource] = {}


def register(key, *, queryset, fields, serialize, permission):
    _registry[key] = SearchSource(key, queryset, fields, serialize, permission)


def search(user, query: str, limit: int = 5, types: list[str] | None = None) -> dict[str, list[dict]]:
    query = query.strip()
    results: dict[str, list[dict]] = {}
    if len(query) < 2:
        return results

    for source in _registry.values():
        if types and source.key not in types:
            continue
        if not has_perm(user, *source.permission):
            continue
        qs = source.queryset(user)
        match = Q()
        for field in source.fields:
            match |= Q(**{f"{field}__icontains": query})
        if connection.vendor == "postgresql" and len(query) >= 3:
            from django.contrib.postgres.search import SearchQuery, SearchVector

            qs = qs.annotate(_search=SearchVector(*source.fields))
            match |= Q(_search=SearchQuery(query, search_type="websearch"))
        hits = [source.serialize(obj, user) for obj in qs.filter(match).distinct()[:limit]]
        if hits:
            results[source.key] = hits
    return results
