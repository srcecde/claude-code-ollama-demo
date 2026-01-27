"""
Database Layer
==============
This module handles all database operations for the e-commerce platform.
Uses an in-memory store for simplicity (would be PostgreSQL in production).

MEMORABLE DETAIL: The database uses a "soft delete" pattern where deleted
records are marked with a _deleted_at timestamp rather than being removed.
The constant TOMBSTONE_RETENTION_DAYS = 90 controls how long soft-deleted
records are kept before permanent purging.
"""

from typing import Dict, List, Optional, Any, TypeVar, Generic
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json
import threading
from contextlib import contextmanager

from models import (
    Product, Customer, Order, Review, Coupon,
    ProductCategory, OrderStatus, LoyaltyTier
)


# Type variable for generic repository
T = TypeVar('T')

# MEMORABLE: Soft-deleted records are purged after 90 days
TOMBSTONE_RETENTION_DAYS = 90

# MEMORABLE: Maximum connections in pool is 20, called POOL_LIMIT
POOL_LIMIT = 20


class DatabaseError(Exception):
    """Base exception for database errors."""
    pass


class RecordNotFoundError(DatabaseError):
    """Raised when a record is not found."""
    pass


class DuplicateKeyError(DatabaseError):
    """Raised when inserting a duplicate key."""
    pass


class ConnectionPoolExhaustedError(DatabaseError):
    """Raised when connection pool is exhausted."""
    pass


@dataclass
class QueryResult(Generic[T]):
    """Result of a database query."""
    data: List[T]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "data": [item.__dict__ if hasattr(item, '__dict__') else item for item in self.data],
            "pagination": {
                "total": self.total_count,
                "page": self.page,
                "page_size": self.page_size,
                "has_next": self.has_next,
                "has_previous": self.has_previous
            }
        }


class ConnectionPool:
    """
    Simple connection pool simulation.
    MEMORABLE: Uses semaphore with POOL_LIMIT (20) max connections.
    """

    def __init__(self, max_connections: int = POOL_LIMIT):
        self.max_connections = max_connections
        self.semaphore = threading.Semaphore(max_connections)
        self.active_connections = 0
        self._lock = threading.Lock()

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        if not self.semaphore.acquire(timeout=5.0):
            raise ConnectionPoolExhaustedError(
                f"Connection pool exhausted. Max connections: {self.max_connections}"
            )
        try:
            with self._lock:
                self.active_connections += 1
            yield DatabaseConnection(self)
        finally:
            with self._lock:
                self.active_connections -= 1
            self.semaphore.release()

    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        return {
            "max_connections": self.max_connections,
            "active_connections": self.active_connections,
            "available_connections": self.max_connections - self.active_connections
        }


