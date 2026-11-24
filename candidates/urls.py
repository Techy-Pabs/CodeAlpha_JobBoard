from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import MyResumeViewSet, ResumeDownloadView

router = SimpleRouter()
router.register("me/resumes", MyResumeViewSet, basename="my-resume")

urlpatterns = [
    *router.urls,
    path("resumes/<int:pk>/download/", ResumeDownloadView.as_view(), name="resume-download"),
]
