"""Dependency Injection Container for dtstylekit.

Provides a lightweight IoC container for managing dependencies and
their lifecycles. Supports singleton and transient registrations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")


class DIContainer:
    """Simple dependency injection container.

    Supports:
    - Singleton registration (same instance returned every time)
    - Transient registration (new instance every time)
    - Factory registration (custom creation logic)
    - Interface-to-implementation binding
    """

    def __init__(self) -> None:
        self._singletons: dict[type, Any] = {}
        self._transients: dict[type, Callable[[], Any]] = {}
        self._factories: dict[type, Callable[[DIContainer], Any]] = {}
        self._interface_bindings: dict[type, type] = {}

    def register_singleton(self, interface: type[T], implementation: type[T]) -> None:
        """Register a singleton implementation for an interface.

        Args:
            interface: The interface/abstract class.
            implementation: The concrete implementation class.
        """
        self._interface_bindings[interface] = implementation
        # Don't create instance yet - lazy initialization

    def register_transient(self, interface: type[T], implementation: type[T]) -> None:
        """Register a transient implementation for an interface.

        A new instance is created every time resolve() is called.

        Args:
            interface: The interface/abstract class.
            implementation: The concrete implementation class.
        """
        self._transients[interface] = implementation

    def register_factory(self, interface: type[T], factory: Callable[[DIContainer], T]) -> None:
        """Register a factory function for an interface.

        Args:
            interface: The interface/abstract class.
            factory: Callable that takes the container and returns an instance.
        """
        self._factories[interface] = factory

    def register_instance(self, interface: type[T], instance: T) -> None:
        """Register a pre-created instance as a singleton.

        Args:
            interface: The interface/abstract class.
            instance: Pre-created instance.
        """
        self._singletons[interface] = instance

    def bind(self, interface: type[T], implementation: type[T]) -> None:
        """Bind an interface to an implementation (singleton by default).

        Args:
            interface: The interface/abstract class.
            implementation: The concrete implementation class.
        """
        self.register_singleton(interface, implementation)

    def resolve(self, interface: type[T] | str) -> T:
        """Resolve an interface to its implementation.

        Args:
            interface: The interface/abstract class or string key to resolve.

        Returns:
            An instance of the registered implementation.

        Raises:
            KeyError: If no registration exists for the interface.
        """
        # Handle string-based resolution for use cases
        if isinstance(interface, str):
            return cast(T, self._resolve_by_name(interface))

        # Check for pre-registered instance
        if interface in self._singletons:
            return cast(T, self._singletons[interface])

        # Check for factory
        if interface in self._factories:
            instance = self._factories[interface](self)
            return cast(T, instance)

        # Check for transient
        if interface in self._transients:
            return cast(T, self._transients[interface]())

        # Check for interface binding (singleton)
        if interface in self._interface_bindings:
            impl = self._interface_bindings[interface]
            instance = impl()
            self._singletons[interface] = instance
            return cast(T, instance)

        # Try to instantiate directly if it's a concrete class
        try:
            instance = interface()
            self._singletons[interface] = instance
            return cast(T, instance)
        except TypeError:
            pass

        raise KeyError(
            f"No registration found for {interface.__name__}. "
            f"Available: {list(self._interface_bindings.keys()) + list(self._transients.keys()) + list(self._factories.keys())}"
        )

    def _resolve_by_name(self, name: str) -> Any:
        """Resolve by string name (for use cases registered by name)."""
        # Map common use case names to their types
        name_map = {
            "dtstylekit.use_cases.GenerateStyleUseCase": "GenerateStyleUseCase",
            "dtstylekit.use_cases.SearchPresetsUseCase": "SearchPresetsUseCase",
            "dtstylekit.use_cases.IndexPresetsUseCase": "IndexPresetsUseCase",
            "dtstylekit.use_cases.ValidateStyleUseCase": "ValidateStyleUseCase",
            "dtstylekit.use_cases.RefineStyleUseCase": "RefineStyleUseCase",
        }
        short_name = name_map.get(name, name)

        # Try to find in singletons by class name
        for key, instance in self._singletons.items():
            if key.__name__ == short_name or str(key) == name:
                return instance

        # Try factories
        for key, factory in self._factories.items():
            if key.__name__ == short_name or str(key) == name:
                instance = factory(self)
                self._singletons[key] = instance
                return instance

        raise KeyError(f"No registration found for {name}")

    def try_resolve(self, interface: type[T]) -> T | None:
        """Try to resolve an interface, returning None if not found.

        Args:
            interface: The interface/abstract class to resolve.

        Returns:
            Instance or None if not registered.
        """
        try:
            return self.resolve(interface)
        except KeyError:
            return None

    def is_registered(self, interface: type) -> bool:
        """Check if an interface is registered.

        Args:
            interface: The interface to check.

        Returns:
            True if registered, False otherwise.
        """
        return (
            interface in self._singletons
            or interface in self._transients
            or interface in self._factories
            or interface in self._interface_bindings
        )

    def clear(self) -> None:
        """Clear all registrations."""
        self._singletons.clear()
        self._transients.clear()
        self._factories.clear()
        self._interface_bindings.clear()

    def create_child_container(self) -> DIContainer:
        """Create a child container that inherits registrations.

        Returns:
            New DIContainer with copied registrations.
        """
        child = DIContainer()
        child._singletons = self._singletons.copy()
        child._transients = self._transients.copy()
        child._factories = self._factories.copy()
        child._interface_bindings = self._interface_bindings.copy()
        return child


# Global container instance
_container: DIContainer | None = None


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    global _container
    if _container is None:
        _container = DIContainer()
    return _container


def configure_container() -> DIContainer:
    """Configure and return the global container with all bindings."""
    container = get_container()
    # Bindings will be registered by individual modules via configure_services()
    return container
