"""Practice item 6 (and 7): the DRF API through APIClient.

Covers serializers (shape of responses), permissions (anon / owner / other
user), pagination (page + page_size), and that the view delegates to the
service (stock really changes, errors map to the right status codes).
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from shop.orders.models import Order
from shop.users.tests.factories import UserFactory

from .factories import OrderFactory
from .factories import ProductFactory

pytestmark = pytest.mark.django_db

# cookiecutter-django sets DATABASES["default"]["ATOMIC_REQUESTS"] = True, so
# every request is wrapped in a transaction. Inside a test (itself already in
# a transaction) that shows up as SAVEPOINT + RELEASE SAVEPOINT: two extra
# statements per request that have nothing to do with our queries.
ATOMIC_REQUEST_OVERHEAD = 2


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestProductsEndpoint:
    def test_anonymous_can_list_active_products(self, api_client):
        ProductFactory.create_batch(3)
        ProductFactory(is_active=False)

        resp = api_client.get(reverse("api:product-list"))

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 3
        assert set(resp.data["results"][0]) == {
            "id",
            "sku",
            "name",
            "category",
            "price",
            "stock",
            "is_active",
        }

    def test_pagination(self, api_client):
        ProductFactory.create_batch(7)

        resp = api_client.get(reverse("api:product-list"), {"page_size": 3})
        assert len(resp.data["results"]) == 3
        assert resp.data["next"] is not None

        resp = api_client.get(reverse("api:product-list"), {"page_size": 3, "page": 3})
        assert len(resp.data["results"]) == 1
        assert resp.data["next"] is None

    def test_search(self, api_client):
        ProductFactory(name="Burr grinder")
        ProductFactory(name="Stoneware mug")
        resp = api_client.get(reverse("api:product-list"), {"search": "grinder"})
        assert [p["name"] for p in resp.data["results"]] == ["Burr grinder"]

    def test_list_is_two_queries_regardless_of_size(
        self,
        api_client,
        django_assert_num_queries,
    ):
        ProductFactory.create_batch(10)
        # 1 COUNT(*) for pagination + 1 SELECT ... JOIN category
        with django_assert_num_queries(2 + ATOMIC_REQUEST_OVERHEAD):
            api_client.get(reverse("api:product-list"))


class TestOrdersEndpoint:
    def test_requires_authentication(self, api_client):
        resp = api_client.get(reverse("api:order-list"))
        # 403 rather than 401: DRF answers 401 only when the FIRST authentication
        # class provides a WWW-Authenticate header. SessionAuthentication (first
        # in REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]) does not, so an
        # anonymous request is "forbidden" rather than "unauthorised". Put
        # TokenAuthentication first if you want 401s.
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_place_order(self, auth_client, user):
        product = ProductFactory(price=Decimal("4.00"), stock=10)

        resp = auth_client.post(
            reverse("api:order-list"),
            {"lines": [{"product_id": product.pk, "quantity": 3}]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["user_email"] == user.email
        assert resp.data["status"] == "pending"
        assert resp.data["total"] == "12.00"
        assert resp.data["items"] == [
            {
                "product_id": product.pk,
                "product_name": product.name,
                "quantity": 3,
                "unit_price": "4.00",
                "line_total": "12.00",
            },
        ]
        product.refresh_from_db()
        assert product.stock == 7

    def test_validation_errors_are_400(self, auth_client):
        resp = auth_client.post(reverse("api:order-list"), {"lines": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "lines" in resp.data

        resp = auth_client.post(
            reverse("api:order-list"),
            {"lines": [{"product_id": 1, "quantity": 0}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_out_of_stock_is_409(self, auth_client):
        product = ProductFactory(stock=1)
        resp = auth_client.post(
            reverse("api:order-list"),
            {"lines": [{"product_id": product.pk, "quantity": 2}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert "Not enough stock" in resp.data["detail"]
        assert Order.objects.count() == 0

    def test_unknown_product_is_400(self, auth_client):
        resp = auth_client.post(
            reverse("api:order-list"),
            {"lines": [{"product_id": 424242, "quantity": 1}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_user_only_sees_own_orders(self, auth_client, user):
        mine = OrderFactory(user=user, items=1)
        theirs = OrderFactory(user=UserFactory(), items=1)

        resp = auth_client.get(reverse("api:order-list"))
        assert [o["id"] for o in resp.data["results"]] == [mine.pk]

        resp = auth_client.get(reverse("api:order-detail", kwargs={"pk": theirs.pk}))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_query_count_is_constant(
        self,
        auth_client,
        user,
        django_assert_num_queries,
    ):
        for _ in range(6):
            OrderFactory(user=user, items=3)
        # 1 COUNT + 1 orders JOIN users + 1 items JOIN products
        with django_assert_num_queries(3 + ATOMIC_REQUEST_OVERHEAD):
            resp = auth_client.get(reverse("api:order-list"))
        assert resp.data["count"] == 6

    def test_cancel(self, auth_client, user):
        product = ProductFactory(stock=5)
        resp = auth_client.post(
            reverse("api:order-list"),
            {"lines": [{"product_id": product.pk, "quantity": 2}]},
            format="json",
        )
        order_id = resp.data["id"]

        resp = auth_client.post(reverse("api:order-cancel", kwargs={"pk": order_id}))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] == "cancelled"
        product.refresh_from_db()
        assert product.stock == 5

        resp = auth_client.post(reverse("api:order-cancel", kwargs={"pk": order_id}))
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_cannot_cancel_someone_elses_order(self, auth_client):
        theirs = OrderFactory(user=UserFactory(), items=1)
        resp = auth_client.post(reverse("api:order-cancel", kwargs={"pk": theirs.pk}))
        assert resp.status_code == status.HTTP_404_NOT_FOUND
