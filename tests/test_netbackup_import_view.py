"""Tests for apps.portal.views.netbackup_import — the "vincular tenant
NetBackup" screen. Mocks apps.integrations.services the same way
test_integrations_sync.py does, no real network access.
"""

import pytest
from apps.integrations import services
from apps.integrations.models import ExternalObjectMapping
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant
from django.test import override_settings

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
        "tenant_slug": "charlie",
        "tenant_name": "ISP Charlie",
        "device_count_active": 2,
        "backup_ok_count": 2,
        "last_backup_at": None,
        "pop_count": 1,
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
def test_not_configured_shows_a_notice_without_calling_netbackup(domain, client, monkeypatch):
    with override_settings(NETBACKUP_API_URL="", NETBACKUP_API_TOKEN=""):
        client.force_login(domain.admin)
        response = client.get("/clients/import-netbackup/")
    assert response.status_code == 200
    assert response.context["not_configured"] is True


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_get_splits_linked_and_unlinked_tenants(domain, client, monkeypatch):
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(
        services,
        "fetch_netbackup_summary",
        lambda: {"tenants": [_row(tenant_slug="alpha", tenant_name="ISP Alpha"), _row()]},
    )

    client.force_login(domain.admin)
    response = client.get("/clients/import-netbackup/")

    assert response.status_code == 200
    linked_slugs = {t["tenant_slug"] for t in response.context["linked"]}
    unlinked_slugs = {t["tenant_slug"] for t in response.context["unlinked"]}
    assert linked_slugs == {"alpha"}
    assert unlinked_slugs == {"charlie"}


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_post_creates_tenant_client_mapping_and_syncs_immediately(domain, client, monkeypatch):
    _seed_metric_definitions()
    monkeypatch.setattr(services, "fetch_netbackup_summary", lambda: {"tenants": [_row()]})

    client.force_login(domain.admin)
    response = client.post("/clients/import-netbackup/", {"tenant_slug": "charlie"})

    tenant = Tenant.objects.get(slug="charlie")
    assert response.status_code == 302
    assert response.url == f"/t/{tenant.id}/"

    mapping = ExternalObjectMapping.objects.get(system="netbackup", external_id="charlie")
    assert mapping.tenant_id == tenant.id

    with tenant_context(tenant.id):
        assert MetricObservation.objects.filter(definition__key__in=METRIC_KEYS).count() == 3


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_post_rejects_a_slug_not_found_in_netbackup(domain, client, monkeypatch):
    monkeypatch.setattr(services, "fetch_netbackup_summary", lambda: {"tenants": []})

    client.force_login(domain.admin)
    response = client.post(
        "/clients/import-netbackup/", {"tenant_slug": "does-not-exist"}, follow=True
    )

    assert not Tenant.objects.filter(slug="does-not-exist").exists()
    messages = [str(m) for m in response.context["messages"]]
    assert any("não encontrado" in m for m in messages)


@override_settings(NETBACKUP_API_URL="http://netbackup.test", NETBACKUP_API_TOKEN="secret")
@pytest.mark.django_db
def test_post_rejects_an_already_linked_slug(domain, client, monkeypatch):
    ExternalObjectMapping.objects.create(system="netbackup", external_id="alpha", tenant=domain.a)
    monkeypatch.setattr(
        services, "fetch_netbackup_summary", lambda: {"tenants": [_row(tenant_slug="alpha")]}
    )

    client.force_login(domain.admin)
    response = client.post("/clients/import-netbackup/", {"tenant_slug": "alpha"}, follow=True)

    # Still exactly one mapping for "alpha" — no duplicate created.
    assert (
        ExternalObjectMapping.objects.filter(system="netbackup", external_id="alpha").count() == 1
    )
    messages = [str(m) for m in response.context["messages"]]
    assert any("já está vinculado" in m for m in messages)
