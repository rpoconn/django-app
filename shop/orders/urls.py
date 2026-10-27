from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("demo/slow/", views.orders_demo_slow, name="demo-slow"),
    path("demo/fast/", views.orders_demo_fast, name="demo-fast"),
]
