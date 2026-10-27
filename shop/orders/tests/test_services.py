"""Service-layer tests: items 2, 4, 5 and 7 together.

Things to notice:

* No HTTP client. Services are plain functions, so tests are plain calls.
* ``db`` fixture (from pytest-django) wraps each test in a transaction and
  rolls it back. Because of that, ``transaction.on_commit`` callbacks would
  never fire -- so we use ``django_capture_on_commit_callbacks`` to capture
  and run them deliberately.
* The concurrency test needs REAL transactions (two connections, a real
  commit), so it uses ``transactional_db`` instead of ``db``.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from unittest import mock

import pytest
from django.core import mail
from django.db import connection

from shop.orders.exceptions import EmptyOrderError
from shop.orders.exceptions import InactiveProductError
from shop.orders.exceptions import OutOfStockError
from shop.orders.models import Order
from shop.orders.models import Product
from shop.orders.services import OrderLine
from shop.orders.services import cancel_order
from shop.orders.services import place_order
from shop.users.tests.factories import UserFactory

from .factories import ProductFactory

pytestmark = pytest.mark.django_db


class TestPlaceOrder:
    def test_creates_order_items_and_decrements_stock(self, user):
        coffee = ProductFactory(price=Decimal("9.50"), stock=10)
        mug = ProductFactory(price=Decimal("12.00"), stock=3)

        order = place_order(
            user=user,
            lines=[OrderLine(coffee.pk, 2), OrderLine(mug.pk, 1)],
        )

        order.refresh_from_db()
        assert order.user == user
        assert order.status == Order.Status.PENDING
        assert order.total == Decimal("31.00")
        assert order.items.count() == 2

        coffee.refresh_from_db()
        mug.refresh_from_db()
        assert coffee.stock == 8
        assert mug.stock == 2

    def test_snapshots_unit_price(self, user):
        product = ProductFactory(price=Decimal("5.00"))
        order = place_order(user=user, lines=[OrderLine(product.pk, 1)])

        product.price = Decimal("99.00")
        product.save()

        item = order.items.get()
        assert item.unit_price == Decimal("5.00")

    def test_merges_duplicate_lines(self, user):
        product = ProductFactory(stock=10)
        order = place_order(
            user=user,
            lines=[OrderLine(product.pk, 1), OrderLine(product.pk, 2)],
        )
        assert order.items.get().quantity == 3

    def test_out_of_stock_rolls_back_everything(self, user):
        """Atomicity: a failure on the 2nd line must undo the 1st line's decrement
        AND the Order row itself."""
        plenty = ProductFactory(stock=10)
        scarce = ProductFactory(stock=1)

        with pytest.raises(OutOfStockError) as excinfo:
            place_order(
                user=user,
                lines=[OrderLine(plenty.pk, 5), OrderLine(scarce.pk, 2)],
            )

        assert excinfo.value.product == scarce
        assert Order.objects.count() == 0
        plenty.refresh_from_db()
        assert plenty.stock == 10  # not 5

    def test_inactive_product_rejected(self, user):
        product = ProductFactory(is_active=False)
        with pytest.raises(InactiveProductError):
            place_order(user=user, lines=[OrderLine(product.pk, 1)])

    def test_unknown_product_rejected(self, user):
        with pytest.raises(Product.DoesNotExist):
            place_order(user=user, lines=[OrderLine(999_999, 1)])

    def test_empty_order_rejected(self, user):
        with pytest.raises(EmptyOrderError):
            place_order(user=user, lines=[])


class TestOnCommitEmail:
    """Practice item 5: the Celery task is queued only after commit."""

    def test_task_is_not_queued_until_commit(
        self,
        user,
        django_capture_on_commit_callbacks,
    ):
        product = ProductFactory()
        with mock.patch(
            "shop.orders.services.send_order_confirmation_email.delay",
        ) as delay:
            # execute=False: callbacks are captured but NOT run, which is
            # exactly the state of the world between on_commit() and COMMIT.
            with django_capture_on_commit_callbacks(execute=False) as callbacks:
                place_order(user=user, lines=[OrderLine(product.pk, 1)])
            assert len(callbacks) == 1
            delay.assert_not_called()

            callbacks[0]()  # simulate the commit
            delay.assert_called_once()

    def test_email_sent_end_to_end(self, user, django_capture_on_commit_callbacks):
        """CELERY_TASK_ALWAYS_EAGER (settings/test.py) runs the task inline, so
        once the on_commit hook fires the email lands in mail.outbox."""
        product = ProductFactory(name="Burr grinder", price=Decimal("89.00"))

        with django_capture_on_commit_callbacks(execute=True):
            order = place_order(user=user, lines=[OrderLine(product.pk, 1)])

        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == [user.email]
        assert f"Order #{order.pk}" in msg.subject
        assert "1 x Burr grinder @ 89.00" in msg.body

    def test_no_email_when_order_fails(self, user, django_capture_on_commit_callbacks):
        product = ProductFactory(stock=0)
        with (
            django_capture_on_commit_callbacks(execute=True),
            pytest.raises(OutOfStockError),
        ):
            place_order(user=user, lines=[OrderLine(product.pk, 1)])
        assert mail.outbox == []


class TestCancelOrder:
    def test_restocks_and_marks_cancelled(self, user):
        product = ProductFactory(stock=5)
        order = place_order(user=user, lines=[OrderLine(product.pk, 3)])

        cancel_order(order=order)

        order.refresh_from_db()
        product.refresh_from_db()
        assert order.status == Order.Status.CANCELLED
        assert product.stock == 5

    def test_cannot_cancel_twice(self, user):
        product = ProductFactory(stock=5)
        order = place_order(user=user, lines=[OrderLine(product.pk, 1)])
        cancel_order(order=order)
        with pytest.raises(ValueError, match="Only pending"):
            cancel_order(order=order)


@pytest.mark.django_db(transaction=True)
class TestRaceCondition:
    """Practice item 4, for real.

    Two threads each try to buy the LAST unit. Each thread has its own DB
    connection, so both ``select_for_update`` calls hit Postgres concurrently.
    The lock serialises them: exactly one order succeeds, stock ends at 0,
    never -1.

    Try it yourself: delete ``.select_for_update()`` in services.place_order,
    rerun this test a few times, and watch it fail intermittently with
    stock == -1 or two successful orders. (PositiveIntegerField only adds a
    CHECK constraint, which would make the loser raise IntegrityError instead
    of OutOfStockError -- still not what you want.)
    """

    def test_only_one_of_two_concurrent_orders_succeeds(self):
        product = ProductFactory(stock=1)
        users = [UserFactory(), UserFactory()]
        results: list[str] = []
        barrier = threading.Barrier(2)

        def buy(user):
            try:
                barrier.wait(timeout=5)  # start at the same moment
                place_order(user=user, lines=[OrderLine(product.pk, 1)])
                results.append("ok")
            except OutOfStockError:
                results.append("out_of_stock")
            except Exception as exc:  # noqa: BLE001
                results.append(f"error: {exc!r}")
            finally:
                connection.close()  # each thread used its own connection; tidy up

        threads = [threading.Thread(target=buy, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sorted(results) == ["ok", "out_of_stock"]
        product.refresh_from_db()
        assert product.stock == 0
        assert Order.objects.count() == 1
