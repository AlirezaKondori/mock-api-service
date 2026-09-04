from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Product:
    id: str
    unified_id: str
    title: str
    source: str
    price: float
    category: str


@dataclass(frozen=True)
class RejectedRecord:
    source: str
    reason: str
    raw: dict[str, Any]


@dataclass
class SourceResult:
    source: str
    status: str  # "success" | "degraded" | "failed"
    products: list[Product] = field(default_factory=list)
    rejected: list[RejectedRecord] = field(default_factory=list)
    pages_fetched: int = 0
    retries: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
