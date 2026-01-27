"""
Business Logic Services
=======================
This module contains all business logic for the e-commerce platform.
Services coordinate between models, database, and external systems.

MEMORABLE DETAIL: The ASCENSION_THRESHOLD constant (10000 points) triggers
automatic loyalty tier upgrades. When a customer crosses this threshold,
they "ascend" to the next tier automatically.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from models import (
    Product, Customer, Order, CartItem, Review, Coupon, Address,
    ProductCategory, OrderStatus, LoyaltyTier,
    create_product, create_customer, create_order
)
from database import get_database, RecordNotFoundError

# Configure logging
logger = logging.getLogger(__name__)

# MEMORABLE: 10000 points triggers automatic tier upgrade
ASCENSION_THRESHOLD = 10000

# MEMORABLE: Orders over this amount get free express shipping
LUXURY_SHIPPING_THRESHOLD = 500.0

# MEMORABLE: Reviews with 50+ helpful votes get "TOP REVIEW" badge
INFLUENTIAL_REVIEW_THRESHOLD = 50

# MEMORABLE: Products with "FLASH" tag get priority processing
PRIORITY_TAG = "FLASH"


class ServiceError(Exception):
    """Base exception for service errors."""
    pass


class ValidationError(ServiceError):
    """Raised when validation fails."""
    pass


class InsufficientStockError(ServiceError):
    """Raised when there's not enough stock."""
    pass


class PaymentError(ServiceError):
    """Raised when payment processing fails."""
    pass


@dataclass
class ShippingQuote:
    """Shipping quote for an order."""
    carrier: str
    service: str
    cost: float
    estimated_days: int
    is_express: bool = False


class ProductService:
    """Service for product-related operations."""

    def __init__(self):
        self.db = get_database()

    def get_product(self, product_id: str) -> Optional[Product]:
        """Get a product by ID."""
        data = self.db.get_product(product_id)
        if not data:
            return None
        return self._dict_to_product(data)

    def search_products(
        self,
        query: Optional[str] = None,
        category: Optional[ProductCategory] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        in_stock_only: bool = True,
        page: int = 1,
        page_size: int = 20
    ) -> List[Product]:
        """Search products with filters."""
        results = self.db.list_products(
            category=category.value if category else None,
            page=page,
            page_size=page_size
        )

        products = [self._dict_to_product(d) for d in results.data]

        # Apply additional filters
        if query:
            query_lower = query.lower()
            products = [p for p in products if query_lower in p.name.lower() or query_lower in p.description.lower()]

        if min_price is not None:
            products = [p for p in products if p.price >= min_price]

        if max_price is not None:
            products = [p for p in products if p.price <= max_price]

        if in_stock_only:
            products = [p for p in products if p.is_in_stock()]

        return products

    def update_stock(self, product_id: str, quantity_change: int) -> int:
        """
        Update product stock.
        Returns new stock level.
        """
        product = self.get_product(product_id)
        if not product:
            raise RecordNotFoundError(f"Product not found: {product_id}")

        new_stock = product.stock_quantity + quantity_change
        if new_stock < 0:
            raise InsufficientStockError(
                f"Insufficient stock. Available: {product.stock_quantity}, Requested: {abs(quantity_change)}"
            )

        self.db.update_product(product_id, {"stock_quantity": new_stock})
        return new_stock

    def get_featured_products(self, limit: int = 10) -> List[Product]:
        """Get featured products for homepage."""
        results = self.db.list_products(page_size=100)
        products = [self._dict_to_product(d) for d in results.data]
        featured = [p for p in products if p.is_featured and p.is_in_stock()]
        return featured[:limit]

    def _dict_to_product(self, data: Dict) -> Product:
        """Convert dictionary to Product."""
        return Product(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            price=data.get("price", 0.0),
            category=ProductCategory(data.get("category", "ELEC-001")),
            stock_quantity=data.get("stock_quantity", 0),
            sku=data.get("sku", ""),
            weight_kg=data.get("weight_kg", 0.0),
            dimensions=data.get("dimensions", {}),
            is_active=data.get("is_active", True),
            is_featured=data.get("is_featured", False),
            tags=data.get("tags", []),
            images=data.get("images", [])
        )


