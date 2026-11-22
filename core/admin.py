from django.contrib import admin

from .models import (Attachment, AuditLog, CompanySettings, CustomFieldDefinition, Note, NumberSequence, PaymentTerm,
                     TaxRate, Webhook, WebhookDelivery)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user", "action", "object_repr", "message"]
    list_filter = ["action"]
    search_fields = ["object_repr", "message"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register([CompanySettings, NumberSequence, TaxRate, PaymentTerm, CustomFieldDefinition, Webhook,
                     WebhookDelivery, Note, Attachment])
