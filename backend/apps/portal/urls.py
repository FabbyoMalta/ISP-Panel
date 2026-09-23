from django.urls import path

from . import views

urlpatterns = [
    path("", views.overview, name="dashboard"),
    path("roadmap/", views.roadmap, name="roadmap"),
    path(
        "recommendations/<uuid:object_id>/",
        views.recommendation_detail,
        name="recommendation-detail",
    ),
    path("assessments/", views.assessments, name="assessments"),
    path("assessments/new/", views.assessment_create, name="assessment-create"),
    path("assessments/<uuid:object_id>/", views.assessment_detail, name="assessment-detail"),
    path("audit/", views.audit, name="audit"),
    path("deactivate/", views.tenant_toggle, name="tenant-deactivate"),
    path("data/<slug:section>/", views.collection, name="collection"),
    path("data/<slug:section>/new/", views.edit_record, name="record-create"),
    path("data/<slug:section>/<uuid:object_id>/edit/", views.edit_record, name="record-edit"),
]
