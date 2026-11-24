from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "companies"

    def ready(self):
        from . import signals  # noqa: F401  (connects the post_save receiver)
