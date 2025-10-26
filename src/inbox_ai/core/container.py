"""Simple service container for dependency management."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")


class ServiceContainer:
    """Minimal dependency container with lazy singleton semantics."""

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[["ServiceContainer"], Any]] = {}
        self._instances: Dict[str, Any] = {}

    def register(self, key: str, factory: Callable[["ServiceContainer"], T]) -> None:
        """Register a factory under a given key."""

        self._factories[key] = factory

    def resolve(self, key: str) -> Any:
        """Resolve a dependency by key, invoking its factory once."""

        if key in self._instances:
            return self._instances[key]
        if key not in self._factories:
            msg = f"Service '{key}' is not registered"
            raise KeyError(msg)
        instance = self._factories[key](self)
        self._instances[key] = instance
        return instance

    def try_resolve(self, key: str) -> Optional[Any]:
        """Resolve a dependency if available; return None otherwise."""

        try:
            return self.resolve(key)
        except KeyError:
            return None

    def clear(self) -> None:
        """Clear cached singleton instances."""

        self._instances.clear()


__all__ = ["ServiceContainer"]
