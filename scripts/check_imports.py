#!/usr/bin/env python3
"""Check for circular imports in the doxtr_doto package.

This script attempts to import all modules in the doxtr_doto package
to detect any circular import issues at import time. It's designed to
be run as part of CI to catch import cycles early.

Usage:
    python scripts/check_imports.py [package_name]

    The package name defaults to "doxtr_doto" when omitted, so a fork or child
    project can repoint the check without editing this source.

Exit codes:
    0 - All imports successful, no circular imports detected
    1 - Import error or circular import detected
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path


def discover_modules(package_name: str) -> list[str]:
    """Discover all modules in a package recursively.

    Args:
        package_name: Name of the package to scan.

    Returns:
        List of fully qualified module names.
    """
    try:
        package = importlib.import_module(package_name)
    except ImportError as e:
        print(f"✗ Cannot import base package {package_name}: {e}")
        return []

    modules = [package_name]

    if not hasattr(package, "__path__"):
        return modules

    for importer, modname, ispkg in pkgutil.walk_packages(
        package.__path__, prefix=f"{package_name}."
    ):
        modules.append(modname)

    return modules


def check_imports(package_name: str) -> tuple[int, int]:
    """Check all imports in a package for circular import issues.

    Args:
        package_name: Name of the package to check.

    Returns:
        Tuple of (successful_count, failed_count).
    """
    modules = discover_modules(package_name)

    if not modules:
        return 0, 1

    success = 0
    failed = 0

    for module_name in sorted(modules):
        try:
            importlib.import_module(module_name)
            print(f"✓ {module_name}")
            success += 1
        except ImportError as e:
            print(f"✗ {module_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {module_name}: {type(e).__name__}: {e}")
            failed += 1

    return success, failed


def main() -> int:
    """Main entry point.

    Reads an optional package name from ``sys.argv[1]`` (default ``doxtr_doto``)
    so forks can repoint the check without editing this source.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    package_name = sys.argv[1] if len(sys.argv) > 1 else "doxtr_doto"

    print(f"Checking for circular imports in {package_name}...\n")

    # Add src to path if running from project root
    src_path = Path(__file__).parent.parent / "src"
    if src_path.exists() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    success, failed = check_imports(package_name)

    print(f"\n{'=' * 50}")
    print(f"Results: {success} passed, {failed} failed")

    if failed > 0:
        print("\n✗ Import cycle check FAILED")
        return 1

    print("\n✓ No circular imports detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
