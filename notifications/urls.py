from rest_framework.routers import SimpleRouter

from .views import NotificationViewSet

router = SimpleRouter()
router.register("me/notifications", NotificationViewSet, basename="my-notification")

urlpatterns = router.urls
