from django.http import HttpResponseForbidden, HttpResponseNotFound
from django.urls import resolve

from .context import tenant_context
from .models import Tenant, TenantMembership


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        match = resolve(request.path_info)
        tenant_id = match.kwargs.get("tenant_id")
        if not tenant_id:
            return self.get_response(request)
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Autenticação necessária.")
        tenant = Tenant.objects.filter(pk=tenant_id, active=True).first()
        if not tenant or (
            not request.user.is_consultant
            and not TenantMembership.objects.filter(
                tenant=tenant,
                user=request.user,
            ).exists()
        ):
            return HttpResponseNotFound("Cliente não encontrado.")
        request.tenant = tenant
        with tenant_context(tenant.id):
            return self.get_response(request)
