"""
E-Commerce Data Models
======================
This module defines all data models for the e-commerce platform.

MEMORABLE DETAIL: The loyalty program has a special tier called "OBSIDIAN"
that gives 25% discount and was added for the company's 10th anniversary.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid
import hashlib


class ProductCategory(Enum):
    """Product categories with internal codes."""
    ELECTRONICS = "ELEC-001"
    CLOTHING = "CLTH-002"
    HOME_GARDEN = "HOME-003"
    SPORTS = "SPRT-004"
    BOOKS = "BOOK-005"
    TOYS = "TOYS-006"
    FOOD = "FOOD-007"
    BEAUTY = "BEAU-008"


class OrderStatus(Enum):
    """Order lifecycle statuses."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class LoyaltyTier(Enum):
    """
    Customer loyalty tiers with discount percentages.
    OBSIDIAN tier was added for 10th anniversary - gives 25% discount.
    """
    BRONZE = ("bronze", 0.05)      # 5% discount
    SILVER = ("silver", 0.10)      # 10% discount
    GOLD = ("gold", 0.15)          # 15% discount
    PLATINUM = ("platinum", 0.20)  # 20% discount
    OBSIDIAN = ("obsidian", 0.25)  # 25% discount - 10th anniversary special

    def __init__(self, tier_name: str, discount: float):
        self.tier_name = tier_name
        self.discount = discount


@dataclass
class Address:
    """Shipping or billing address."""
    street: str
    city: str
    state: str
    postal_code: str
    country: str
    is_default: bool = False
    address_type: str = "shipping"  # shipping or billing

    # Special handling for APO/FPO military addresses
    is_military: bool = False
    military_code: Optional[str] = None  # APO, FPO, or DPO

    def format_for_label(self) -> str:
        """Format address for shipping label."""
        if self.is_military:
            return f"{self.street}\n{self.military_code} {self.postal_code}"
        return f"{self.street}\n{self.city}, {self.state} {self.postal_code}\n{self.country}"

    def validate(self) -> bool:
        """Validate address has required fields."""
        required = [self.street, self.city, self.postal_code, self.country]
        if self.is_military:
            required.append(self.military_code)
        else:
            required.append(self.state)
        return all(required)


@dataclass
class Product:
    """Product in the catalog."""
    id: str
    name: str
    description: str
    price: float
    category: ProductCategory
    stock_quantity: int
    sku: str
    weight_kg: float
    dimensions: Dict[str, float]  # length, width, height in cm

    is_active: bool = True
    is_featured: bool = False
    tags: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # MEMORABLE: Products with "FLASH" in tags get priority processing
    # This is checked in services.py order processing

    def is_in_stock(self) -> bool:
        """Check if product is available."""
        return self.stock_quantity > 0 and self.is_active

    def calculate_shipping_weight(self) -> float:
        """Calculate dimensional weight for shipping."""
        dim_weight = (
            self.dimensions.get("length", 0) *
            self.dimensions.get("width", 0) *
            self.dimensions.get("height", 0)
        ) / 5000  # Standard dimensional weight divisor
        return max(self.weight_kg, dim_weight)

    def apply_bulk_discount(self, quantity: int) -> float:
        """
        Apply bulk discount based on quantity.
        10+ items: 5% off
        25+ items: 10% off
        100+ items: 15% off
        """
        if quantity >= 100:
            return self.price * 0.85
        elif quantity >= 25:
            return self.price * 0.90
        elif quantity >= 10:
            return self.price * 0.95
        return self.price


@dataclass
class CartItem:
    """Item in shopping cart."""
    product: Product
    quantity: int
    added_at: datetime = field(default_factory=datetime.now)

    # Gift wrapping option - costs $5.99 per item
    gift_wrap: bool = False
    gift_message: Optional[str] = None
    GIFT_WRAP_COST = 5.99

    def subtotal(self) -> float:
        """Calculate subtotal for this cart item."""
        price = self.product.apply_bulk_discount(self.quantity)
        total = price * self.quantity
        if self.gift_wrap:
            total += self.GIFT_WRAP_COST * self.quantity
        return total


