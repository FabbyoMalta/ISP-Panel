import re

import pytest
from apps.assessments.services import start_assessment
from apps.tenancy.context import tenant_context
from apps.tenancy.models import TenantMembership
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "roadmap/",
        "assessments/",
        "data/resources/",
        "data/risks/",
        "data/metrics/",
        "data/events/",
        "data/links/",
        "data/client/",
        "data/contacts/",
        "audit/",
    ],
)
def test_admin_pages_render(domain, client, suffix):
    client.force_login(domain.admin)
    response = client.get(f"/t/{domain.a.id}/{suffix}")
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize(
    "section",
    [
        "resources",
        "risks",
        "metrics",
        "events",
        "links",
        "contacts",
        "recommendations",
        "roadmap",
        "risk-links",
    ],
)
def test_forms_render(domain, client, section):
    client.force_login(domain.admin)
    assert client.get(f"/t/{domain.a.id}/data/{section}/new/").status_code == 200


def test_assessment_answer_and_publish_ui(domain, client):
    client.force_login(domain.admin)
    with tenant_context(domain.a.id):
        obj = start_assessment(domain.admin, "UI assessment", timezone.localdate(), domain.template)
    url = f"/t/{domain.a.id}/assessments/{obj.pk}/"
    assert client.get(url).status_code == 200
    for item in [domain.item1, domain.item2]:
        assert (
            client.post(
                url, {"item_key": str(item.pk), "status": "met", "comment": "Verified"}
            ).status_code
            == 302
        )
    assert client.post(url, {"action": "publish"}).status_code == 302
    client.force_login(domain.customer)
    response = client.get(url)
    assert response.status_code == 200
    assert "Publicada" in response.content.decode()


def test_user_creation_and_membership(domain, client):
    client.force_login(domain.admin)
    response = client.post(
        "/users/new/",
        {
            "username": "new-client",
            "email": "new@example.test",
            "role": "client",
            "is_active": "on",
            "password": "Very-secure-fixture-82!",
            "tenants": [str(domain.a.id)],
        },
    )
    assert response.status_code == 302, response.content
    user = get_user_model().objects.get(username="new-client")
    assert user.check_password("Very-secure-fixture-82!")
    assert not user.is_staff
    assert TenantMembership.objects.filter(user=user, tenant=domain.a).exists()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_is_one_time(domain, client):
    response = client.post("/accounts/password_reset/", {"email": domain.customer.email})
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    link = re.search(r"http://testserver(/accounts/reset/[^\s]+)", mail.outbox[0].body).group(1)
    response = client.get(link)
    set_password_url = response["Location"]
    response = client.post(
        set_password_url,
        {
            "new_password1": "Updated-strong-password-63!",
            "new_password2": "Updated-strong-password-63!",
        },
    )
    assert response.status_code == 302
    domain.customer.refresh_from_db()
    assert domain.customer.check_password("Updated-strong-password-63!")
    response = client.get(link)
    assert "expirou" in response.content.decode()


def test_nonexistent_transition_is_404(domain, client):
    client.force_login(domain.admin)
    response = client.post(
        f"/api/v1/t/{domain.a.id}/recommendations/{domain.rec_b.pk}/transition/", {"status": "done"}
    )
    assert response.status_code == 404


def test_roadmap_form_resolves_current_tenant_choices(domain, client):
    client.force_login(domain.admin)
    response = client.post(
        f"/t/{domain.a.id}/data/roadmap/new/",
        {"recommendation": str(domain.rec_a.pk), "horizon": "now", "order": 0},
    )
    assert response.status_code == 302, response.content
    with tenant_context(domain.a.pk):
        assert domain.rec_a.placement.horizon == "now"


def test_removing_dependency_is_audited_even_without_changed_fields(domain, client):
    from apps.audit.models import AuditEntry
    from apps.recommendations.models import Recommendation
    from apps.recommendations.services import add_dependency

    client.force_login(domain.admin)
    with tenant_context(domain.a.pk):
        other = Recommendation.objects.create(
            tenant=domain.a, category=domain.category, title="Pré-requisito", justification="Teste"
        )
        edge = add_dependency(domain.admin, domain.rec_a, other)
    response = client.post(
        f"/t/{domain.a.pk}/recommendations/{domain.rec_a.pk}/",
        {"action": "remove_dependency", "dependency": str(edge.pk)},
    )
    assert response.status_code == 302
    with tenant_context(domain.a.pk):
        assert not domain.rec_a.dependencies.exists()
        assert AuditEntry.objects.filter(action="dependency_removed").exists()
