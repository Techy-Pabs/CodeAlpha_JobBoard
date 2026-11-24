from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = BaseUserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    # is_staff is on the add form too: without it Django's form validation
    # skips the user_role_required_unless_staff check (the check uses is_staff)
    # and a missing role would reach the database as a 500 instead of a form error.
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("Role", {"fields": ("role", "is_staff")}),)
