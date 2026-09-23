import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import SecurityEvent
from apps.assessments.models import Assessment
from apps.assessments.services import answer_assessment, publish_assessment, start_assessment
from apps.audit.models import AuditEntry
from apps.clients.models import Client
from apps.recommendations.models import Recommendation, RecommendationDependency
from apps.recommendations.services import add_dependency, remove_dependency, transition
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant, TenantMembership

from .forms import (
    FORMS,
    AnswerForm,
    AssessmentEditForm,
    AssessmentForm,
    DependencyForm,
    TenantForm,
    TransitionForm,
    UserForm,
)
from .selectors import dashboard, roadmap_rows
from .services import check_metric, require_consultant, save_record, visible

LABELS = {
    "client": "Dados da empresa",
    "contacts": "Contatos",
    "resources": "Infraestrutura",
    "risks": "Riscos técnicos",
    "recommendations": "Recomendações",
    "metrics": "Capacidade e métricas",
    "events": "Evolução",
    "links": "Ferramentas",
    "roadmap": "Organizar roadmap",
    "risk-links": "Tratamento de riscos",
}


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    tenants = Tenant.objects.filter(active=True)
    if not request.user.is_consultant:
        tenants = tenants.filter(tenantmembership__user=request.user)
        if tenants.count() == 1:
            return redirect("dashboard", tenant_id=tenants.first().pk)
    query = request.GET.get("q", "").strip()
    if query:
        tenants = tenants.filter(name__icontains=query)
    return render(
        request,
        "portal/home.html",
        {"tenants": tenants.order_by("name"), "query": query, "page_title": "Carteira de clientes"},
    )


@login_required
def client_create(request):
    require_consultant(request.user)
    form = TenantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            data = form.cleaned_data
            tenant = Tenant.objects.create(name=data["name"], slug=data["slug"])
            with tenant_context(tenant.pk):
                save_record(
                    request.user,
                    Client(
                        tenant=tenant,
                        legal_name=data["legal_name"],
                        trade_name=data["name"],
                        region=data["region"],
                        joined_on=data["joined_on"],
                    ),
                )
        messages.success(request, "Cliente cadastrado. Comece pelo inventário e pela avaliação.")
        return redirect("dashboard", tenant_id=tenant.pk)
    return render(request, "portal/form.html", {"form": form, "page_title": "Novo cliente"})


@login_required
def overview(request, tenant_id):
    context = dashboard(request.user)
    context.update(
        {
            "page_title": "Visão geral",
            "profile": Client.objects.first(),
            "today": timezone.localdate(),
        }
    )
    return render(request, "portal/dashboard.html", context)


@login_required
def collection(request, tenant_id, section):
    if section not in FORMS:
        raise Http404
    if section in ("roadmap", "risk-links"):
        require_consultant(request.user)
    model = FORMS[section]._meta.model
    qs = visible(model.objects.all(), request.user).order_by("-created_at")
    history, definitions, selected_metric = [], [], ""
    if section == "metrics":
        from apps.metrics.models import MetricDefinition

        definitions = MetricDefinition.objects.all().order_by("name")
        selected_metric = request.GET.get("metric", "peak-gbps")
        qs = (
            qs.filter(definition__key=selected_metric)
            .select_related("definition")
            .order_by("-observed_at")
        )
        recent = list(qs[:60])
        history = [
            {
                "date": row.observed_at.strftime("%d/%m/%Y"),
                "value": float(row.value),
                "unit": row.definition.unit,
            }
            for row in reversed(recent)
        ]
    from django.core.paginator import Paginator

    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "portal/collection.html",
        {
            "objects": page,
            "section": section,
            "page_title": LABELS[section],
            "history": history,
            "definitions": definitions,
            "selected_metric": selected_metric,
        },
    )


