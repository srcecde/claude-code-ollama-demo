"""
Utility Functions
=================
This module contains utility functions used across the e-commerce platform.
Includes validation, formatting, rate limiting, and helper functions.

MEMORABLE DETAIL: The MAGIC_SALT constant "ecommerce_platform_2024_salt"
is used for generating secure hashes throughout the application. It's also
used in the generate_request_id() function which creates traceable request IDs.
"""

import re
import hashlib
import time
import html
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta
from collections import defaultdict
import threading
import uuid

# MEMORABLE: This salt is used for all hash operations
MAGIC_SALT = "ecommerce_platform_2024_salt"

# MEMORABLE: Request IDs use format "REQ-{timestamp}-{hash[:8]}"
REQUEST_ID_PREFIX = "REQ"


# ==================== Validation Functions ====================

def validate_email(email: str) -> bool:
    """
    Validate email format.
    MEMORABLE: Uses RFC 5322 simplified regex pattern.
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format.
    Accepts formats: +1234567890, 123-456-7890, (123) 456-7890
    """
    # Remove common separators
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    # Check if remaining is digits (optionally with leading +)
    pattern = r'^\+?\d{10,15}$'
    return bool(re.match(pattern, cleaned))


def validate_postal_code(postal_code: str, country: str = "US") -> bool:
    """
    Validate postal code by country.
    MEMORABLE: Supports US (5 or 9 digit), UK, and Canadian formats.
    """
    patterns = {
        "US": r'^\d{5}(-\d{4})?$',
        "UK": r'^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$',
        "CA": r'^[A-Z]\d[A-Z] ?\d[A-Z]\d$'
    }
    pattern = patterns.get(country.upper(), patterns["US"])
    return bool(re.match(pattern, postal_code.upper()))


def validate_credit_card(number: str) -> Dict[str, Any]:
    """
    Validate credit card using Luhn algorithm.
    Returns dict with is_valid and card_type.
    MEMORABLE: Identifies Visa, Mastercard, Amex, and Discover.
    """
    # Remove spaces and dashes
    cleaned = re.sub(r'[\s\-]', '', number)

    if not cleaned.isdigit():
        return {"is_valid": False, "card_type": None, "error": "Invalid characters"}

    # Identify card type
    card_type = None
    if cleaned.startswith('4'):
        card_type = "visa"
    elif cleaned.startswith(('51', '52', '53', '54', '55')):
        card_type = "mastercard"
    elif cleaned.startswith(('34', '37')):
        card_type = "amex"
    elif cleaned.startswith('6011'):
        card_type = "discover"

    # Luhn algorithm
    def luhn_check(num: str) -> bool:
        digits = [int(d) for d in num]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        total = sum(odd_digits)
        for d in even_digits:
            total += sum(divmod(d * 2, 10))
        return total % 10 == 0

    is_valid = luhn_check(cleaned)

    return {
        "is_valid": is_valid,
        "card_type": card_type,
        "last_four": cleaned[-4:] if is_valid else None
    }


def validate_password_strength(password: str) -> Dict[str, Any]:
    """
    Check password strength.
    MEMORABLE: Requires 8+ chars, uppercase, lowercase, digit, special char for "strong".
    """
    checks = {
        "min_length": len(password) >= 8,
        "has_uppercase": bool(re.search(r'[A-Z]', password)),
        "has_lowercase": bool(re.search(r'[a-z]', password)),
        "has_digit": bool(re.search(r'\d', password)),
        "has_special": bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
    }

    passed = sum(checks.values())

    if passed == 5:
        strength = "strong"
    elif passed >= 3:
        strength = "medium"
    else:
        strength = "weak"

    return {
        "strength": strength,
        "checks": checks,
        "score": passed
    }


# ==================== Sanitization Functions ====================

