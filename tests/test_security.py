import json
import uuid

import pytest
from apps.inventory.models import Resource, ResourceType
from apps.recommendations.models import Recommendation, RecommendationDependency
from apps.tenancy.context import current_tenant, tenant_context
from apps.tenancy.models import Tenant
from django.core.exceptions import ValidationError
from django.test import Client as Browser
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_scope_denies_without_context_and_restores_after_error(domain):
    assert Recommendation.objects.count() == 0
    with tenant_context(domain.a.id):
        assert list(Recommendation.objects.values_list("title", flat=True)) == [domain.rec_a.title]
        with pytest.raises(RuntimeError):
            with tenant_context(domain.b.id):
                assert Recommendation.objects.count() == 1
                raise RuntimeError("test")
        assert current_tenant.get() == str(domain.a.id)
    assert current_tenant.get() is None


def test_cross_tenant_relationship_rejected(domain):
    with tenant_context(domain.a.id), pytest.raises(ValidationError):
        RecommendationDependency.objects.create(
            tenant=domain.a, recommendation=domain.rec_a, prerequisite=domain.rec_b
        )


def test_tenant_and_object_id_access_denied(domain, client):
    client.force_login(domain.customer)
    assert client.get(f"/t/{domain.b.id}/").status_code == 404
    assert client.get(f"/api/v1/t/{domain.b.id}/recommendations/").status_code == 404
    assert (
        client.get(f"/api/v1/t/{domain.a.id}/recommendations/{domain.rec_b.id}/").status_code == 404
    )
    assert client.get(f"/t/{domain.a.id}/recommendations/{domain.rec_b.id}/").status_code == 404
    assert client.get(f"/t/{uuid.uuid4()}/").status_code == 404
    assert client.get("/does-not-exist/").status_code == 404


def test_client_has_no_internal_fields_and_cannot_write(domain, client):
    client.force_login(domain.customer)
    for path in [
        f"/api/v1/t/{domain.a.id}/recommendations/",
        f"/api/v1/t/{domain.a.id}/clients/",
        f"/t/{domain.a.id}/data/client/",
        f"/t/{domain.a.id}/recommendations/{domain.rec_a.id}/",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"CONFIDENTIAL-INTERNAL" not in response.content
        assert b"internal_notes" not in response.content
    endpoint = f"/api/v1/t/{domain.a.id}/recommendations/{domain.rec_a.id}/"
    assert (
        client.patch(
            endpoint, json.dumps({"title": "HACK"}), content_type="application/json"
        ).status_code
        == 403
    )
    assert client.post(f"/t/{domain.a.id}/data/risks/new/", {"title": "HACK"}).status_code == 403
    assert client.get("/users/").status_code == 403
    assert client.get(f"/t/{domain.a.id}/audit/").status_code == 403
    assert client.get(f"/api/v1/t/{domain.a.id}/audit/").json()["count"] == 0


def test_draft_is_not_visible_and_private_dependency_not_leaked(domain, client):
    with tenant_context(domain.a.id):
        draft = Recommendation.objects.create(
            tenant=domain.a,
            category=domain.category,
            title="SECRET-DRAFT",
            justification="Private",
            editorial_status="draft",
        )
        RecommendationDependency.objects.create(
            tenant=domain.a, recommendation=domain.rec_a, prerequisite=draft
        )
    client.force_login(domain.customer)
    assert client.get(f"/api/v1/t/{domain.a.id}/recommendations/{draft.id}/").status_code == 404
    for path in [
        f"/t/{domain.a.id}/",
        f"/t/{domain.a.id}/roadmap/",
        f"/t/{domain.a.id}/recommendations/{domain.rec_a.id}/",
        f"/api/v1/t/{domain.a.id}/dependencies/",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"SECRET-DRAFT" not in response.content
    assert (
        client.get(f"/api/v1/t/{domain.a.id}/recommendations/{domain.rec_a.id}/").json()["blocked"]
        is True
    )


def test_api_rejects_tenant_and_protected_status_writes(domain, client):
    client.force_login(domain.admin)
    endpoint = f"/api/v1/t/{domain.a.id}/recommendations/{domain.rec_a.id}/"
    for data in (
        {"tenant": str(domain.b.id)},
        {"status": "done"},
        {"source": "AI"},
        {"completed_on": "2026-01-01"},
    ):
        response = client.patch(endpoint, json.dumps(data), content_type="application/json")
        assert response.status_code == 400, response.content
    assert (
        client.post(
            f"/api/v1/t/{domain.a.id}/dependencies/",
            {"recommendation": str(domain.rec_a.id), "prerequisite": str(domain.rec_b.id)},
        ).status_code
        == 400
    )


def test_api_new_resource_and_scoped_relationships(domain, client):
    typ = ResourceType.objects.create(name="DNS")
    client.force_login(domain.admin)
    response = client.post(
        f"/api/v1/t/{domain.a.id}/resources/",
        json.dumps(
            {
                "type": typ.pk,
                "name": "DNS local",
                "observed_at": timezone.now().isoformat(),
                "published": True,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    with tenant_context(domain.a.id):
        assert Resource.objects.get().name == "DNS local"
    with tenant_context(domain.b.id):
        assert Resource.objects.count() == 0


def test_inactive_tenant_blocked(domain, client):
    Tenant.objects.filter(pk=domain.a.pk).update(active=False)
    client.force_login(domain.customer)
    assert client.get(f"/t/{domain.a.id}/").status_code == 404


def test_session_csrf_required_for_writes(domain):
    browser = Browser(enforce_csrf_checks=True)
    browser.force_login(domain.admin)
    response = browser.post(f"/api/v1/t/{domain.a.id}/recommendations/", {"title": "No CSRF"})
    assert response.status_code == 403
    assert browser.get("/accounts/logout/").status_code == 405


def test_brute_force_limited_persistently(domain, client):
    for _ in range(8):
        response = client.post("/accounts/login/", {"username": "admin", "password": "wrong"})
        assert response.status_code == 200
    assert (
        client.post("/accounts/login/", {"username": "admin", "password": "wrong"}).status_code
        == 429
    )


def test_external_links_reject_javascript(domain):
    from apps.external_links.models import ExternalLink

    with tenant_context(domain.a.id), pytest.raises(ValidationError):
        ExternalLink.objects.create(tenant=domain.a, title="Unsafe", url="javascript:alert(1)")


def test_authentication_required(domain, client):
    assert client.get("/").status_code == 302
    assert client.get(f"/api/v1/t/{domain.a.id}/resources/").status_code == 403
    assert client.get("/api/v1/tenants/").status_code == 403
    assert client.get("/api/schema/").status_code == 403
