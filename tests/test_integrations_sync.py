"""Tests for apps.integrations.management.commands.sync_netbackup — the
NetBackup pull-sync job. Mocks the outbound HTTP call
(`services.fetch_netbackup_summary`) directly, no real network/DB-external
access.
"""

from datetime import timedelta

import httpx
import pytest
from apps.integrations import services
from apps.integrations.models import ExternalObjectMapping, IntegrationRun
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.tenancy.context import tenant_context
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

METRIC_KEYS = [
    "netbackup-active-devices",
    "netbackup-backup-ok",
    "netbackup-backup-freshness-hours",
    "netbackup-pop-count",
]


def _seed_metric_definitions():
    for key in METRIC_KEYS:
        MetricDefinition.objects.get_or_create(key=key, defaults={"name": key, "unit": "n/a"})


def _row(**overrides):
    base = {
        "tenant_slug": "alpha",
        "tenant_name": "ISP Alpha",
        "device_count_active": 10,
        "backup_ok_count": 8,
        "last_backup_at": timezone.now().isoformat(),
        "pop_count": 3,
    }
    base.update(overrides)
    return base


@override_settings(NETBACKUP_API_URL="", NETBACKUP_API_TOKEN="")
@pytest.mark.django_db
def test_unset_config_is_a_no_op_without_integration_run():
    call_command("sync_netbackup")
    assert IntegrationRun.objects.count() == 0


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_zero_mappings_creates_a_successful_empty_run():
    call_command("sync_netbackup")
    run = IntegrationRun.objects.get()
    assert run.status == IntegrationRun.Status.SUCCESS
    assert run.tenants_considered == 0


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_happy_path_writes_four_published_observations(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(services, "fetch_netbackup_summary", lambda: {"tenants": [_row()]})

    call_command("sync_netbackup")

    run = IntegrationRun.objects.get()
    assert run.status == IntegrationRun.Status.SUCCESS
    assert run.tenants_succeeded == 1
    assert run.tenants_failed == 0

    with tenant_context(domain.a.id):
        observations = MetricObservation.objects.filter(definition__key__in=METRIC_KEYS)
        assert observations.count() == 4
        assert all(o.published for o in observations)

    actor = get_user_model().objects.get(username="sync.netbackup")
    assert actor.is_consultant
    assert not actor.has_usable_password()


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_tenant_with_no_backups_skips_freshness_metric(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(
        services,
        "fetch_netbackup_summary",
        lambda: {"tenants": [_row(last_backup_at=None)]},
    )

    call_command("sync_netbackup")

    with tenant_context(domain.a.id):
        observations = MetricObservation.objects.filter(definition__key__in=METRIC_KEYS)
        assert observations.count() == 3
        assert not observations.filter(definition__key="netbackup-backup-freshness-hours").exists()


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_slug_not_found_marks_partial_failure_without_affecting_other_tenants(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    ExternalObjectMapping.objects.create(system="netbackup", external_id="bravo", tenant=domain.b)
    monkeypatch.setattr(
        services,
        "fetch_netbackup_summary",
        lambda: {"tenants": [_row(tenant_slug="bravo")]},  # "alpha" missing
    )

    call_command("sync_netbackup")

    run = IntegrationRun.objects.get()
    assert run.status == IntegrationRun.Status.PARTIAL_FAILURE
    assert run.tenants_succeeded == 1
    assert run.tenants_failed == 1
    with tenant_context(domain.b.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 4
    with tenant_context(domain.a.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 0


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_transport_failure_aborts_whole_run_with_zero_writes(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)

    def _boom():
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(services, "fetch_netbackup_summary", _boom)

    call_command("sync_netbackup")

    run = IntegrationRun.objects.get()
    assert run.status == IntegrationRun.Status.FAILED
    assert run.error
    with tenant_context(domain.a.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 0


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_rerunning_same_day_skips_already_synced_metrics(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(services, "fetch_netbackup_summary", lambda: {"tenants": [_row()]})

    call_command("sync_netbackup")
    call_command("sync_netbackup")

    with tenant_context(domain.a.id):
        # Still 4 — the second run's writes were all skipped as same-day.
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 4

    second_run = IntegrationRun.objects.order_by("-started_at").first()
    assert set(second_run.details[0]["skipped_already_synced_today"]) == set(METRIC_KEYS)


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_a_mid_batch_exception_rolls_back_that_tenants_partial_writes(domain, monkeypatch):
    """`netbackup-pop-count` (the 3rd of 4 candidates) is deliberately left
    unseeded, so `write_observations_for_tenant` raises `MetricDefinition.DoesNotExist`
    after the first two observations (active-devices, backup-ok) would
    already have been created. `MetricDefinition` is a global catalog, not
    tenant-scoped, so this affects every tenant — proving two things at
    once: (a) one tenant's exception never aborts the whole run (the
    command still finishes, logs tenants_failed, doesn't raise), and (b)
    `tenant_context`'s per-tenant transaction rolls back the *whole* batch,
    not just the observation that raised — no orphaned partial writes.
    """
    _seed_metric_definitions()
    MetricDefinition.objects.filter(key="netbackup-pop-count").delete()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    ExternalObjectMapping.objects.create(system="netbackup", external_id="bravo", tenant=domain.b)
    monkeypatch.setattr(
        services,
        "fetch_netbackup_summary",
        lambda: {"tenants": [_row(tenant_slug="alpha"), _row(tenant_slug="bravo")]},
    )

    call_command("sync_netbackup")

    run = IntegrationRun.objects.get()
    assert run.status == IntegrationRun.Status.FAILED
    assert run.tenants_succeeded == 0
    assert run.tenants_failed == 2
    with tenant_context(domain.a.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 0


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_pop_count_observation_is_marked_estimated_with_assumptions(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(services, "fetch_netbackup_summary", lambda: {"tenants": [_row()]})

    call_command("sync_netbackup")

    with tenant_context(domain.a.id):
        pop_observation = MetricObservation.objects.get(definition__key="netbackup-pop-count")
        assert pop_observation.estimated is True
        assert pop_observation.assumptions.strip()


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_freshness_hours_computed_from_raw_timestamp(domain, monkeypatch):
    _seed_metric_definitions()
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    last_backup_at = timezone.now() - timedelta(hours=5)
    monkeypatch.setattr(
        services,
        "fetch_netbackup_summary",
        lambda: {"tenants": [_row(last_backup_at=last_backup_at.isoformat())]},
    )

    call_command("sync_netbackup")

    with tenant_context(domain.a.id):
        freshness = MetricObservation.objects.get(
            definition__key="netbackup-backup-freshness-hours"
        )
        assert 4.9 <= float(freshness.value) <= 5.1


@pytest.mark.django_db
def test_sync_mapping_in_isolation_against_an_already_fetched_payload(domain):
    """services.sync_mapping() is what apps.portal.views.netbackup_import
    calls right after creating a mapping — exercises it directly, with a
    payload the caller already fetched, not via the management command.
    """
    _seed_metric_definitions()
    mapping = ExternalObjectMapping.objects.create(
        system="netbackup", external_id="alpha", tenant=domain.a
    )
    actor = services.ensure_sync_actor()
    payload = {"tenants": [_row()]}

    entry = services.sync_mapping(actor, mapping, payload)

    assert entry["outcome"] == "ok"
    with tenant_context(domain.a.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 4


@pytest.mark.django_db
def test_sync_mapping_reports_not_found_without_touching_other_tenants(domain):
    _seed_metric_definitions()
    mapping = ExternalObjectMapping.objects.create(
        system="netbackup", external_id="alpha", tenant=domain.a
    )
    actor = services.ensure_sync_actor()
    payload = {"tenants": [_row(tenant_slug="someone-else")]}

    entry = services.sync_mapping(actor, mapping, payload)

    assert entry["outcome"] == "not_found_in_netbackup"
    with tenant_context(domain.a.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 0