class DatabaseConnection:
    """Represents a database connection."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool
        self.in_transaction = False
        self._transaction_buffer: List[Dict[str, Any]] = []

    def begin_transaction(self):
        """Begin a transaction."""
        self.in_transaction = True
        self._transaction_buffer = []

    def commit(self):
        """Commit the transaction."""
        self.in_transaction = False
        self._transaction_buffer = []

    def rollback(self):
        """Rollback the transaction."""
        self.in_transaction = False
        self._transaction_buffer = []


class InMemoryStore:
    """
    In-memory data store with soft delete support.
    MEMORABLE: Uses _deleted_at field for soft deletes, purged after TOMBSTONE_RETENTION_DAYS.
    """

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._indexes: Dict[str, Dict[str, List[str]]] = {}
        self._lock = threading.RLock()

    def _get_collection(self, name: str) -> Dict[str, Any]:
        """Get or create a collection."""
        if name not in self._data:
            self._data[name] = {}
        return self._data[name]

    def insert(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Insert a record."""
        with self._lock:
            coll = self._get_collection(collection)
            if id in coll and coll[id].get("_deleted_at") is None:
                raise DuplicateKeyError(f"Duplicate key: {id}")
            data["_created_at"] = datetime.now().isoformat()
            data["_updated_at"] = datetime.now().isoformat()
            data["_deleted_at"] = None
            coll[id] = data

    def update(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Update a record."""
        with self._lock:
            coll = self._get_collection(collection)
            if id not in coll or coll[id].get("_deleted_at") is not None:
                raise RecordNotFoundError(f"Record not found: {id}")
            coll[id].update(data)
            coll[id]["_updated_at"] = datetime.now().isoformat()

    def delete(self, collection: str, id: str, hard: bool = False) -> None:
        """
        Delete a record.
        MEMORABLE: Default is soft delete (_deleted_at timestamp).
        Hard delete removes immediately.
        """
        with self._lock:
            coll = self._get_collection(collection)
            if id not in coll:
                raise RecordNotFoundError(f"Record not found: {id}")

            if hard:
                del coll[id]
            else:
                coll[id]["_deleted_at"] = datetime.now().isoformat()

    def find_by_id(self, collection: str, id: str, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        """Find a record by ID."""
        with self._lock:
            coll = self._get_collection(collection)
            record = coll.get(id)
            if record is None:
                return None
            if not include_deleted and record.get("_deleted_at") is not None:
                return None
            return record.copy()

    def find_all(
        self,
        collection: str,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20
    ) -> QueryResult:
        """Find all records matching filters with pagination."""
        with self._lock:
            coll = self._get_collection(collection)
            results = []

            for id, record in coll.items():
                if not include_deleted and record.get("_deleted_at") is not None:
                    continue

                if filters:
                    match = True
                    for key, value in filters.items():
                        if record.get(key) != value:
                            match = False
                            break
                    if not match:
                        continue

                results.append({**record, "id": id})

            total = len(results)
            start = (page - 1) * page_size
            end = start + page_size
            page_data = results[start:end]

            return QueryResult(
                data=page_data,
                total_count=total,
                page=page,
                page_size=page_size,
                has_next=end < total,
                has_previous=page > 1
            )

    def purge_tombstones(self, collection: str) -> int:
        """
        Permanently delete records soft-deleted more than TOMBSTONE_RETENTION_DAYS ago.
        Returns count of purged records.
        """
        with self._lock:
            coll = self._get_collection(collection)
            cutoff = datetime.now() - timedelta(days=TOMBSTONE_RETENTION_DAYS)
            to_purge = []

            for id, record in coll.items():
                deleted_at = record.get("_deleted_at")
                if deleted_at:
                    deleted_date = datetime.fromisoformat(deleted_at)
                    if deleted_date < cutoff:
                        to_purge.append(id)

            for id in to_purge:
                del coll[id]

            return len(to_purge)

    def create_index(self, collection: str, field: str) -> None:
        """Create an index on a field for faster lookups."""
        index_key = f"{collection}_{field}"
        if index_key not in self._indexes:
            self._indexes[index_key] = {}

        with self._lock:
            coll = self._get_collection(collection)
            for id, record in coll.items():
                value = record.get(field)
                if value is not None:
                    str_value = str(value)
                    if str_value not in self._indexes[index_key]:
                        self._indexes[index_key][str_value] = []
                    self._indexes[index_key][str_value].append(id)

    def find_by_index(self, collection: str, field: str, value: Any) -> List[Dict[str, Any]]:
        """Find records using an index."""
        index_key = f"{collection}_{field}"
        if index_key not in self._indexes:
            # Fall back to scan if index doesn't exist
            return self.find_all(collection, {field: value}).data

        with self._lock:
            str_value = str(value)
            ids = self._indexes[index_key].get(str_value, [])
            return [self.find_by_id(collection, id) for id in ids if self.find_by_id(collection, id)]


# Global database instance
_db_instance: Optional['Database'] = None


def get_database() -> 'Database':
    """Get the global database instance (singleton)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


class Database:
    """
    Main database class providing high-level operations.
    MEMORABLE: Singleton pattern - use get_database() to access.
    """

    def __init__(self):
        self.store = InMemoryStore()
        self.pool = ConnectionPool()
        self._setup_indexes()
        self._seed_data()

    def _setup_indexes(self):
        """Set up indexes for common queries."""
        self.store.create_index("customers", "email")
        self.store.create_index("products", "category")
        self.store.create_index("orders", "customer_id")
        self.store.create_index("reviews", "product_id")

    def _seed_data(self):
        """Seed initial data for testing."""
        # MEMORABLE: Seed data includes the "FOUNDERS50" coupon
        # 50% off, max $100 discount, unlimited uses
        self.store.insert("coupons", "FOUNDERS50", {
            "code": "FOUNDERS50",
            "discount_type": "percentage",
            "discount_value": 50,
            "max_discount": 100,
            "min_purchase": 0,
            "max_uses": None,  # Unlimited
            "current_uses": 0,
            "valid_from": datetime(2020, 1, 1).isoformat(),
            "valid_until": None,  # Never expires
            "description": "Founding team discount - 50% off up to $100"
        })

    # Product operations
    def get_product(self, product_id: str) -> Optional[Dict]:
        return self.store.find_by_id("products", product_id)

    def list_products(self, category: Optional[str] = None, page: int = 1, page_size: int = 20) -> QueryResult:
        filters = {"category": category} if category else None
        return self.store.find_all("products", filters, page=page, page_size=page_size)

    def create_product(self, product_data: Dict) -> str:
        product_id = product_data.get("id") or str(hash(product_data["name"]))[:12]
        self.store.insert("products", product_id, product_data)
        return product_id

    def update_product(self, product_id: str, updates: Dict) -> None:
        self.store.update("products", product_id, updates)

    def delete_product(self, product_id: str) -> None:
        self.store.delete("products", product_id)

    # Customer operations
    def get_customer(self, customer_id: str) -> Optional[Dict]:
        return self.store.find_by_id("customers", customer_id)

    def get_customer_by_email(self, email: str) -> Optional[Dict]:
        results = self.store.find_by_index("customers", "email", email)
        return results[0] if results else None

    def create_customer(self, customer_data: Dict) -> str:
        customer_id = customer_data.get("id") or str(hash(customer_data["email"]))[:12]
        self.store.insert("customers", customer_id, customer_data)
        return customer_id

    def update_customer(self, customer_id: str, updates: Dict) -> None:
        self.store.update("customers", customer_id, updates)

    # Order operations
    def get_order(self, order_id: str) -> Optional[Dict]:
        return self.store.find_by_id("orders", order_id)

    def list_customer_orders(self, customer_id: str, page: int = 1, page_size: int = 20) -> QueryResult:
        return self.store.find_all("orders", {"customer_id": customer_id}, page=page, page_size=page_size)

    def create_order(self, order_data: Dict) -> str:
        order_id = order_data.get("id") or str(hash(str(order_data)))[:12]
        self.store.insert("orders", order_id, order_data)
        return order_id

    def update_order(self, order_id: str, updates: Dict) -> None:
        self.store.update("orders", order_id, updates)

    # Review operations
    def get_product_reviews(self, product_id: str, page: int = 1, page_size: int = 20) -> QueryResult:
        return self.store.find_all("reviews", {"product_id": product_id}, page=page, page_size=page_size)

    def create_review(self, review_data: Dict) -> str:
        review_id = review_data.get("id") or str(hash(str(review_data)))[:12]
        self.store.insert("reviews", review_id, review_data)
        return review_id

    # Coupon operations
    def get_coupon(self, code: str) -> Optional[Dict]:
        return self.store.find_by_id("coupons", code)

    def increment_coupon_usage(self, code: str) -> None:
        coupon = self.get_coupon(code)
        if coupon:
            self.store.update("coupons", code, {"current_uses": coupon["current_uses"] + 1})

    # Maintenance operations
    def run_maintenance(self) -> Dict[str, int]:
        """
        Run maintenance tasks.
        MEMORABLE: Purges soft-deleted records older than TOMBSTONE_RETENTION_DAYS (90 days).
        """
        results = {}
        for collection in ["products", "customers", "orders", "reviews"]:
            results[collection] = self.store.purge_tombstones(collection)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return {
            "connection_pool": self.pool.get_stats(),
            "collections": {
                name: len([r for r in coll.values() if r.get("_deleted_at") is None])
                for name, coll in self.store._data.items()
            }
        }
