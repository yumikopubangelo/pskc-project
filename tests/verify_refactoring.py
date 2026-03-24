#!/usr/bin/env python3
"""
Verify routes.py refactoring imports and structure
"""
import sys
import os

# Add project to path
sys.path.insert(0, 'd:\\pskc-project')

print("=" * 60)
print("Verifying Routes.py Refactoring")
print("=" * 60)

# Test 1: Check if all helper modules can be imported
print("\n1. Testing helper module imports...")
try:
    from src.api.route_health import create_health_router, get_startup_state
    print("   ✓ route_health imports successful")
except ImportError as e:
    print(f"   ✗ route_health import failed: {e}")
    sys.exit(1)

try:
    from src.api.route_keys import create_key_router, get_metrics_storage
    print("   ✓ route_keys imports successful")
except ImportError as e:
    print(f"   ✗ route_keys import failed: {e}")
    sys.exit(1)

try:
    from src.api.route_metrics import create_metrics_router
    print("   ✓ route_metrics imports successful")
except ImportError as e:
    print(f"   ✗ route_metrics import failed: {e}")
    sys.exit(1)

try:
    from src.api.route_prefetch import create_prefetch_router
    print("   ✓ route_prefetch imports successful")
except ImportError as e:
    print(f"   ✗ route_prefetch import failed: {e}")
    sys.exit(1)

# Test 2: Verify routers can be created
print("\n2. Testing router creation...")
try:
    health_router = create_health_router()
    print(f"   ✓ Health router created ({len(health_router.routes)} routes)")
except Exception as e:
    print(f"   ✗ Health router creation failed: {e}")
    sys.exit(1)

try:
    keys_router = create_key_router()
    print(f"   ✓ Keys router created ({len(keys_router.routes)} routes)")
except Exception as e:
    print(f"   ✗ Keys router creation failed: {e}")
    sys.exit(1)

try:
    metrics_router = create_metrics_router()
    print(f"   ✓ Metrics router created ({len(metrics_router.routes)} routes)")
except Exception as e:
    print(f"   ✗ Metrics router creation failed: {e}")
    sys.exit(1)

try:
    prefetch_router = create_prefetch_router()
    print(f"   ✓ Prefetch router created ({len(prefetch_router.routes)} routes)")
except Exception as e:
    print(f"   ✗ Prefetch router creation failed: {e}")
    sys.exit(1)

# Test 3: Verify shared state functions
print("\n3. Testing shared state functions...")
try:
    startup_state = get_startup_state()
    assert isinstance(startup_state, dict)
    print(f"   ✓ Startup state accessible: {list(startup_state.keys())}")
except Exception as e:
    print(f"   ✗ Startup state access failed: {e}")
    sys.exit(1)

try:
    metrics = get_metrics_storage()
    assert isinstance(metrics, dict)
    print(f"   ✓ Metrics storage accessible: {list(metrics.keys())}")
except Exception as e:
    print(f"   ✗ Metrics storage access failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ All refactoring validations passed!")
print("=" * 60)
