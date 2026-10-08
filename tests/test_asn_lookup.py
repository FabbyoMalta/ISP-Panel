"""Tests for apps.inventory.services.lookup_asn (RDAP) and the manual,
consultant-only view that surfaces it. httpx.get is mocked directly —
no real network — same approach as test_integrations_sync.py.
"""

import httpx
import pytest
from apps.inventory import services
from apps.inventory.models import Resource, ResourceType
from apps.tenancy.context import tenant_context
from django.utils import timezone

pytestmark = pytest.mark.django_db


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        return self._payload


RDAP_PAYLOAD = {
    "handle": "AS12345",
    "name": "EXAMPLE-AS",
    "country": "BR",
    "status": ["active"],
    "entities": [{"vcardArray": ["vcard", [["fn", {}, "text", "Example Org Ltda"]]]}],
    "events": [{"eventAction": "registration", "eventDate": "2010-01-01T00:00:00Z"}],
}


def test_lookup_asn_parses_org_name_and_registration_date(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(RDAP_PAYLOAD))
    result = services.lookup_asn("12345")
    assert result["org_name"] == "Example Org Ltda"
    assert result["country"] == "BR"
    assert result["registered_on"] == "2010-01-01T00:00:00Z"


def test_lookup_asn_rejects_non_numeric_input():
    with pytest.raises(ValueError):
        services.lookup_asn("not-a-number")


def test_lookup_asn_propagates_http_errors(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse({}, status_code=404))
    with pytest.raises(httpx.HTTPError):
        services.lookup_asn("12345")


def test_view_shows_lookup_result_for_resource_with_asn_attribute(domain, client, monkeypatch):
    monkeypatch.setattr(services, "lookup_asn", lambda asn: {**RDAP_PAYLOAD, "org_name": "X"})
    resource_type = ResourceType.objects.create(name="Upstream", attribute_keys=["asn"])
    with tenant_context(domain.a.pk):
        resource = Resource.objects.create(
            tenant=domain.a,
            type=resource_type,
            name="Plena",
            observed_at=timezone.now(),
            attributes={"asn": "12345"},
        )
    client.force_login(domain.admin)
    response = client.get(f"/t/{domain.a.id}/data/resources/{resource.id}/whois/")
    assert response.status_code == 200
    assert "<dd>X</dd>" in response.content.decode()


def test_view_shows_error_when_resource_has_no_asn_attribute(domain, client):
    resource_type = ResourceType.objects.create(name="Servidor", attribute_keys=["funcao"])
    with tenant_context(domain.a.pk):
        resource = Resource.objects.create(
            tenant=domain.a, type=resource_type, name="DNS-01", observed_at=timezone.now()
        )
    client.force_login(domain.admin)
    response = client.get(f"/t/{domain.a.id}/data/resources/{resource.id}/whois/")
    assert response.status_code == 200
    assert "não tem um número de ASN" in response.content.decode()
