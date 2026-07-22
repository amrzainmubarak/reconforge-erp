"""Inspectable local module metadata for ReconForge runtime capabilities."""

from reconforge.modules.registry import (
    MODULE_REGISTRY_SCHEMA_VERSION,
    ModuleDescriptor,
    ModuleMaturity,
    ModuleRegistryError,
    RegistryValidationIssue,
    get_module,
    list_modules,
    registry_payload,
    validate_registry,
)

__all__ = [
    "MODULE_REGISTRY_SCHEMA_VERSION",
    "ModuleMaturity",
    "ModuleDescriptor",
    "ModuleRegistryError",
    "RegistryValidationIssue",
    "get_module",
    "list_modules",
    "registry_payload",
    "validate_registry",
]
