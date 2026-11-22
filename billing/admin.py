from django.contrib import admin

from .models import Document, DocumentLayout, DocumentPosition, Payment


class PositionInline(admin.TabularInline):
    model = DocumentPosition
    extra = 0


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["number", "doc_type", "date", "customer", "status"]
    list_filter = ["doc_type", "status"]
    search_fields = ["number", "subject"]
    inlines = [PositionInline]


admin.site.register([Payment, DocumentLayout])
