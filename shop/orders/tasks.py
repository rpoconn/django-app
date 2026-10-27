"""Celery tasks (practice item 5).

Keep tasks tiny: load what you need by id, do the side effect, return. Never
pass model instances as task arguments; they get serialised to JSON and go
stale.
"""

from celery import shared_task
from django.core.mail import send_mail

from .models import Order


@shared_task(
    autoretry_for=(Order.DoesNotExist,),
    retry_backoff=True,
    max_retries=3,
)
def send_order_confirmation_email(order_id: int) -> str:
    # select_related / prefetch_related matter here too: the email body walks
    # the order -> items -> product graph.
    order = (
        Order.objects.select_related("user")
        .prefetch_related("items__product")
        .get(pk=order_id)
    )

    lines = "\n".join(
        f"  {item.quantity} x {item.product.name} "
        f"@ {item.unit_price} = {item.line_total}"
        for item in order.items.all()
    )
    body = f"Thanks for your order #{order.pk}.\n\n{lines}\n\nTotal: {order.total}\n"

    send_mail(
        subject=f"Order #{order.pk} confirmed",
        message=body,
        from_email=None,  # falls back to DEFAULT_FROM_EMAIL
        recipient_list=[order.user.email],
    )
    return f"sent order {order.pk} confirmation to {order.user.email}"