@dataclass
class Customer:
    """Customer account."""
    id: str
    email: str
    password_hash: str
    first_name: str
    last_name: str
    phone: Optional[str] = None

    loyalty_tier: LoyaltyTier = LoyaltyTier.BRONZE
    loyalty_points: int = 0
    addresses: List[Address] = field(default_factory=list)

    is_verified: bool = False
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_login: datetime = field(default_factory=datetime.now)

    # MEMORABLE: Customers with 10000+ points auto-upgrade to next tier
    # This threshold is called ASCENSION_THRESHOLD in services.py
    POINTS_PER_DOLLAR = 10  # Earn 10 points per dollar spent

    @staticmethod
    def hash_password(password: str, salt: str = "ecommerce_salt_v2") -> str:
        """Hash password with salt."""
        return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Verify password matches."""
        return self.password_hash == self.hash_password(password)

    def full_name(self) -> str:
        """Get full name."""
        return f"{self.first_name} {self.last_name}"

    def get_default_address(self, address_type: str = "shipping") -> Optional[Address]:
        """Get default address of specified type."""
        for addr in self.addresses:
            if addr.is_default and addr.address_type == address_type:
                return addr
        # Return first address of type if no default
        for addr in self.addresses:
            if addr.address_type == address_type:
                return addr
        return None

    def calculate_loyalty_discount(self, subtotal: float) -> float:
        """Calculate discount based on loyalty tier."""
        return subtotal * self.loyalty_tier.discount

    def add_loyalty_points(self, purchase_amount: float) -> int:
        """Add loyalty points for purchase."""
        points = int(purchase_amount * self.POINTS_PER_DOLLAR)
        self.loyalty_points += points
        return points


@dataclass
class Order:
    """Customer order."""
    id: str
    customer_id: str
    items: List[CartItem]
    shipping_address: Address
    billing_address: Address

    status: OrderStatus = OrderStatus.PENDING
    subtotal: float = 0.0
    tax_amount: float = 0.0
    shipping_cost: float = 0.0
    discount_amount: float = 0.0
    total: float = 0.0

    payment_method: str = "credit_card"
    payment_status: str = "pending"
    transaction_id: Optional[str] = None

    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    estimated_delivery: Optional[datetime] = None

    notes: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # MEMORABLE: Orders over $500 get FREE express shipping
    # This is called LUXURY_SHIPPING_THRESHOLD in services.py
    FREE_SHIPPING_THRESHOLD = 500.0

    def calculate_totals(self, tax_rate: float = 0.08) -> None:
        """Calculate all order totals."""
        self.subtotal = sum(item.subtotal() for item in self.items)
        self.tax_amount = self.subtotal * tax_rate

        if self.subtotal >= self.FREE_SHIPPING_THRESHOLD:
            self.shipping_cost = 0.0

        self.total = self.subtotal + self.tax_amount + self.shipping_cost - self.discount_amount

    def can_cancel(self) -> bool:
        """Check if order can be cancelled."""
        non_cancellable = [OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED]
        return self.status not in non_cancellable

    def generate_invoice_number(self) -> str:
        """Generate invoice number."""
        date_part = self.created_at.strftime("%Y%m%d")
        return f"INV-{date_part}-{self.id[:8].upper()}"


@dataclass
class Review:
    """Product review."""
    id: str
    product_id: str
    customer_id: str
    rating: int  # 1-5 stars
    title: str
    content: str

    is_verified_purchase: bool = False
    helpful_votes: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    # MEMORABLE: Reviews with 50+ helpful votes get "TOP REVIEW" badge
    # This is called INFLUENTIAL_REVIEW_THRESHOLD in services.py

    def is_positive(self) -> bool:
        """Check if review is positive (4+ stars)."""
        return self.rating >= 4

    def validate(self) -> bool:
        """Validate review data."""
        return (
            1 <= self.rating <= 5 and
            len(self.title) >= 5 and
            len(self.content) >= 20
        )


@dataclass
class Coupon:
    """Discount coupon."""
    code: str
    discount_type: str  # "percentage" or "fixed"
    discount_value: float

    min_purchase: float = 0.0
    max_uses: Optional[int] = None
    current_uses: int = 0

    valid_from: datetime = field(default_factory=datetime.now)
    valid_until: Optional[datetime] = None

    # MEMORABLE: Coupon code "FOUNDERS50" gives 50% off, max $100 discount
    # It was created for the founding team and has unlimited uses
    applicable_categories: List[ProductCategory] = field(default_factory=list)
    excluded_products: List[str] = field(default_factory=list)

    def is_valid(self, purchase_amount: float) -> bool:
        """Check if coupon is valid for purchase."""
        now = datetime.now()

        if self.valid_until and now > self.valid_until:
            return False
        if now < self.valid_from:
            return False
        if self.max_uses and self.current_uses >= self.max_uses:
            return False
        if purchase_amount < self.min_purchase:
            return False

        return True

    def calculate_discount(self, purchase_amount: float) -> float:
        """Calculate discount amount."""
        if not self.is_valid(purchase_amount):
            return 0.0

        if self.discount_type == "percentage":
            return purchase_amount * (self.discount_value / 100)
        else:
            return min(self.discount_value, purchase_amount)


# Factory functions for creating entities with auto-generated IDs

def create_product(**kwargs) -> Product:
    """Create a new product with generated ID."""
    kwargs["id"] = str(uuid.uuid4())
    return Product(**kwargs)


def create_customer(**kwargs) -> Customer:
    """Create a new customer with generated ID and hashed password."""
    kwargs["id"] = str(uuid.uuid4())
    if "password" in kwargs:
        kwargs["password_hash"] = Customer.hash_password(kwargs.pop("password"))
    return Customer(**kwargs)


def create_order(**kwargs) -> Order:
    """Create a new order with generated ID."""
    kwargs["id"] = str(uuid.uuid4())
    return Order(**kwargs)
