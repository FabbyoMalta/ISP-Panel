from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection, transaction

current_tenant = ContextVar("current_tenant", default=None)


@contextmanager
def tenant_context(tenant_id):
    """Only enter after authorization. SET LOCAL cannot leak through pooled connections."""
    with transaction.atomic():
        previous = current_tenant.get()
        token = current_tenant.set(str(tenant_id))
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
        try:
            yield
        finally:
            current_tenant.reset(token)
            if connection.vendor == "postgresql" and not connection.needs_rollback:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [previous or ""])
