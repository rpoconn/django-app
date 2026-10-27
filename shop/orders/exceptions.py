class OrderError(Exception):
    """Base class for domain errors raised by the orders service layer."""


class OutOfStockError(OrderError):
    def __init__(self, product, requested: int) -> None:
        self.product = product
        self.requested = requested
        super().__init__(
            f"Not enough stock for {product.sku}: "
            f"requested {requested}, available {product.stock}",
        )


class InactiveProductError(OrderError):
    pass


class EmptyOrderError(OrderError):
    pass