@login_required
def edit_record(request, tenant_id, section, object_id=None):
    require_consultant(request.user)
    if section not in FORMS:
        raise Http404
    form_class = FORMS[section]
    obj = (
        get_object_or_404(form_class._meta.model.objects, pk=object_id)
        if object_id
        else form_class._meta.model(tenant=request.tenant)
    )
    if section == "metrics":
        obj.author = request.user
    form = form_class(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            obj = form.save(commit=False)
            if section == "metrics":
                check_metric(obj)
                if object_id:
                    raise ValidationError("Métricas são históricas. Registre uma nova observação.")
            save_record(request.user, obj)
            messages.success(request, "Registro salvo.")
            return redirect("collection", tenant_id=tenant_id, section=section)
        except ValidationError as error:
            form.add_error(None, error.messages)
    return render(
        request,
        "portal/form.html",
        {
            "form": form,
            "page_title": f"{'Editar' if object_id else 'Adicionar'} · {LABELS[section]}",
        },
    )


@login_required
def roadmap(request, tenant_id):
    return render(
        request,
        "portal/roadmap.html",
        {"rows": roadmap_rows(request.user), "page_title": "Roadmap técnico"},
    )


@login_required
def recommendation_detail(request, tenant_id, object_id):
    obj = get_object_or_404(visible(Recommendation.objects.all(), request.user), pk=object_id)
    transition_form = TransitionForm(initial={"status": obj.status})
    dependency_form = DependencyForm(recommendation=obj)
    if request.method == "POST":
        require_consultant(request.user)
        action = request.POST.get("action")
        try:
            if action == "transition":
                transition_form = TransitionForm(request.POST)
                if transition_form.is_valid():
                    transition(request.user, obj, **transition_form.cleaned_data)
                else:
                    raise ValidationError("Informe um estado válido.")
            elif action == "dependency":
                dependency_form = DependencyForm(request.POST, recommendation=obj)
                if dependency_form.is_valid():
                    add_dependency(request.user, obj, dependency_form.cleaned_data["prerequisite"])
                else:
                    raise ValidationError("Selecione uma melhoria deste cliente.")
            elif action == "remove_dependency":
                edge = get_object_or_404(
                    RecommendationDependency.objects,
                    pk=request.POST.get("dependency"),
                    recommendation=obj,
                )
                remove_dependency(request.user, edge)
            else:
                raise ValidationError("Ação inválida.")
            messages.success(request, "Roadmap atualizado.")
            return redirect(request.path)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    dependencies = visible(obj.dependencies.all(), request.user).select_related("prerequisite")
    return render(
        request,
        "portal/recommendation.html",
        {
            "item": obj,
            "dependencies": dependencies,
            "has_private_dependency": obj.dependencies.count() > dependencies.count(),
            "transition_form": transition_form,
            "dependency_form": dependency_form,
            "page_title": obj.title,
        },
    )


@login_required
def assessments(request, tenant_id):
    return render(
        request,
        "portal/assessments.html",
        {
            "objects": visible(Assessment.objects.all(), request.user).order_by(
                "-assessed_on", "-created_at"
            ),
            "page_title": "Avaliações técnicas",
        },
    )


@login_required
def assessment_create(request, tenant_id):
    require_consultant(request.user)
    form = AssessmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = start_assessment(request.user, **form.cleaned_data)
        return redirect("assessment-detail", tenant_id=tenant_id, object_id=obj.pk)
    return render(request, "portal/form.html", {"form": form, "page_title": "Nova avaliação"})


@login_required
def assessment_detail(request, tenant_id, object_id):
    obj = get_object_or_404(visible(Assessment.objects.all(), request.user), pk=object_id)
    if request.method == "POST":
        require_consultant(request.user)
        try:
            if request.POST.get("action") == "publish":
                publish_assessment(request.user, obj)
            elif request.POST.get("action") == "edit":
                form = AssessmentEditForm(request.POST, instance=obj)
                if not form.is_valid():
                    raise ValidationError(str(form.errors.as_text()))
                save_record(request.user, form.save(commit=False))
            else:
                form = AnswerForm(request.POST)
                if not form.is_valid():
                    raise ValidationError("Informe uma situação válida para o critério.")
                answer_assessment(
                    request.user, obj, request.POST.get("item_key"), **form.cleaned_data
                )
            messages.success(request, "Avaliação atualizada.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect(request.path)
    answers = {answer.item_key: answer for answer in obj.answers.all()}
    rows = []
    for definition in obj.template.snapshot["items"]:
        answer = answers.get(definition["key"])
        rows.append(
            {
                "definition": definition,
                "answer": answer,
                "form": AnswerForm(
                    initial={
                        "status": answer.status,
                        "comment": answer.comment,
                        "internal_notes": answer.internal_notes,
                    }
                    if answer
                    else None,
                    auto_id=f"id_{definition['key']}_%s",
                ),
            }
        )
    return render(
        request,
        "portal/assessment.html",
        {
            "item": obj,
            "rows": rows,
            "edit_form": AssessmentEditForm(instance=obj),
            "page_title": obj.title,
        },
    )


@login_required
def audit(request, tenant_id):
    require_consultant(request.user)
    from django.core.paginator import Paginator

    page = Paginator(AuditEntry.objects.select_related("actor"), 50).get_page(
        request.GET.get("page")
    )
    return render(request, "portal/audit.html", {"objects": page, "page_title": "Auditoria"})


@login_required
def users(request):
    if not request.user.is_administrator:
        raise PermissionDenied
    return render(
        request,
        "portal/users.html",
        {
            "objects": get_user_model().objects.order_by("username"),
            "page_title": "Usuários e acesso",
        },
    )


@login_required
def user_edit(request, object_id=None):
    if not request.user.is_administrator:
        raise PermissionDenied
    obj = get_object_or_404(get_user_model(), pk=object_id) if object_id else get_user_model()()
    if obj.is_superuser and not request.user.is_superuser:
        raise PermissionDenied
    form = UserForm(
        request.POST or None,
        instance=obj,
        initial={"tenants": Tenant.objects.filter(tenantmembership__user=obj)}
        if object_id
        else None,
    )
    if request.method == "POST" and form.is_valid():
        if obj.pk == request.user.pk and (
            not form.cleaned_data["is_active"] or form.cleaned_data["role"] != request.user.role
        ):
            form.add_error(None, "Não altere seu próprio papel ou acesso nesta tela.")
        else:
            with transaction.atomic():
                user = form.save(commit=False)
                password = form.cleaned_data["password"]
                invite = not object_id and not password
                if password or invite:
                    user.set_password(password or secrets.token_urlsafe(40))
                user.is_staff = user.role == "admin" or user.is_superuser
                user.save()
                TenantMembership.objects.filter(user=user).delete()
                if user.role == "client":
                    for tenant in form.cleaned_data["tenants"]:
                        TenantMembership.objects.create(user=user, tenant=tenant)
                SecurityEvent.objects.create(
                    actor=request.user,
                    action="user_updated" if object_id else "user_created",
                    object_id=str(user.pk),
                    details={
                        "role": user.role,
                        "active": user.is_active,
                        "tenants": [str(t.pk) for t in form.cleaned_data["tenants"]],
                        "password_changed": bool(password or invite),
                    },
                )
            if invite:
                reset = PasswordResetForm({"email": user.email})
                if reset.is_valid():
                    reset.save(request=request, use_https=request.is_secure())
            messages.success(
                request,
                "Usuário salvo."
                + (" Link de definição de senha enviado por e-mail." if invite else ""),
            )
            return redirect("users")
    return render(request, "portal/form.html", {"form": form, "page_title": "Gerenciar usuário"})


@require_POST
@login_required
def tenant_toggle(request, tenant_id):
    if not request.user.is_administrator:
        raise PermissionDenied
    request.tenant.active = False
    request.tenant.save(update_fields=["active"])
    SecurityEvent.objects.create(
        actor=request.user, action="tenant_deactivated", object_id=str(tenant_id)
    )
    return redirect("home")


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
