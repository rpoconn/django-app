from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from shop.orders.api.views import OrderViewSet
from shop.orders.api.views import ProductViewSet
from shop.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)
router.register("products", ProductViewSet, basename="product")
router.register("orders", OrderViewSet, basename="order")


app_name = "api"
urlpatterns = router.urls
