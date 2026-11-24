from django.contrib import admin
from django.db import models

from .models import EmployerProfile


@admin.register(EmployerProfile)
class EmployerProfileAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "location", "website", "created_at")
    list_filter = ("location",)
    search_fields = ("company_name", "user__username", "user__email", "location")
    raw_id_fields = ("user",)
    # A website typed without a scheme becomes https:// (Django 6's default).
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}
