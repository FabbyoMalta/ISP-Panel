import pytest
from apps.assessments.services import answer_assessment, publish_assessment, start_assessment
from apps.recommendations.models import RecommendationDependency
from apps.tenancy.context import tenant_context
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires real PostgreSQL"),
]


def assume_runtime():
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='isp_test_runtime') THEN CREATE ROLE isp_test_runtime NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        cursor.execute("GRANT USAGE ON SCHEMA public TO isp_test_runtime")
        cursor.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO isp_test_runtime"
        )
        cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO isp_test_runtime")
        cursor.execute("SET LOCAL ROLE isp_test_runtime")


def test_rls_filters_raw_sql_and_no_context_denies(domain):
    with transaction.atomic():
        assume_runtime()
        with connection.cursor() as cursor:
            cursor.execute("SELECT title FROM recommendations_recommendation")
            assert cursor.fetchall() == []
        with tenant_context(domain.a.pk), connection.cursor() as cursor:
            cursor.execute("SELECT title FROM recommendations_recommendation")
            assert cursor.fetchall() == [(domain.rec_a.title,)]
            cursor.execute(
                "UPDATE recommendations_recommendation SET title=%s WHERE id=%s",
                ["BAD", domain.rec_b.pk],
            )
            assert cursor.rowcount == 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM recommendations_recommendation")
            assert cursor.fetchone()[0] == 0
            cursor.execute("RESET ROLE")


def test_rls_rejects_foreign_tenant_insert(domain):
    with transaction.atomic():
        assume_runtime()
        with (
            tenant_context(domain.a.pk),
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO clients_clientcontact(id,tenant_id,name,position,email,phone,created_at,updated_at) VALUES(gen_random_uuid(),%s,'HACK','','','',now(),now())",
                [domain.b.pk],
            )
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def test_composite_fk_rejects_raw_cross_tenant_relationship(domain):
    # Owner/superuser bypassing RLS still cannot violate tenant referential integrity.
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO recommendations_recommendationdependency(id,tenant_id,recommendation_id,prerequisite_id,created_at,updated_at) VALUES(gen_random_uuid(),%s,%s,%s,now(),now())",
            [domain.a.pk, domain.rec_a.pk, domain.rec_b.pk],
        )


def test_database_preserves_published_history_and_audit(domain):
    with tenant_context(domain.a.pk):
        assessment = start_assessment(
            domain.admin, "Published", timezone.localdate(), domain.template
        )
        for item in [domain.item1, domain.item2]:
            answer_assessment(domain.admin, assessment, str(item.pk), "met")
        publish_assessment(domain.admin, assessment)
        for statement, params in [
            ("UPDATE assessments_assessment SET title=%s WHERE id=%s", ["Changed", assessment.pk]),
            ("DELETE FROM assessments_assessmentanswer WHERE assessment_id=%s", [assessment.pk]),
            (
                "UPDATE assessments_assessmenttemplateversion SET name=%s WHERE id=%s",
                ["Changed", domain.template.pk],
            ),
            ("DELETE FROM audit_auditentry WHERE tenant_id=%s", [domain.a.pk]),
        ]:
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(statement, params)


@pytest.mark.django_db(transaction=True)
def test_concurrent_opposing_dependencies_cannot_create_cycle(domain):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from apps.recommendations.models import Recommendation
    from apps.recommendations.services import add_dependency
    from django.core.exceptions import ValidationError
    from django.db import close_old_connections

    with tenant_context(domain.a.pk):
        second = Recommendation.objects.create(
            tenant=domain.a,
            title="Concurrent B",
            category=domain.category,
            justification="Concurrency",
        )
    barrier = Barrier(2)

    def attempt(left, right):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with tenant_context(domain.a.pk):
                add_dependency(domain.admin, left, right)
            return "created"
        except ValidationError:
            return "rejected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda pair: attempt(*pair), [(domain.rec_a, second), (second, domain.rec_a)])
        )
    assert sorted(results) == ["created", "rejected"]
    with tenant_context(domain.a.pk):
        assert RecommendationDependency.objects.count() == 1
