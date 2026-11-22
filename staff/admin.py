from django.contrib import admin

from .models import Assignment, Availability, Employee, Qualification, TimeEntry


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["number", "first_name", "last_name", "kind", "active"]
    search_fields = ["first_name", "last_name", "email"]
    filter_horizontal = ["qualifications"]


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "employee", "job", "start_time", "end_time", "approved", "billed"]
    list_filter = ["approved", "billed", "employee"]


admin.site.register([Qualification, Availability, Assignment])
