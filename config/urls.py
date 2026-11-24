from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import MyProfileView

from .views import health

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="swagger-ui", permanent=False), name="root"),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/me/profile/", MyProfileView.as_view(), name="my-profile"),
    path("api/companies/", include("companies.urls")),
    path("api/", include("jobs.urls")),
    path("api/", include("candidates.urls")),
    path("api/", include("applications.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

# Resumes are private: they are never served from a public /media/ URL, even
# in development. They are only sent by /api/resumes/{id}/download/, which
# checks who is asking.
