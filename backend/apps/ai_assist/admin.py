from django.contrib import admin

from apps.accounts.admin import SecurityEventAdmin

from .models import AIConversation, AIMessage


@admin.register(AIConversation)
class AIConversationAdmin(SecurityEventAdmin):
    list_display = ["title", "tenant", "assessment", "started_at"]
    list_filter = ["tenant"]
    readonly_fields = ["tenant", "title", "assessment", "started_at"]


@admin.register(AIMessage)
class AIMessageAdmin(SecurityEventAdmin):
    list_display = ["conversation", "role", "tool_name", "created_at"]
    list_filter = ["role"]
    readonly_fields = [
        "tenant",
        "conversation",
        "role",
        "content",
        "tool_name",
        "tool_args",
        "created_at",
    ]
