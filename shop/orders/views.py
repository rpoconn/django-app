"""HTML views are thin: pick a queryset from selectors, render a template.

/orders/demo/slow/ and /orders/demo/fast/ render the same page; the only
difference is which selector they use. Compare them in django-debug-toolbar.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import selectors


@login_required
def orders_demo_slow(request):
    orders = selectors.orders_with_items_slow()[:20]
    return render(
        request,
        "orders/order_list.html",
        {"orders": orders, "mode": "slow (N+1)"},
    )


@login_required
def orders_demo_fast(request):
    orders = selectors.orders_with_items_fast()[:20]
    return render(request, "orders/order_list.html", {"orders": orders, "mode": "fast"})
