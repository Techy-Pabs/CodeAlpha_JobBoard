from django.urls import path

from .views import CompanyDetailView

app_name = "companies"

urlpatterns = [
    path("<int:pk>/", CompanyDetailView.as_view(), name="detail"),
]
