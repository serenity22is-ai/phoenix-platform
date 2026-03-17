"""
Payment Adapters — Concrete implementations for each payment processor.

Each adapter translates ANASTASiA's unified payment interface into
processor-specific API calls. ANASTASiA never replaces the customer's
payment system — it adapts to it.

MYSTES KYRIOS LLC — Confidential.
"""

from .adyen_adapter import AdyenAdapter
from .braintree_adapter import BraintreeAdapter
from .paypal_adapter import PayPalAdapter
from .square_adapter import SquareAdapter
from .stripe_adapter import StripeAdapter

__all__ = [
    "AdyenAdapter",
    "BraintreeAdapter",
    "PayPalAdapter",
    "SquareAdapter",
    "StripeAdapter",
]
