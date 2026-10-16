"""Dashboard "Pending approvals": everything waiting for my decision, oldest first, in one query.

Each app registers a source: a function returning a queryset of the requests this person may decide,
annotated with the same columns (``columns(...)``), and a formatter that turns one row into a widget item.
The sources are combined with UNION ALL, so the widget costs one query however many kinds there are.
"""
from typing import Callable

from django.db.models import CharField, DateField, DateTimeField, DecimalField, F, IntegerField, Value
from django.db.models.functions import Cast

COLUMNS = ("a_kind", "a_id", "a_created", "a_name", "a_label", "a_label_ur", "a_first", "a_last", "a_start", "a_end", "a_number", "a_extra")
TYPES = {
    "a_kind": CharField(), "a_id": IntegerField(), "a_created": DateTimeField(), "a_name": CharField(),
    "a_label": CharField(), "a_label_ur": CharField(), "a_first": DateField(), "a_last": DateField(),
    "a_start": DateTimeField(), "a_end": DateTimeField(), "a_number": DecimalField(max_digits=14, decimal_places=2),
    "a_extra": CharField(),
}

_sources: dict[str, tuple[Callable, Callable]] = {}


def register(kind: str, queryset: Callable, formatter: Callable):
    _sources[kind] = (queryset, formatter)


def columns(qs, kind: str, **values):
    """The source's rows as the shared columns (missing ones are typed NULLs, so the UNION matches on PostgreSQL)."""
    values = {"a_kind": Value(kind), "a_id": F("pk"), **values}
    exprs = {}
    for name in COLUMNS:  # annotated in COLUMNS order, so every part selects the columns in the same order
        expr = values.get(name)
        field = TYPES[name]
        if expr is None:
            expr = Value("") if isinstance(field, CharField) else Cast(Value(None), field)
        elif name in ("a_number", "a_first", "a_last", "a_start", "a_end", "a_created") or isinstance(expr, Value):
            expr = Cast(expr, field.clone())
        exprs[name] = expr
    return qs.order_by().annotate(**exprs).values_list(*COLUMNS)


def pending(user, limit=8) -> list[dict]:
    parts = [source(user) for source, _formatter in _sources.values()]
    if not parts:
        return []
    combined = parts[0].union(*parts[1:], all=True) if len(parts) > 1 else parts[0]
    rows = combined.order_by("a_created", "a_id")[:limit]
    out = []
    for row in rows:
        r = dict(zip(COLUMNS, row))
        out.append(_sources[r["a_kind"]][1](r))
    return out
