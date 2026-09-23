from django.db.models import Case, IntegerField, Value, When

from apps.assessments.models import Assessment
from apps.inventory.models import Resource
from apps.metrics.models import MetricObservation
from apps.recommendations.models import Recommendation
from apps.risks.models import Risk
from apps.timeline.models import Event

from .services import visible


def priority_order(field="priority"):
    return Case(
        *[
            When(**{field: key}, then=Value(index))
            for index, key in enumerate(["critical", "high", "medium", "low"])
        ],
        output_field=IntegerField(),
    )


def roadmap_rows(user, by_priority=False):
    qs = (
        visible(Recommendation.objects.all(), user)
        .select_related("category", "placement")
        .prefetch_related("dependencies__prerequisite")
    )
    if by_priority:
        qs = qs.order_by(priority_order(), "recommended_on", "title")
    else:
        horizon_order = Case(
            When(placement__horizon="now", then=Value(0)),
            When(placement__horizon="next", then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
        qs = qs.order_by(horizon_order, "placement__order", priority_order(), "title")
    rows = []
    for recommendation in qs:
        pending = [
            edge for edge in recommendation.dependencies.all() if edge.prerequisite.status != "done"
        ]
        visible_pending = [
            edge.prerequisite.title
            for edge in pending
            if user.is_consultant or edge.prerequisite.editorial_status == "published"
        ]
        rows.append(
            {
                "item": recommendation,
                "blocked": bool(pending) or recommendation.status == "blocked",
                "dependencies": visible_pending,
                "has_private_dependency": len(visible_pending) < len(pending),
            }
        )
    return rows


def dashboard(user):
    observations = visible(MetricObservation.objects.all(), user).select_related("definition")
    latest = {}
    for observation in observations:
        latest.setdefault(observation.definition.key, observation)
    subscribers = latest.get("active-subscribers")
    estimated = latest.get("estimated-subscribers")
    peak = latest.get("peak-gbps")
    capacity = latest.get("capacity-gbps")
    usage = (
        round(100 * peak.value / capacity.value, 1)
        if peak and capacity and capacity.value
        else None
    )
    assessments = (
        visible(Assessment.objects.filter(published_at__isnull=False), user)
        .select_related("template")
        .order_by("-assessed_on", "-published_at")
    )
    resources = visible(Resource.objects.all(), user).select_related("type")
    rows = roadmap_rows(user, by_priority=True)
    return {
        "subscribers": subscribers,
        "estimated": estimated,
        "peak": peak,
        "capacity": capacity,
        "usage": usage,
        "usage_bar": min(100, usage or 0),
        "metrics": latest,
        "assessment": assessments.first(),
        "resources": resources,
        "risks": visible(Risk.objects.filter(status="open"), user).order_by(
            priority_order("severity"), "title"
        )[:5],
        "next_steps": [
            row for row in rows if row["item"].status not in ("done", "na") and not row["blocked"]
        ][:4],
        "blocked_count": sum(
            row["blocked"] for row in rows if row["item"].status not in ("done", "na")
        ),
        "completed_count": sum(row["item"].status == "done" for row in rows),
        "events": visible(Event.objects.all(), user)[:6],
        "asn": resources.filter(type__name="ASN").first(),
        "ipv6": resources.filter(type__name="IPv6").first(),
        "upstreams": resources.filter(type__name="Upstream", status="active").count(),
    }
