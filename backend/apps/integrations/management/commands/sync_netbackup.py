"""Pulls a per-tenant summary from NetBackup (device counts, backup health,
POP estimate) and records it as MetricObservation history for each mapped
tenant. Meant to be invoked by an external cron/systemd timer (this
project has no worker/queue infra — see docs/architecture.md) — recommended
daily, since idempotency below is bucketed by calendar day.

Never wrapped in an outer @transaction.atomic: each
`with tenant_context(...)` block is already its own transaction
(apps.tenancy.context.tenant_context), which is what gives per-tenant
atomicity and lets one tenant's failure never roll back a sibling tenant's
already-committed writes, or the IntegrationRun row itself.
"""

from datetime import datetime
from decimal import Decimal

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.models import ExternalObjectMapping, IntegrationRun
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.portal.services import save_record
from apps.tenancy.context import tenant_context

POP_COUNT_ASSUMPTIONS = (
    "Contagem aproximada por valores distintos de Device.site (texto livre, "
    "sem normalização); pode haver divergência por grafia/caixa inconsistente."
)


def _ensure_sync_actor():
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username="sync.netbackup",
        defaults={"email": "sync.netbackup@localhost.invalid", "role": "consultant"},
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def _fetch_netbackup_summary() -> dict:
    url = f"{settings.NETBACKUP_API_URL.rstrip('/')}/integrations/portal/tenant-summary"
    headers = {"Authorization": f"Bearer {settings.NETBACKUP_API_TOKEN}"}
    response = httpx.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def _write_observations(actor, tenant_id, row, entry):
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


class Command(BaseCommand):
    help = "Sincroniza contagens de equipamentos/backup do NetBackup para MetricObservation."

    def handle(self, *args, **options):
        if not settings.NETBACKUP_API_URL or not settings.NETBACKUP_API_TOKEN:
            self.stdout.write(
                self.style.WARNING(
                    "NETBACKUP_API_URL/NETBACKUP_API_TOKEN não configurados; ignorando."
                )
            )
            return

        actor = _ensure_sync_actor()
        run = IntegrationRun.objects.create(system="netbackup")

        mappings = list(
            ExternalObjectMapping.objects.filter(system="netbackup").select_related("tenant")
        )
        run.tenants_considered = len(mappings)
        if not mappings:
            run.status = IntegrationRun.Status.SUCCESS
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at", "tenants_considered"])
            self.stdout.write(self.style.SUCCESS("Nenhum ExternalObjectMapping cadastrado."))
            return

        try:
            payload = _fetch_netbackup_summary()
        except (httpx.HTTPError, ValueError) as exc:
            run.status = IntegrationRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error = str(exc)[:2000]
            run.save(update_fields=["status", "finished_at", "error", "tenants_considered"])
            self.stderr.write(self.style.ERROR(f"Falha ao consultar o NetBackup: {exc}"))
            return

        by_slug = {row["tenant_slug"]: row for row in payload["tenants"]}
        details: list[dict] = []
        succeeded = 0
        failed = 0

        for mapping in mappings:
            entry = {"external_id": mapping.external_id, "isp_tenant": str(mapping.tenant_id)}
            row = by_slug.get(mapping.external_id)
            if row is None:
                entry["outcome"] = "not_found_in_netbackup"
                failed += 1
            else:
                try:
                    with tenant_context(mapping.tenant_id):
                        _write_observations(actor, mapping.tenant_id, row, entry)
                    entry["outcome"] = "ok"
                    succeeded += 1
                except Exception as exc:  # noqa: BLE001 — one tenant's failure must not abort the run
                    entry["outcome"] = "error"
                    entry["message"] = str(exc)[:500]
                    failed += 1
            details.append(entry)

        run.tenants_matched = sum(1 for m in mappings if m.external_id in by_slug)
        run.tenants_succeeded = succeeded
        run.tenants_failed = failed
        if failed == 0:
            run.status = IntegrationRun.Status.SUCCESS
        elif succeeded == 0:
            run.status = IntegrationRun.Status.FAILED
        else:
            run.status = IntegrationRun.Status.PARTIAL_FAILURE
        run.finished_at = timezone.now()
        run.details = details
        run.save(
            update_fields=[
                "tenants_matched",
                "tenants_succeeded",
                "tenants_failed",
                "status",
                "finished_at",
                "details",
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronização concluída: {succeeded} ok, {failed} falha(s) de "
                f"{len(mappings)} mapeamento(s)."
            )
        )
