from apps.portal import api, views
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
for name, serializer in api.RESOURCE_SERIALIZERS.items():
    viewset = type(
        f"{serializer.Meta.model.__name__}ViewSet",
        (api.ScopedViewSet,),
        {"serializer_class": serializer},
    )
    router.register(name, viewset, basename=name)
router.register("recommendations", api.RecommendationViewSet, basename="recommendations")
router.register("assessments", api.AssessmentViewSet, basename="assessments")
router.register("dependencies", api.DependencyViewSet, basename="dependencies")
router.register("audit", api.AuditViewSet, basename="audit-api")
global_router = DefaultRouter()
global_router.register("tenants", api.TenantViewSet, basename="tenants")
global_router.register("assessment-categories", api.CategoryViewSet, basename="categories")

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("clients/new/", views.client_create, name="client-create"),
    path("clients/import-netbackup/", views.netbackup_import, name="netbackup-import"),
    path("users/", views.users, name="users"),
    path("users/new/", views.user_edit, name="user-create"),
    path("users/<int:object_id>/", views.user_edit, name="user-edit"),
    path("t/<uuid:tenant_id>/", include("apps.portal.urls")),
    path("api/v1/", include(global_router.urls)),
    path("api/v1/t/<uuid:tenant_id>/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
]
