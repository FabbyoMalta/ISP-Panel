import pytest
from apps.assessments.models import Assessment, AssessmentItemDefinition
from apps.assessments.services import answer_assessment, publish_assessment, start_assessment
from apps.audit.models import AuditEntry
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.portal.services import save_record
from apps.recommendations.models import Recommendation
from apps.recommendations.services import add_dependency, transition
from apps.tenancy.context import tenant_context
from apps.timeline.models import Event
from django.core.exceptions import ValidationError
from django.utils import timezone

pytestmark = pytest.mark.django_db


def make_rec(domain, title):
    return Recommendation.objects.create(
        tenant=domain.a, title=title, category=domain.category, justification="Resiliência"
    )


def test_dependency_cycles_and_self_reference(domain):
    with tenant_context(domain.a.id):
        b, c = make_rec(domain, "B"), make_rec(domain, "C")
        add_dependency(domain.admin, domain.rec_a, b)
        add_dependency(domain.admin, b, c)
        with pytest.raises(ValidationError, match="ciclo"):
            add_dependency(domain.admin, c, domain.rec_a)
        with pytest.raises(ValidationError, match="si mesma"):
            add_dependency(domain.admin, c, c)


def test_completion_unlock_and_reopening_protection(domain):
    with tenant_context(domain.a.id):
        child = make_rec(domain, "BGP")
        add_dependency(domain.admin, child, domain.rec_a)
        for status in ["in_progress", "done"]:
            with pytest.raises(ValidationError, match="pré-requisitos"):
                transition(domain.admin, child, status)
        transition(domain.admin, domain.rec_a, "done")
        transition(domain.admin, domain.rec_a, "done")
        assert Event.objects.filter(recommendation=domain.rec_a).count() == 1
        child.refresh_from_db()
        assert child.status == "recommended"
        transition(domain.admin, child, "in_progress")
        with pytest.raises(ValidationError, match="dependentes"):
            transition(domain.admin, domain.rec_a, "planned")
        assert AuditEntry.objects.filter(action="status_changed").count() == 2


def test_na_does_not_satisfy_dependency_and_manual_block_needs_resolution(domain):
    with tenant_context(domain.a.id):
        child = make_rec(domain, "IPv6")
        add_dependency(domain.admin, child, domain.rec_a)
        transition(domain.admin, domain.rec_a, "na", "Cenário não requer ASN")
        with pytest.raises(ValidationError):
            transition(domain.admin, child, "done")
        with pytest.raises(ValidationError):
            transition(domain.admin, child, "blocked")
        transition(domain.admin, child, "blocked", "Aguardando orçamento")
        transition(domain.admin, domain.rec_a, "done")
        with pytest.raises(ValidationError, match="manual"):
            transition(domain.admin, child, "in_progress")
        transition(domain.admin, child, "planned")
        transition(domain.admin, child, "done")


def test_weighted_maturity_and_published_history(domain):
    with tenant_context(domain.a.id):
        obj = start_assessment(domain.admin, "Baseline", timezone.localdate(), domain.template)
        with pytest.raises(ValidationError, match="todos"):
            publish_assessment(domain.admin, obj)
        answer_assessment(domain.admin, obj, str(domain.item1.pk), "met")
        answer_assessment(domain.admin, obj, str(domain.item2.pk), "partial")
        published = publish_assessment(domain.admin, obj)
        assert published.result["areas"][0]["score"] == 62  # Python rounding of 62.5
        assert published.result["level"] == "Essencial"
        AssessmentItemDefinition.objects.filter(pk=domain.item1.pk).update(
            weight=20, title="Changed"
        )
        assert published.template.snapshot["items"][0]["title"] == "Backups"
        with pytest.raises(ValidationError, match="publicada"):
            answer_assessment(domain.admin, published, str(domain.item1.pk), "unmet")
        published.title = "Overwrite history"
        with pytest.raises(ValidationError, match="imutáveis"):
            save_record(domain.admin, published)
        assert Assessment.objects.get(pk=obj.pk).title == "Baseline"


def test_all_na_is_not_full_maturity(domain):
    with tenant_context(domain.a.id):
        obj = start_assessment(domain.admin, "NA", timezone.localdate(), domain.template)
        with pytest.raises(ValidationError):
            answer_assessment(domain.admin, obj, str(domain.item1.pk), "na")
        for item in [domain.item1, domain.item2]:
            answer_assessment(domain.admin, obj, str(item.pk), "na", "Não aplicável neste cenário")
        obj = publish_assessment(domain.admin, obj)
        assert obj.result["areas"][0]["score"] is None
        assert obj.result["level"] == "Em desenvolvimento"
        assert obj.result["pending"] == ["Backups"]


def test_metrics_require_assumptions_and_preserve_observations(domain):
    definition = MetricDefinition.objects.create(key="capacity", name="Capacidade", unit="Gbps")
    with tenant_context(domain.a.id):
        obj = MetricObservation(
            tenant=domain.a,
            definition=definition,
            value="6",
            observed_at=timezone.now(),
            author=domain.admin,
            estimated=True,
        )
        with pytest.raises(ValidationError):
            obj.save()
        obj.assumptions = "Perfil de uso verificado"
        obj.save()
        obj.value = 8
        with pytest.raises(ValidationError, match="históricas"):
            obj.save()


def test_audit_tracks_change_and_is_not_client_visible(domain):
    with tenant_context(domain.a.id):
        domain.rec_a.title = "Second upstream"
        save_record(domain.admin, domain.rec_a)
        entry = AuditEntry.objects.get()
        assert entry.actor == domain.admin
        assert entry.changes["title"]["before"] == "Melhoria ISP Alpha"
        assert entry.changes["title"]["after"] == "Second upstream"
