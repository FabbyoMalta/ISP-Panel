"""NetBackup sync logic — shared between
management/commands/sync_netbackup.py (all mappings, cron-invoked) and
apps.portal.views.netbackup_import (one mapping, right after the operator
creates it). See that command's module docstring for the per-tenant
atomicity/idempotency reasoning this still relies on.
"""

from datetime import datetime
from decimal import Decimal

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.integrations.models import ExternalObjectMapping
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.portal.services import save_record
from apps.tenancy.context import tenant_context

POP_COUNT_ASSUMPTIONS = (
    "Contagem aproximada por valores distintos de Device.site (texto livre, "
    "sem normalização); pode haver divergência por grafia/caixa inconsistente."
)


def ensure_sync_actor():
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username="sync.netbackup",
        defaults={"email": "sync.netbackup@localhost.invalid", "role": "consultant"},
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def fetch_netbackup_summary() -> dict:
    url = f"{settings.NETBACKUP_API_URL.rstrip('/')}/integrations/portal/tenant-summary"
    headers = {"Authorization": f"Bearer {settings.NETBACKUP_API_TOKEN}"}
    response = httpx.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def write_observations_for_tenant(actor, tenant_id, row, entry):
    now = timezone.now()
    today = timezone.localdate()
    entry["raw"] = row

    candidates = [
        ("netbackup-active-devices", Decimal(row["device_count_active"]), False, ""),
        ("netbackup-backup-ok", Decimal(row["backup_ok_count"]), False, ""),
        ("netbackup-pop-count", Decimal(row["pop_count"]), True, POP_COUNT_ASSUMPTIONS),
    ]
    if row["last_backup_at"]:
        last_backup_at = datetime.fromisoformat(row["last_backup_at"])
        hours = (now - last_backup_at).total_seconds() / 3600
        candidates.append(
            ("netbackup-backup-freshness-hours", Decimal(hours).quantize(Decimal("0.1")), False, "")
        )
    else:
        entry["freshness_skipped"] = "sem backups registrados"

    skipped = []
    for key, value, estimated, assumptions in candidates:
        definition = MetricDefinition.objects.get(key=key)
        latest = (
            MetricObservation.objects.filter(tenant_id=tenant_id, definition=definition)
            .order_by("-observed_at")
            .first()
        )
        if latest and latest.observed_at.date() == today:
            skipped.append(key)
            continue
        observation = MetricObservation(
            tenant_id=tenant_id,
            definition=definition,
            value=value,
            observed_at=now,
            source="Sincronização automática NetBackup",
            estimated=estimated,
            assumptions=assumptions,
            author=actor,
            published=True,
        )
        save_record(actor, observation)
    entry["skipped_already_synced_today"] = skipped


def sync_mapping(actor, mapping: ExternalObjectMapping, payload: dict) -> dict:
    """Syncs one ExternalObjectMapping against an already-fetched
    `payload` (the full GET /integrations/portal/tenant-summary body) —
    the caller fetches once and reuses it across every mapping in a run
    (the management command), or passes a just-fetched payload for the
    one mapping it cares about (the "vincular tenant" view). Never raises
    for a per-tenant problem (not found in NetBackup, a write error) —
    only a bad `payload` shape would propagate, which both callers treat
    as a transport-level failure anyway.
    """
    entry = {"external_id": mapping.external_id, "isp_tenant": str(mapping.tenant_id)}
    row = next((r for r in payload["tenants"] if r["tenant_slug"] == mapping.external_id), None)
    if row is None:
        entry["outcome"] = "not_found_in_netbackup"
        return entry

    try:
        with tenant_context(mapping.tenant_id):
            write_observations_for_tenant(actor, mapping.tenant_id, row, entry)
        entry["outcome"] = "ok"
    except Exception as exc:  # noqa: BLE001 — one mapping's failure must not abort the caller's loop
        entry["outcome"] = "error"
        entry["message"] = str(exc)[:500]
    return entry
