from django.contrib import admin

from .models import Application, ApplicationStatusChange


class StatusChangeInline(admin.TabularInline):
    """The application's history, oldest first. Read-only: history is a record."""

    model = ApplicationStatusChange
    extra = 0
    fields = ("created_at", "from_status", "to_status", "changed_by", "note")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("job", "candidate", "status", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("job__title", "candidate__user__username", "candidate__user__email")
    raw_id_fields = ("job", "candidate", "resume")
    list_select_related = ("job", "candidate__user")
    inlines = [StatusChangeInline]


@admin.register(ApplicationStatusChange)
class ApplicationStatusChangeAdmin(admin.ModelAdmin):
    list_display = ("application", "from_status", "to_status", "changed_by", "created_at")
    list_filter = ("to_status", "created_at")
    search_fields = ("application__job__title", "changed_by__username", "note")
    raw_id_fields = ("application", "changed_by")
