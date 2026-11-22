from django.contrib import admin

from .models import Appointment, Job, JobPosition, JobStatus, Project, Task


class PositionInline(admin.TabularInline):
    model = JobPosition
    extra = 0


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["number", "title", "customer", "status", "start", "end", "is_template"]
    list_filter = ["status", "is_template"]
    search_fields = ["number", "title"]
    inlines = [PositionInline]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "customer", "status", "is_template"]
    search_fields = ["number", "name"]


admin.site.register([JobStatus, Task, Appointment])
