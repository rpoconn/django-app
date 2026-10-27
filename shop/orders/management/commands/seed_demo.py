"""Create demo data so the N+1 demo pages and API have something to show.

Usage:  python manage.py seed_demo [--orders 30]
"""

import random

from django.core.management.base import BaseCommand

from shop.orders.models import Category
from shop.orders.models import Product
from shop.orders.services import OrderLine
from shop.orders.services import place_order
from shop.users.models import User

CATALOGUE = {
    "Coffee": [
        ("ESP-250", "Espresso beans 250g", "9.50"),
        ("FLT-1K", "Filter blend 1kg", "24.00"),
    ],
    "Tea": [("EGR-100", "Earl Grey 100g", "6.25"), ("SEN-100", "Sencha 100g", "8.75")],
    "Gear": [("MUG-01", "Stoneware mug", "12.00"), ("GRD-01", "Burr grinder", "89.00")],
}


class Command(BaseCommand):
    help = "Seed categories, products, a demo user and some orders."

    def add_arguments(self, parser):
        parser.add_argument("--orders", type=int, default=30)

    def handle(self, *args, **options):
        products = []
        for cat_name, items in CATALOGUE.items():
            category, _ = Category.objects.get_or_create(name=cat_name)
            for sku, name, price in items:
                product, _ = Product.objects.update_or_create(
                    sku=sku,
                    defaults={
                        "name": name,
                        "category": category,
                        "price": price,
                        "stock": 10_000,
                    },
                )
                products.append(product)

        user, created = User.objects.get_or_create(
            email="demo@example.com",
            defaults={"name": "Demo User"},
        )
        if created:
            user.set_password("demo-password")
            user.save()

        rng = random.Random(42)  # noqa: S311 - demo data, not security
        for _ in range(options["orders"]):
            chosen = rng.sample(products, k=rng.randint(1, 3))
            lines = [
                OrderLine(product_id=p.pk, quantity=rng.randint(1, 4)) for p in chosen
            ]
            place_order(user=user, lines=lines)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(products)} products and {options['orders']} orders for "
                f"demo@example.com / demo-password",
            ),
        )
