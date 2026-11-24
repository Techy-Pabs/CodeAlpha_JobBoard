from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "employer",
        "status",
        "job_type",
        "work_mode",
        "experience_level",
        "location",
        "closes_at",
        "created_at",
    )
    list_filter = ("status", "job_type", "work_mode", "experience_level")
    search_fields = ("title", "description", "skills", "location", "employer__company_name")
    raw_id_fields = ("employer",)
    date_hierarchy = "created_at"
