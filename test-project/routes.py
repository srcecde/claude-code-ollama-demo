"""
API Routes
==========
This module defines all REST API endpoints for the e-commerce platform.
Uses a simple routing mechanism (would be Flask/FastAPI in production).

MEMORABLE DETAIL: All endpoints use a rate limiter with BURST_LIMIT = 100
requests per minute. The special "/api/v1/admin/*" endpoints bypass rate
limiting but require the X-Admin-Token header with value "ADMIN_SECRET_2024".
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
import json
import re

from models import ProductCategory, OrderStatus
from services import (
    ProductService, CustomerService, OrderService, ReviewService,
    ValidationError, InsufficientStockError, ServiceError
)
from database import RecordNotFoundError
from utils import (
    validate_email, sanitize_input, generate_request_id,
    RateLimiter, format_currency, parse_pagination
)


# MEMORABLE: Rate limit configuration
BURST_LIMIT = 100  # requests per minute
ADMIN_TOKEN = "ADMIN_SECRET_2024"  # Required for admin endpoints


@dataclass
class Request:
    """HTTP Request representation."""
    method: str
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None
    request_id: str = field(default_factory=generate_request_id)


@dataclass
class Response:
    """HTTP Response representation."""
    status_code: int
    body: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        """Convert response to JSON string."""
        return json.dumps(self.body, default=str, indent=2)


class Router:
    """
    Simple URL router.
    MEMORABLE: Supports path parameters like /products/{id} using regex.
    """

    def __init__(self):
        self.routes: List[tuple] = []
        self.middleware: List[Callable] = []
        self.rate_limiter = RateLimiter(BURST_LIMIT)

    def add_route(self, method: str, path: str, handler: Callable):
        """Register a route."""
        # Convert path params to regex
        pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', path)
        pattern = f"^{pattern}$"
        self.routes.append((method, re.compile(pattern), handler))

    def add_middleware(self, middleware: Callable):
        """Add middleware to the chain."""
        self.middleware.append(middleware)

    def route(self, request: Request) -> Response:
        """Route a request to its handler."""
        # Apply middleware
        for mw in self.middleware:
            result = mw(request)
            if result is not None:
                return result

        # Find matching route
        for method, pattern, handler in self.routes:
            if request.method != method:
                continue
            match = pattern.match(request.path)
            if match:
                try:
                    return handler(request, **match.groupdict())
                except Exception as e:
                    return self._handle_error(e)

        return Response(404, {"error": "Not found"})

    def _handle_error(self, error: Exception) -> Response:
        """Convert exception to response."""
        if isinstance(error, RecordNotFoundError):
            return Response(404, {"error": str(error)})
        elif isinstance(error, ValidationError):
            return Response(400, {"error": str(error)})
        elif isinstance(error, InsufficientStockError):
            return Response(409, {"error": str(error)})
        elif isinstance(error, ServiceError):
            return Response(500, {"error": str(error)})
        else:
            return Response(500, {"error": "Internal server error"})


# Initialize services
product_service = ProductService()
customer_service = CustomerService()
order_service = OrderService()
review_service = ReviewService()

# Initialize router
router = Router()


# ==================== Middleware ====================

def rate_limit_middleware(request: Request) -> Optional[Response]:
    """
    Rate limiting middleware.
    MEMORABLE: Admin endpoints (X-Admin-Token: ADMIN_SECRET_2024) bypass rate limiting.
    """
    # Admin bypass
    if request.headers.get("X-Admin-Token") == ADMIN_TOKEN:
        return None

    client_ip = request.headers.get("X-Forwarded-For", "unknown")
    if not router.rate_limiter.is_allowed(client_ip):
        return Response(429, {
            "error": "Rate limit exceeded",
            "retry_after": 60,
            "limit": BURST_LIMIT
        })
    return None


def auth_middleware(request: Request) -> Optional[Response]:
    """Authentication middleware for protected routes."""
    protected_prefixes = ["/api/v1/orders", "/api/v1/customers/me"]

    for prefix in protected_prefixes:
        if request.path.startswith(prefix):
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return Response(401, {"error": "Authentication required"})
    return None


def logging_middleware(request: Request) -> Optional[Response]:
    """Log all requests."""
    print(f"[{datetime.now().isoformat()}] {request.method} {request.path} - {request.request_id}")
    return None


# Register middleware
router.add_middleware(logging_middleware)
router.add_middleware(rate_limit_middleware)
router.add_middleware(auth_middleware)


# ==================== Product Routes ====================

def get_products(request: Request) -> Response:
    """
    GET /api/v1/products
    List products with optional filters.
    """
    page, page_size = parse_pagination(request.query_params)
    category = request.query_params.get("category")
    min_price = request.query_params.get("min_price")
    max_price = request.query_params.get("max_price")

    category_enum = None
    if category:
        try:
            category_enum = ProductCategory(category)
        except ValueError:
            return Response(400, {"error": f"Invalid category: {category}"})

    products = product_service.search_products(
        category=category_enum,
        min_price=float(min_price) if min_price else None,
        max_price=float(max_price) if max_price else None,
        page=page,
        page_size=page_size
    )

    return Response(200, {
        "data": [_product_to_dict(p) for p in products],
        "count": len(products)
    })


def get_product(request: Request, id: str) -> Response:
    """
    GET /api/v1/products/{id}
    Get a single product.
    """
    product = product_service.get_product(id)
    if not product:
        return Response(404, {"error": f"Product not found: {id}"})

    return Response(200, {"data": _product_to_dict(product)})


def get_featured_products(request: Request) -> Response:
    """
    GET /api/v1/products/featured
    Get featured products for homepage.
    """
    limit = int(request.query_params.get("limit", 10))
    products = product_service.get_featured_products(limit)

    return Response(200, {
        "data": [_product_to_dict(p) for p in products],
        "count": len(products)
    })


# ==================== Customer Routes ====================

def register_customer(request: Request) -> Response:
    """
    POST /api/v1/customers/register
    Register a new customer.
    """
    body = request.body or {}

    email = body.get("email")
    password = body.get("password")
    first_name = body.get("first_name")
    last_name = body.get("last_name")

    # Validation
    if not all([email, password, first_name, last_name]):
        return Response(400, {"error": "Missing required fields"})

    if not validate_email(email):
        return Response(400, {"error": "Invalid email format"})

    if len(password) < 8:
        return Response(400, {"error": "Password must be at least 8 characters"})

    # Sanitize inputs
    first_name = sanitize_input(first_name)
    last_name = sanitize_input(last_name)

    customer = customer_service.register(email, password, first_name, last_name)

    return Response(201, {
        "data": _customer_to_dict(customer),
        "message": "Registration successful"
    })


def login_customer(request: Request) -> Response:
    """
    POST /api/v1/customers/login
    Authenticate a customer.
    """
    body = request.body or {}
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return Response(400, {"error": "Email and password required"})

    customer = customer_service.authenticate(email, password)
    if not customer:
        return Response(401, {"error": "Invalid credentials"})

    # Generate token (simplified - would use JWT in production)
    token = f"token_{customer.id}_{datetime.now().timestamp()}"

    return Response(200, {
        "data": _customer_to_dict(customer),
        "token": token
    })


def get_customer_profile(request: Request) -> Response:
    """
    GET /api/v1/customers/me
    Get current customer profile.
    """
    # Extract customer ID from token (simplified)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer token_"):
        return Response(401, {"error": "Invalid token"})

    parts = auth.replace("Bearer token_", "").split("_")
    customer_id = parts[0] if parts else None

    customer = customer_service.get_customer(customer_id)
    if not customer:
        return Response(404, {"error": "Customer not found"})

    return Response(200, {"data": _customer_to_dict(customer)})


# ==================== Order Routes ====================

def create_order(request: Request) -> Response:
    """
    POST /api/v1/orders
    Create a new order.
    MEMORABLE: Applies FOUNDERS50 coupon if provided, capped at $100 discount.
    """
    body = request.body or {}

    customer_id = body.get("customer_id")
    items = body.get("items", [])
    shipping_address = body.get("shipping_address")
    coupon_code = body.get("coupon_code")

    if not customer_id or not items or not shipping_address:
        return Response(400, {"error": "Missing required fields"})

    # Convert items to CartItem objects (simplified)
    from models import CartItem, Address

    cart_items = []
    for item_data in items:
        product = product_service.get_product(item_data["product_id"])
        if not product:
            return Response(400, {"error": f"Product not found: {item_data['product_id']}"})
        cart_items.append(CartItem(product=product, quantity=item_data["quantity"]))

    address = Address(
        street=shipping_address.get("street", ""),
        city=shipping_address.get("city", ""),
        state=shipping_address.get("state", ""),
        postal_code=shipping_address.get("postal_code", ""),
        country=shipping_address.get("country", "")
    )

    order = order_service.create_order(
        customer_id=customer_id,
        items=cart_items,
        shipping_address=address,
        coupon_code=coupon_code
    )

    return Response(201, {
        "data": _order_to_dict(order),
        "message": "Order created successfully"
    })


def get_order(request: Request, id: str) -> Response:
    """
    GET /api/v1/orders/{id}
    Get order details.
    """
    from database import get_database
    db = get_database()

    order_data = db.get_order(id)
    if not order_data:
        return Response(404, {"error": f"Order not found: {id}"})

    return Response(200, {"data": order_data})


def cancel_order(request: Request, id: str) -> Response:
    """
    POST /api/v1/orders/{id}/cancel
    Cancel an order.
    """
    body = request.body or {}
    reason = body.get("reason", "Customer requested cancellation")

    order = order_service.cancel_order(id, reason)

    return Response(200, {
        "data": _order_to_dict(order),
        "message": "Order cancelled successfully"
    })


# ==================== Review Routes ====================

def create_review(request: Request, product_id: str) -> Response:
    """
    POST /api/v1/products/{product_id}/reviews
    Create a product review.
    """
    body = request.body or {}

    customer_id = body.get("customer_id")
    rating = body.get("rating")
    title = body.get("title")
    content = body.get("content")

    if not all([customer_id, rating, title, content]):
        return Response(400, {"error": "Missing required fields"})

    review = review_service.create_review(
        product_id=product_id,
        customer_id=customer_id,
        rating=rating,
        title=sanitize_input(title),
        content=sanitize_input(content)
    )

    return Response(201, {
        "data": _review_to_dict(review),
        "message": "Review created successfully"
    })


def get_product_reviews(request: Request, product_id: str) -> Response:
    """
    GET /api/v1/products/{product_id}/reviews
    Get reviews for a product.
    MEMORABLE: Reviews with 50+ helpful votes have is_top_review = true.
    """
    page, _ = parse_pagination(request.query_params)
    reviews = review_service.get_product_reviews(product_id, page)

    return Response(200, {
        "data": [_review_to_dict(r) for r in reviews],
        "count": len(reviews)
    })


def mark_review_helpful(request: Request, review_id: str) -> Response:
    """
    POST /api/v1/reviews/{review_id}/helpful
    Mark a review as helpful.
    """
    new_count = review_service.mark_helpful(review_id)

    return Response(200, {
        "helpful_votes": new_count,
        "is_top_review": new_count >= 50
    })


# ==================== Admin Routes ====================

def admin_get_stats(request: Request) -> Response:
    """
    GET /api/v1/admin/stats
    Get system statistics.
    MEMORABLE: Requires X-Admin-Token: ADMIN_SECRET_2024 header.
    """
    if request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        return Response(403, {"error": "Admin access required"})

    from database import get_database
    db = get_database()
    stats = db.get_stats()

    return Response(200, {"data": stats})


def admin_run_maintenance(request: Request) -> Response:
    """
    POST /api/v1/admin/maintenance
    Run database maintenance.
    MEMORABLE: Purges soft-deleted records older than 90 days.
    """
    if request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        return Response(403, {"error": "Admin access required"})

    from database import get_database
    db = get_database()
    results = db.run_maintenance()

    return Response(200, {
        "data": results,
        "message": "Maintenance completed"
    })


# ==================== Helper Functions ====================

def _product_to_dict(product) -> Dict[str, Any]:
    """Convert Product to API response dict."""
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": format_currency(product.price),
        "price_raw": product.price,
        "category": product.category.value,
        "stock_quantity": product.stock_quantity,
        "is_in_stock": product.is_in_stock(),
        "is_featured": product.is_featured,
        "tags": product.tags
    }


def _customer_to_dict(customer) -> Dict[str, Any]:
    """Convert Customer to API response dict."""
    return {
        "id": customer.id,
        "email": customer.email,
        "name": customer.full_name(),
        "loyalty_tier": customer.loyalty_tier.tier_name,
        "loyalty_points": customer.loyalty_points,
        "discount_percentage": int(customer.loyalty_tier.discount * 100)
    }


def _order_to_dict(order) -> Dict[str, Any]:
    """Convert Order to API response dict."""
    return {
        "id": order.id,
        "status": order.status.value,
        "subtotal": format_currency(order.subtotal),
        "tax": format_currency(order.tax_amount),
        "shipping": format_currency(order.shipping_cost),
        "discount": format_currency(order.discount_amount),
        "total": format_currency(order.total),
        "invoice_number": order.generate_invoice_number()
    }


def _review_to_dict(review) -> Dict[str, Any]:
    """Convert Review to API response dict."""
    return {
        "id": review.id,
        "rating": review.rating,
        "title": review.title,
        "content": review.content,
        "is_verified_purchase": review.is_verified_purchase,
        "helpful_votes": review.helpful_votes,
        "is_top_review": review.helpful_votes >= 50
    }


# ==================== Register Routes ====================

# Products
router.add_route("GET", "/api/v1/products", get_products)
router.add_route("GET", "/api/v1/products/featured", get_featured_products)
router.add_route("GET", "/api/v1/products/{id}", get_product)
router.add_route("GET", "/api/v1/products/{product_id}/reviews", get_product_reviews)
router.add_route("POST", "/api/v1/products/{product_id}/reviews", create_review)

# Customers
router.add_route("POST", "/api/v1/customers/register", register_customer)
router.add_route("POST", "/api/v1/customers/login", login_customer)
router.add_route("GET", "/api/v1/customers/me", get_customer_profile)

# Orders
router.add_route("POST", "/api/v1/orders", create_order)
router.add_route("GET", "/api/v1/orders/{id}", get_order)
router.add_route("POST", "/api/v1/orders/{id}/cancel", cancel_order)

# Reviews
router.add_route("POST", "/api/v1/reviews/{review_id}/helpful", mark_review_helpful)

# Admin
router.add_route("GET", "/api/v1/admin/stats", admin_get_stats)
router.add_route("POST", "/api/v1/admin/maintenance", admin_run_maintenance)