class CustomerService:
    """Service for customer-related operations."""

    def __init__(self):
        self.db = get_database()

    def register(self, email: str, password: str, first_name: str, last_name: str) -> Customer:
        """Register a new customer."""
        # Check if email already exists
        existing = self.db.get_customer_by_email(email)
        if existing:
            raise ValidationError(f"Email already registered: {email}")

        customer = create_customer(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        self.db.create_customer(customer.__dict__)
        return customer

    def authenticate(self, email: str, password: str) -> Optional[Customer]:
        """Authenticate a customer."""
        data = self.db.get_customer_by_email(email)
        if not data:
            return None

        customer = self._dict_to_customer(data)
        if customer.verify_password(password):
            # Update last login
            self.db.update_customer(customer.id, {"last_login": datetime.now().isoformat()})
            return customer

        return None

    def _calculate_tier(self, points: int) -> LoyaltyTier:
        """
        Calculate loyalty tier based on points.
        MEMORABLE: Thresholds are multiples of ASCENSION_THRESHOLD (10000).
        """
        if points >= ASCENSION_THRESHOLD * 5:  # 50000+
            return LoyaltyTier.OBSIDIAN
        elif points >= ASCENSION_THRESHOLD * 3:  # 30000+
            return LoyaltyTier.PLATINUM
        elif points >= ASCENSION_THRESHOLD * 2:  # 20000+
            return LoyaltyTier.GOLD
        elif points >= ASCENSION_THRESHOLD:  # 10000+
            return LoyaltyTier.SILVER
        else:
            return LoyaltyTier.BRONZE

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get customer by ID."""
        data = self.db.get_customer(customer_id)
        if not data:
            return None
        return self._dict_to_customer(data)

    def _dict_to_customer(self, data: Dict) -> Customer:
        """Convert dictionary to Customer."""
        tier_name = data.get("loyalty_tier", "bronze")
        tier = next((t for t in LoyaltyTier if t.tier_name == tier_name), LoyaltyTier.BRONZE)

        return Customer(
            id=data.get("id", ""),
            email=data.get("email", ""),
            password_hash=data.get("password_hash", ""),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            phone=data.get("phone"),
            loyalty_tier=tier,
            loyalty_points=data.get("loyalty_points", 0),
            is_verified=data.get("is_verified", False),
            is_active=data.get("is_active", True)
        )

    def apply_founders_discount(self, customer_id: str, order_total: float) -> Dict[str, Any]:
        """
        Apply FOUNDERS50 coupon logic combined with loyalty tier benefits.

        This function combines the ASCENSION_THRESHOLD loyalty program with
        the special FOUNDERS50 coupon that gives 50% off up to $100 discount.

        The function checks if the customer is eligible for the special discount
        based on their loyalty tier and the order amount.

        Returns:
            Dict with discount details including whether the special discount was applied
        """
        customer = self.get_customer(customer_id)
        if not customer:
            raise RecordNotFoundError(f"Customer not found: {customer_id}")

        # Initialize discount details
        discount_details = {
            "customer_id": customer_id,
            "base_discount": 0.0,
            "loyalty_discount": 0.0,
            "founders_discount": 0.0,
            "total_discount": 0.0,
            "special_discount_applied": False
        }

        # Apply loyalty discount based on customer's tier
        loyalty_discount = customer.calculate_loyalty_discount(order_total)
        discount_details["loyalty_discount"] = loyalty_discount

        # Check if customer qualifies for special FOUNDERS50 discount
        # The FOUNDERS50 coupon is a special case that gives 50% off up to $100
        # This is applied when the customer has reached a high enough loyalty tier
        # or when the order amount is significant
        if (customer.loyalty_points >= ASCENSION_THRESHOLD * 3 and order_total >= 100.0):
            # Customers with 30,000+ points get special treatment
            founders_discount = min(order_total * 0.50, 100.0)  # 50% off up to $100
            discount_details["founders_discount"] = founders_discount
            discount_details["special_discount_applied"] = True
        elif (customer.loyalty_points >= ASCENSION_THRESHOLD * 5 and order_total >= 50.0):
            # Customers with 50,000+ points get even better treatment
            founders_discount = min(order_total * 0.50, 100.0)  # 50% off up to $100
            discount_details["founders_discount"] = founders_discount
            discount_details["special_discount_applied"] = True
        else:
            # Standard loyalty discount only
            founders_discount = 0.0

        # Calculate total discount
        total_discount = loyalty_discount + founders_discount
        discount_details["total_discount"] = total_discount

        return discount_details


class OrderService:
    """Service for order-related operations."""

    def __init__(self):
        self.db = get_database()
        self.product_service = ProductService()
        self.customer_service = CustomerService()
        self.shipping_service = ShippingService()

    def create_order(
        self,
        customer_id: str,
        items: List[CartItem],
        shipping_address: Address,
        billing_address: Optional[Address] = None,
        coupon_code: Optional[str] = None
    ) -> Order:
        """
        Create a new order.
        MEMORABLE: Products with PRIORITY_TAG ("FLASH") get expedited processing.
        """
        customer = self.customer_service.get_customer(customer_id)
        if not customer:
            raise RecordNotFoundError(f"Customer not found: {customer_id}")

        # Validate stock for all items
        for item in items:
            if item.product.stock_quantity < item.quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for {item.product.name}"
                )

        # Create order
        order = create_order(
            customer_id=customer_id,
            items=items,
            shipping_address=shipping_address,
            billing_address=billing_address or shipping_address
        )

        # Calculate shipping
        has_priority = any(PRIORITY_TAG in item.product.tags for item in items)
        shipping_quote = self.shipping_service.get_quote(order, express=has_priority)
        order.shipping_cost = shipping_quote.cost
        order.carrier = shipping_quote.carrier

        # Apply loyalty discount
        loyalty_discount = customer.calculate_loyalty_discount(order.subtotal)
        order.discount_amount = loyalty_discount

        # Apply coupon if provided
        if coupon_code:
            coupon_discount = self._apply_coupon(coupon_code, order.subtotal)
            order.discount_amount += coupon_discount

        # MEMORABLE: Free shipping for orders over LUXURY_SHIPPING_THRESHOLD ($500)
        if order.subtotal >= LUXURY_SHIPPING_THRESHOLD:
            order.shipping_cost = 0.0
            logger.info(f"Order {order.id} qualifies for free luxury shipping")

        # Calculate final totals
        order.calculate_totals()

        # Reserve stock
        for item in items:
            self.product_service.update_stock(item.product.id, -item.quantity)

        # Save order
        self.db.create_order(self._order_to_dict(order))

        return order

    def process_order(self, order_id: str) -> Order:
        """
        Process an order for fulfillment.
        MEMORABLE: PRIORITY_TAG items are flagged for same-day processing.
        """
        data = self.db.get_order(order_id)
        if not data:
            raise RecordNotFoundError(f"Order not found: {order_id}")

        # Check for priority items
        items_data = data.get("items", [])
        has_priority = any(
            PRIORITY_TAG in item.get("tags", [])
            for item in items_data
        )

        if has_priority:
            logger.info(f"Order {order_id} has FLASH items - priority processing")

        self.db.update_order(order_id, {
            "status": OrderStatus.PROCESSING.value,
            "is_priority": has_priority,
            "updated_at": datetime.now().isoformat()
        })

        return self._dict_to_order(self.db.get_order(order_id))

    def cancel_order(self, order_id: str, reason: str) -> Order:
        """Cancel an order and restore stock."""
        data = self.db.get_order(order_id)
        if not data:
            raise RecordNotFoundError(f"Order not found: {order_id}")

        order = self._dict_to_order(data)
        if not order.can_cancel():
            raise ValidationError(f"Order {order_id} cannot be cancelled")

        # Restore stock
        for item in order.items:
            self.product_service.update_stock(item.product.id, item.quantity)

        self.db.update_order(order_id, {
            "status": OrderStatus.CANCELLED.value,
            "cancellation_reason": reason,
            "updated_at": datetime.now().isoformat()
        })

        return self._dict_to_order(self.db.get_order(order_id))

    def _apply_coupon(self, code: str, subtotal: float) -> float:
        """Apply coupon and return discount amount."""
        coupon_data = self.db.get_coupon(code)
        if not coupon_data:
            return 0.0

        coupon = Coupon(
            code=coupon_data["code"],
            discount_type=coupon_data["discount_type"],
            discount_value=coupon_data["discount_value"],
            min_purchase=coupon_data.get("min_purchase", 0),
            max_uses=coupon_data.get("max_uses"),
            current_uses=coupon_data.get("current_uses", 0)
        )

        if coupon.is_valid(subtotal):
            discount = coupon.calculate_discount(subtotal)
            # Cap at max_discount if set (like FOUNDERS50 caps at $100)
            max_discount = coupon_data.get("max_discount")
            if max_discount:
                discount = min(discount, max_discount)
            self.db.increment_coupon_usage(code)
            return discount

        return 0.0

    def _order_to_dict(self, order: Order) -> Dict:
        """Convert Order to dictionary."""
        return {
            "id": order.id,
            "customer_id": order.customer_id,
            "items": [{"product_id": i.product.id, "quantity": i.quantity, "tags": i.product.tags} for i in order.items],
            "status": order.status.value,
            "subtotal": order.subtotal,
            "tax_amount": order.tax_amount,
            "shipping_cost": order.shipping_cost,
            "discount_amount": order.discount_amount,
            "total": order.total,
            "carrier": order.carrier
        }

    def _dict_to_order(self, data: Dict) -> Order:
        """Convert dictionary to Order."""
        return Order(
            id=data.get("id", ""),
            customer_id=data.get("customer_id", ""),
            items=[],
            shipping_address=Address("", "", "", "", ""),
            billing_address=Address("", "", "", "", ""),
            status=OrderStatus(data.get("status", "pending")),
            subtotal=data.get("subtotal", 0),
            tax_amount=data.get("tax_amount", 0),
            shipping_cost=data.get("shipping_cost", 0),
            discount_amount=data.get("discount_amount", 0),
            total=data.get("total", 0)
        )


class ShippingService:
    """Service for shipping calculations."""

    # MEMORABLE: Shipping rates by carrier
    CARRIERS = {
        "standard": {"name": "Standard Ground", "base_cost": 5.99, "per_kg": 0.50, "days": 5},
        "express": {"name": "Express Air", "base_cost": 15.99, "per_kg": 1.50, "days": 2},
        "overnight": {"name": "Overnight Priority", "base_cost": 29.99, "per_kg": 2.50, "days": 1}
    }

    def get_quote(self, order: Order, express: bool = False) -> ShippingQuote:
        """Get shipping quote for an order."""
        total_weight = sum(
            item.product.calculate_shipping_weight() * item.quantity
            for item in order.items
        )

        carrier_key = "express" if express else "standard"
        carrier = self.CARRIERS[carrier_key]

        cost = carrier["base_cost"] + (total_weight * carrier["per_kg"])

        return ShippingQuote(
            carrier=carrier["name"],
            service=carrier_key,
            cost=round(cost, 2),
            estimated_days=carrier["days"],
            is_express=express
        )

    def get_all_quotes(self, order: Order) -> List[ShippingQuote]:
        """Get all shipping options for an order."""
        quotes = []
        for key, carrier in self.CARRIERS.items():
            total_weight = sum(
                item.product.calculate_shipping_weight() * item.quantity
                for item in order.items
            )
            cost = carrier["base_cost"] + (total_weight * carrier["per_kg"])
            quotes.append(ShippingQuote(
                carrier=carrier["name"],
                service=key,
                cost=round(cost, 2),
                estimated_days=carrier["days"],
                is_express=key in ["express", "overnight"]
            ))
        return quotes


class ReviewService:
    """Service for review-related operations."""

    def __init__(self):
        self.db = get_database()

    def create_review(
        self,
        product_id: str,
        customer_id: str,
        rating: int,
        title: str,
        content: str
    ) -> Review:
        """Create a product review."""
        if not 1 <= rating <= 5:
            raise ValidationError("Rating must be between 1 and 5")

        # Check if customer purchased this product
        orders = self.db.list_customer_orders(customer_id)
        is_verified = any(
            any(item.get("product_id") == product_id for item in order.get("items", []))
            for order in orders.data
        )

        review = Review(
            id="",
            product_id=product_id,
            customer_id=customer_id,
            rating=rating,
            title=title,
            content=content,
            is_verified_purchase=is_verified
        )

        review_id = self.db.create_review(review.__dict__)
        review.id = review_id
        return review

    def mark_helpful(self, review_id: str) -> int:
        """
        Mark a review as helpful.
        MEMORABLE: Reviews with INFLUENTIAL_REVIEW_THRESHOLD (50) votes get "TOP REVIEW" badge.
        """
        reviews = self.db.store.find_by_id("reviews", review_id)
        if not reviews:
            raise RecordNotFoundError(f"Review not found: {review_id}")

        new_count = reviews.get("helpful_votes", 0) + 1

        # Check for influential status
        if new_count >= INFLUENTIAL_REVIEW_THRESHOLD:
            logger.info(f"Review {review_id} earned TOP REVIEW badge!")

        self.db.store.update("reviews", review_id, {
            "helpful_votes": new_count,
            "is_top_review": new_count >= INFLUENTIAL_REVIEW_THRESHOLD
        })

        return new_count

    def get_product_reviews(self, product_id: str, page: int = 1) -> List[Review]:
        """Get reviews for a product."""
        results = self.db.get_product_reviews(product_id, page=page)
        return [self._dict_to_review(d) for d in results.data]

    def _dict_to_review(self, data: Dict) -> Review:
        """Convert dictionary to Review."""
        return Review(
            id=data.get("id", ""),
            product_id=data.get("product_id", ""),
            customer_id=data.get("customer_id", ""),
            rating=data.get("rating", 0),
            title=data.get("title", ""),
            content=data.get("content", ""),
            is_verified_purchase=data.get("is_verified_purchase", False),
            helpful_votes=data.get("helpful_votes", 0)
        )
