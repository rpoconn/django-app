"""factory_boy factories (practice item 7).

Factories build valid objects with sensible defaults so each test only spells
out the fields it actually cares about.

* ``SubFactory``  -> create the FK target automatically.
* ``Sequence``    -> unique values (sku) across a test.
* ``Faker``       -> realistic noise for fields nobody asserts on.
* ``post_generation`` -> hang child objects off a parent (``OrderFactory(items=3)``).
"""

from decimal import Decimal

import factory
from factory import Faker
from factory import SubFactory
from factory.django import DjangoModelFactory

from shop.orders.models import Category
from shop.orders.models import Order
from shop.orders.models import OrderItem
from shop.orders.models import Product
from shop.users.tests.factories import UserFactory


class CategoryFactory(DjangoModelFactory[Category]):
    name = factory.Sequence(lambda n: f"Category {n}")

    class Meta:
        model = Category
        django_get_or_create = ["name"]


class ProductFactory(DjangoModelFactory[Product]):
    sku = factory.Sequence(lambda n: f"SKU-{n:05d}")
    name = Faker("catch_phrase")
    category = SubFactory(CategoryFactory)
    price = Decimal("10.00")
    stock = 100
    is_active = True

    class Meta:
        model = Product


class OrderFactory(DjangoModelFactory[Order]):
    user = SubFactory(UserFactory)
    status = Order.Status.PENDING
    total = Decimal("0.00")

    class Meta:
        model = Order
        skip_postgeneration_save = True

    @factory.post_generation
    def items(self, create, extracted, **kwargs):
        """``OrderFactory(items=3)`` creates three OrderItems with fresh products."""
        if not create or not extracted:
            return
        for _ in range(int(extracted)):
            OrderItemFactory(order=self)
        self.total = sum((i.line_total for i in self.items.all()), Decimal("0.00"))
        self.save(update_fields=["total"])


class OrderItemFactory(DjangoModelFactory[OrderItem]):
    order = SubFactory(OrderFactory)
    product = SubFactory(ProductFactory)
    quantity = 1
    unit_price = factory.LazyAttribute(lambda o: o.product.price)

    class Meta:
        model = OrderItem
