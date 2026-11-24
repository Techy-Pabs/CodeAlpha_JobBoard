from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ApplicationViewSet, MyApplicationsView

router = SimpleRouter()
router.register("applications", ApplicationViewSet, basename="application")

urlpatterns = [
    path("me/applications/", MyApplicationsView.as_view(), name="my-applications"),
    *router.urls,
]
