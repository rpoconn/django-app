"""DRF serializers (practice item 6).

Two kinds:

* read serializers (``ProductSerializer``, ``OrderSerializer``) mirror the
  model for output;
* a write serializer (``PlaceOrderSerializer``) validates *input* only and
  hands clean data to the service. It is not a ModelSerializer on purpose:
  the shape of "place an order" is not the shape of an Order row.
"""

from rest_framework import serializers

from shop.orders.models import Order
from shop.orders.models import OrderItem
from shop.orders.models import Product
from shop.orders.services import OrderLine


class ProductSerializer(serializers.ModelSerializer[Product]):
    category = serializers.StringRelatedField()

    class Meta:
        model = Product
        fields = ["id", "sku", "name", "category", "price", "stock", "is_active"]
        read_only_fields = fields


class OrderItemSerializer(serializers.ModelSerializer[OrderItem]):
    # These two fields read product.* -- cheap only if the view's queryset
    # already did select_related("product") inside the Prefetch.
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = ["product_id", "product_name", "quantity", "unit_price", "line_total"]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer[Order]):
    items = OrderItemSerializer(many=True, read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Order
        fields = ["id", "user_email", "status", "total", "created_at", "items"]
        read_only_fields = fields


class OrderLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class PlaceOrderSerializer(serializers.Serializer):
    lines = OrderLineInputSerializer(many=True, allow_empty=False)

    def to_order_lines(self) -> list[OrderLine]:
        """Convert validated input into the service's plain input type."""
        return [OrderLine(**line) for line in self.validated_data["lines"]]
