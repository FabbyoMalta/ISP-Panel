"""Chat history for the AI assistant (OpenRouter) — see
apps.ai_assist.services for the actual OpenRouter call/tool-dispatch
logic. Both models are append-only: a conversation is a transcript, not
an editable record — see admin.py's read-only registration.
"""

from django.db import models

from apps.tenancy.models import TenantModel


class AIConversation(TenantModel):
    title = models.CharField("Título", max_length=180, blank=True)
    # Nullable: a conversation could outlive the assessment it started
    # from, or (not built yet) exist without one — but in practice
    # services.ensure_open_assessment() always sets this on creation.
    assessment = models.ForeignKey(
        "assessments.Assessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Conversa {self.pk}"


class AIMessage(TenantModel):
    class Role(models.TextChoices):
        USER = "user", "Consultor"
        ASSISTANT = "assistant", "IA"
        TOOL = "tool", "Ação executada"

    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    # Populated only for role=TOOL — which tool ran and with what args,
    # kept structured so the template can render a distinct action card
    # instead of raw text ("✓ Respondido: ... → Atendido").
    tool_name = models.CharField(max_length=60, blank=True)
    tool_args = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
