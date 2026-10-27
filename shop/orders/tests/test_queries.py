"""Practice item 3: pin query counts so the N+1 can't sneak back in.

``django_assert_num_queries`` (pytest-django) fails if the exact number of SQL
statements differs, and prints them all. ``django_assert_max_num_queries`` is
the looser cousin for when you only care about an upper bound.

Run with ``-s`` and ``--ds`` as usual; to *see* the queries, add
``-o log_cli=true`` or just read the assertion failure output.
"""

import pytest

from shop.orders import selectors

from .factories import OrderFactory
from .factories import ProductFactory

pytestmark = pytest.mark.django_db


def _walk_orders(qs):
    """Touch every relation the template touches."""
    return [
        (o.user.email, [(i.quantity, i.product.name) for i in o.items.all()])
        for o in qs
    ]


def _walk_products(qs):
    return [(p.name, p.category.name) for p in qs]


class TestOrdersWithItems:
    @pytest.fixture
    def five_orders(self):
        for _ in range(5):
            OrderFactory(items=2)

    def test_slow_version_is_n_plus_one(self, five_orders, django_assert_num_queries):
        # 1 (orders) + 5 orders * (1 user + 1 items + 2 products) = 21
        with django_assert_num_queries(21):
            _walk_orders(selectors.orders_with_items_slow())

    def test_fast_version_is_constant(self, five_orders, django_assert_num_queries):
        # 1 (orders JOIN users) + 1 (items JOIN products WHERE order_id IN ...)
        with django_assert_num_queries(2):
            _walk_orders(selectors.orders_with_items_fast())

    def test_fast_version_stays_constant_as_data_grows(self, django_assert_num_queries):
        for _ in range(15):
            OrderFactory(items=3)
        with django_assert_num_queries(2):
            _walk_orders(selectors.orders_with_items_fast())


class TestProductsWithCategory:
    def test_slow(self, django_assert_num_queries):
        ProductFactory.create_batch(4)
        with django_assert_num_queries(1 + 4):
            _walk_products(selectors.products_with_category_slow())

    def test_fast(self, django_assert_num_queries):
        ProductFactory.create_batch(4)
        with django_assert_num_queries(1):
            _walk_products(selectors.products_with_category_fast())
