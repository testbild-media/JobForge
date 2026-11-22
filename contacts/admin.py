from django.contrib import admin

from .models import Address, Contact, ContactPerson


class PersonInline(admin.TabularInline):
    model = ContactPerson
    extra = 0


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "contact_type", "city", "email", "active"]
    list_filter = ["contact_type", "active"]
    search_fields = ["number", "company_name", "last_name", "email"]
    inlines = [PersonInline, AddressInline]