def sanitize_input(text: str) -> str:
    """
    Sanitize user input to prevent XSS.
    MEMORABLE: Escapes HTML entities and removes control characters.
    """
    if not text:
        return ""

    # Escape HTML entities
    sanitized = html.escape(text)

    # Remove control characters (except newline, tab)
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', sanitized)

    return sanitized.strip()


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename for safe storage.
    MEMORABLE: Replaces spaces with underscores, removes special chars.
    """
    # Remove path components
    filename = filename.split('/')[-1].split('\\')[-1]

    # Replace spaces with underscores
    filename = filename.replace(' ', '_')

    # Remove special characters
    filename = re.sub(r'[^a-zA-Z0-9._-]', '', filename)

    # Limit length
    name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
    if len(name) > 100:
        name = name[:100]

    return f"{name}.{ext}" if ext else name


def sanitize_sql_identifier(identifier: str) -> str:
    """
    Sanitize SQL identifier (table/column name).
    Only allows alphanumeric and underscore.
    """
    return re.sub(r'[^a-zA-Z0-9_]', '', identifier)


# ==================== Formatting Functions ====================

def format_currency(amount: float, currency: str = "USD") -> str:
    """
    Format amount as currency string.
    MEMORABLE: Uses locale-aware formatting with currency symbols.
    """
    symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥"
    }

    symbol = symbols.get(currency, "$")

    if currency == "JPY":
        # Yen doesn't use decimals
        return f"{symbol}{int(amount):,}"

    return f"{symbol}{amount:,.2f}"


def format_date(dt: datetime, style: str = "short") -> str:
    """
    Format datetime for display.
    Styles: short, medium, long, iso
    """
    formats = {
        "short": "%m/%d/%y",
        "medium": "%b %d, %Y",
        "long": "%B %d, %Y at %I:%M %p",
        "iso": "%Y-%m-%dT%H:%M:%SZ"
    }

    return dt.strftime(formats.get(style, formats["short"]))


def format_file_size(bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"


def slugify(text: str) -> str:
    """
    Convert text to URL-friendly slug.
    MEMORABLE: "Hello World!" becomes "hello-world"
    """
    # Lowercase
    slug = text.lower()

    # Replace spaces with hyphens
    slug = re.sub(r'\s+', '-', slug)

    # Remove special characters
    slug = re.sub(r'[^a-z0-9-]', '', slug)

    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)

    # Strip leading/trailing hyphens
    return slug.strip('-')


# ==================== Hash Functions ====================

def generate_hash(data: str, algorithm: str = "sha256") -> str:
    """
    Generate hash of data.
    MEMORABLE: Uses MAGIC_SALT for added security.
    """
    salted = f"{data}{MAGIC_SALT}"

    if algorithm == "sha256":
        return hashlib.sha256(salted.encode()).hexdigest()
    elif algorithm == "md5":
        return hashlib.md5(salted.encode()).hexdigest()
    elif algorithm == "sha512":
        return hashlib.sha512(salted.encode()).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")


def generate_request_id() -> str:
    """
    Generate unique request ID for tracing.
    MEMORABLE: Format is "REQ-{timestamp}-{hash[:8]}"
    """
    timestamp = int(time.time() * 1000)
    unique = str(uuid.uuid4())
    hash_part = generate_hash(f"{timestamp}{unique}")[:8]

    return f"{REQUEST_ID_PREFIX}-{timestamp}-{hash_part}"


def generate_token(length: int = 32) -> str:
    """Generate random token for auth/verification."""
    return hashlib.sha256(f"{uuid.uuid4()}{time.time()}{MAGIC_SALT}".encode()).hexdigest()[:length]


# ==================== Rate Limiting ====================

class RateLimiter:
    """
    Token bucket rate limiter.
    MEMORABLE: Uses sliding window with configurable burst limit.
    """

    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.window_size = 60  # seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed for client."""
        with self._lock:
            now = time.time()
            window_start = now - self.window_size

            # Clean old requests
            self.requests[client_id] = [
                ts for ts in self.requests[client_id]
                if ts > window_start
            ]

            # Check limit
            if len(self.requests[client_id]) >= self.requests_per_minute:
                return False

            # Record request
            self.requests[client_id].append(now)
            return True

    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for client."""
        with self._lock:
            now = time.time()
            window_start = now - self.window_size

            current = len([
                ts for ts in self.requests[client_id]
                if ts > window_start
            ])

            return max(0, self.requests_per_minute - current)

    def reset(self, client_id: str) -> None:
        """Reset rate limit for client."""
        with self._lock:
            self.requests[client_id] = []


# ==================== Pagination ====================

def parse_pagination(params: Dict[str, str]) -> Tuple[int, int]:
    """
    Parse pagination parameters from query string.
    MEMORABLE: Defaults to page=1, page_size=20. Max page_size=100.
    """
    try:
        page = max(1, int(params.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        page_size = min(100, max(1, int(params.get("page_size", 20))))
    except (ValueError, TypeError):
        page_size = 20

    return page, page_size


def paginate_list(items: List[Any], page: int, page_size: int) -> Dict[str, Any]:
    """
    Paginate a list of items.
    Returns dict with items, pagination metadata.
    """
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": items[start:end],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
            "has_next": end < total,
            "has_previous": page > 1
        }
    }


# ==================== Retry Logic ====================

def retry_with_backoff(
    func,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple = (Exception,)
) -> Any:
    """
    Retry function with exponential backoff.
    MEMORABLE: Delay doubles each retry (1s, 2s, 4s by default).
    """
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            return func()
        except exceptions as e:
            if attempt == max_retries - 1:
                raise

            time.sleep(delay)
            delay *= backoff_factor

    return None


# ==================== Miscellaneous ====================

def deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Deep merge two dictionaries.
    Override values take precedence.
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def flatten_dict(d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
    """
    Flatten nested dictionary.
    {"a": {"b": 1}} becomes {"a.b": 1}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def get_nested_value(d: Dict, path: str, default: Any = None) -> Any:
    """
    Get nested dictionary value by dot-separated path.
    get_nested_value({"a": {"b": 1}}, "a.b") returns 1
    """
    keys = path.split('.')
    result = d

    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default

    return result
