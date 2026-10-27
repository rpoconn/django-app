"""Business logic for orders (practice items 2, 4, 5).

Views and API endpoints call these functions and do nothing else. Keeping the
logic here means:

* it is reusable from the HTML view, the DRF view, the admin, a management
  command, or a Celery task;
* it can be unit-tested without an HTTP client;
* transaction boundaries are explicit and in one place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from .exceptions import EmptyOrderError
from .exceptions import InactiveProductError
from .exceptions import OutOfStockError
from .models import Order
from .models import OrderItem
from .models import Product
from .tasks import send_order_confirmation_email

if TYPE_CHECKING:
    from collections.abc import Iterable

    from shop.users.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderLine:
    """Plain input to the service, decoupled from serializers and forms."""

    product_id: int
    quantity: int


def place_order(*, user: User, lines: Iterable[OrderLine]) -> Order:
    """Create an order and decrement stock atomically.

    Concurrency story (practice item 4):

    * ``transaction.atomic()`` makes "create order + create items + decrement
      stock" all-or-nothing. If anything raises, nothing is written.
    * ``select_for_update()`` takes a row-level lock on the Product rows for
      the lifetime of the transaction. Two requests for the last unit of a
      product will serialise: the second one blocks until the first commits,
      then re-reads ``stock`` and sees 0, so it fails instead of going negative.
    * ``order_by("pk")`` locks rows in a consistent order, which avoids
      deadlocks when two orders contain the same products in a different order.
    * A plain ``product.stock -= qty`` is safe here *because* we hold the lock.
      Without the lock you would need ``F("stock") - qty`` plus a check
      constraint, and you still could not reliably tell the caller "sold out".

    Side effects (practice item 5):

    * The confirmation email is queued with ``transaction.on_commit``. If we
      called ``.delay()`` inside the atomic block, the worker could pick the
      task up before the transaction commits and fail with
      ``Order.DoesNotExist`` (or, worse, email about an order that was rolled
      back).
    """
    lines = list(lines)
    if not lines:
        msg = "An order needs at least one line."
        raise EmptyOrderError(msg)

    # Merge duplicate product ids so the UniqueConstraint on OrderItem holds.
    wanted: dict[int, int] = {}
    for line in lines:
        if line.quantity < 1:
            msg = f"Quantity must be >= 1 for product {line.product_id}."
            raise ValueError(msg)
        wanted[line.product_id] = wanted.get(line.product_id, 0) + line.quantity

    with transaction.atomic():
        products = (
            Product.objects.select_for_update().filter(pk__in=wanted).order_by("pk")
        )
        by_id = {p.pk: p for p in products}

        missing = set(wanted) - set(by_id)
        if missing:
            msg = f"Unknown product id(s): {sorted(missing)}"
            raise Product.DoesNotExist(msg)

        order = Order.objects.create(user=user, total=Decimal("0.00"))
        items: list[OrderItem] = []
        total = Decimal("0.00")

        for product_id, qty in wanted.items():
            product = by_id[product_id]
            if not product.is_active:
                raise InactiveProductError(product.sku)
            if product.stock < qty:
                raise OutOfStockError(product, qty)

            product.stock -= qty
            total += product.price * qty
            items.append(
                OrderItem(
                    order=order,
                    product=product,
                    quantity=qty,
                    unit_price=product.price,
                ),
            )

        Product.objects.bulk_update(by_id.values(), ["stock"])
        OrderItem.objects.bulk_create(items)
        order.total = total
        order.save(update_fields=["total"])

        transaction.on_commit(lambda: send_order_confirmation_email.delay(order.pk))

    logger.info("order placed", extra={"order_id": order.pk, "user_id": user.pk})
    return order


def cancel_order(*, order: Order) -> Order:
    """Cancel a pending order and return its stock. Same locking pattern."""
    with transaction.atomic():
        # Re-fetch with a lock so two concurrent cancels can't double-restock.
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.PENDING:
            msg = f"Only pending orders can be cancelled (got {order.status})."
            raise ValueError(msg)

        items = list(order.items.order_by("product_id"))
        product_ids = [i.product_id for i in items]
        # Lock the products too (consistent pk order, same as place_order).
        locked = {
            p.pk: p
            for p in Product.objects.select_for_update()
            .filter(pk__in=product_ids)
            .order_by("pk")
        }
        for item in items:
            locked[item.product_id].stock += item.quantity
        Product.objects.bulk_update(locked.values(), ["stock"])

        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status"])
    return order
