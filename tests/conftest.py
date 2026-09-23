import os
from types import SimpleNamespace

os.environ.setdefault("TESTING", "true")

import pytest
from apps.assessments.models import (
    AssessmentCategory,
    AssessmentItemDefinition,
    MaturityLevel,
    MaturityRule,
)
from apps.assessments.services import publish_catalog
from apps.clients.models import Client
from apps.recommendations.models import Recommendation
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant, TenantMembership
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def domain(db):
    User = get_user_model()
    admin = User.objects.create_user(
        "admin",
        email="admin@example.test",
        password="Secure-test-secret-72!",
        role="admin",
        is_staff=True,
    )
    customer = User.objects.create_user(
        "client", email="client@example.test", password="Secure-test-secret-72!"
    )
    other_user = User.objects.create_user(
        "other", email="other@example.test", password="Secure-test-secret-72!"
    )
    a = Tenant.objects.create(name="ISP Alpha", slug="alpha")
    b = Tenant.objects.create(name="ISP Bravo", slug="bravo")
    TenantMembership.objects.create(tenant=a, user=customer)
    TenantMembership.objects.create(tenant=b, user=other_user)
    category = AssessmentCategory.objects.create(name="Rede")
    item1 = AssessmentItemDefinition.objects.create(category=category, title="Backups", weight=1)
    item2 = AssessmentItemDefinition.objects.create(
        category=category, title="Redundância", weight=3
    )
    level = MaturityLevel.objects.create(name="Essencial", order=1)
    MaturityRule.objects.create(level=level, item=item1)
    template = publish_catalog(admin)
    recs = []
    for tenant in (a, b):
        with tenant_context(tenant.pk):
            Client.objects.create(
                tenant=tenant,
                legal_name=tenant.name,
                trade_name=tenant.name,
                joined_on=timezone.localdate(),
                internal_notes="CONFIDENTIAL-INTERNAL",
            )
            recs.append(
                Recommendation.objects.create(
                    tenant=tenant,
                    title=f"Melhoria {tenant.name}",
                    category=category,
                    justification="Reduzir risco",
                    editorial_status="published",
                    internal_notes="CONFIDENTIAL-INTERNAL",
                )
            )
    return SimpleNamespace(
        admin=admin,
        customer=customer,
        other_user=other_user,
        a=a,
        b=b,
        category=category,
        item1=item1,
        item2=item2,
        template=template,
        rec_a=recs[0],
        rec_b=recs[1],
    )
