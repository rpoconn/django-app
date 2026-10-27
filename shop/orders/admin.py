from django.contrib import admin

from .models import Category
from .models import Order
from .models import OrderItem
from .models import Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "price", "stock", "is_active"]
    list_filter = ["category", "is_active"]
    list_select_related = ["category"]  # avoids N+1 in the changelist
    search_fields = ["sku", "name"]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ["product"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "total", "created_at"]
    list_filter = ["status"]
    list_select_related = ["user"]
    inlines = [OrderItemInline]
