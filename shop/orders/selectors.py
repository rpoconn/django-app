"""Read-side queries (practice item 3).

Each pair below has a deliberately slow version and a fixed version. Open the
Debug Toolbar's SQL panel on /orders/demo/slow/ vs /orders/demo/fast/ and
compare query counts. tests/test_queries.py pins the counts.

Rule of thumb:
  * select_related   -> forward FK / OneToOne. Adds a JOIN, still one query.
  * prefetch_related -> reverse FK / M2M (anything that is "many"). Runs a
    second query with ``WHERE id IN (...)`` and stitches results in Python.
  * Prefetch(queryset=...) -> customise the inner query, e.g. to add a
    select_related on the "many" side.
"""

from django.db.models import Prefetch
from django.db.models import QuerySet

from .models import Order
from .models import OrderItem
from .models import Product


def orders_with_items_slow() -> QuerySet[Order]:
    """1 query for orders, then for EACH order: 1 for user, 1 for items,
    and 1 per item for the product. That is the N+1 (really 1 + N*(2+M))."""
    return Order.objects.all()


def orders_with_items_fast() -> QuerySet[Order]:
    """2 queries total no matter how many orders:
    orders JOIN users, then items JOIN products WHERE order_id IN (...)."""
    return Order.objects.select_related("user").prefetch_related(
        Prefetch(
            "items",
            queryset=OrderItem.objects.select_related("product").order_by("pk"),
        ),
    )


def products_with_category_slow() -> QuerySet[Product]:
    return Product.objects.all()


def products_with_category_fast() -> QuerySet[Product]:
    return Product.objects.select_related("category")


def orders_for_user(user) -> QuerySet[Order]:
    """What the API uses: a user's own orders, already fully loaded."""
    return orders_with_items_fast().filter(user=user)
