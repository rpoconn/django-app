"""DRF views (practice items 2 and 6).

Notice how little is here: validation goes through a serializer, the real work
goes through ``services``, and the view only translates domain exceptions into
HTTP responses.
"""

from rest_framework import mixins
from rest_framework import permissions
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from shop.orders import selectors
from shop.orders import services
from shop.orders.exceptions import OrderError
from shop.orders.models import Product

from .permissions import IsOwner
from .serializers import OrderSerializer
from .serializers import PlaceOrderSerializer
from .serializers import ProductSerializer


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Public catalogue: anyone can list and retrieve active products."""

    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    queryset = Product.objects.filter(is_active=True).select_related("category")
    search_fields = ["sku", "name"]
    ordering_fields = ["price", "name"]


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """A user's own orders. Create via POST, cancel via POST /{id}/cancel/."""

    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        # selectors.orders_for_user already does select_related/prefetch_related,
        # so serialising a page of orders is 2 queries, not 2 + N*M.
        return selectors.orders_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = services.place_order(
                user=request.user,
                lines=serializer.to_order_lines(),
            )
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except Product.DoesNotExist as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Re-read through the selector so the response uses the same
        # prefetching as list/retrieve.
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            services.cancel_order(order=order)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data)
