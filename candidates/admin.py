from django.contrib import admin

from .models import CandidateProfile, Resume


class ResumeInline(admin.TabularInline):
    model = Resume
    extra = 0
    fields = ("original_filename", "file", "size_bytes", "is_default", "uploaded_at")
    readonly_fields = ("uploaded_at",)


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "headline", "location", "created_at")
    list_filter = ("location",)
    search_fields = ("user__username", "user__email", "headline", "skills")
    raw_id_fields = ("user",)
    inlines = [ResumeInline]


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "candidate", "size_bytes", "is_default", "uploaded_at")
    list_filter = ("is_default", "uploaded_at")
    search_fields = ("original_filename", "candidate__user__username")
    raw_id_fields = ("candidate",)
