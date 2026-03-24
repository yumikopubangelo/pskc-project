#!/usr/bin/env python3
"""Verify ML training endpoints are properly implemented."""

import sys

def check_route_training():
    """Check route_training.py endpoints."""
    with open('src/api/route_training.py') as f:
        content = f.read()
    
    checks = {
        'POST /generate': '@router.post("/generate")' in content,
        'GET /generate/estimate': '@router.get("/generate/estimate")' in content,
        'GET /collector/config': '@router.get("/collector/config")' in content,
    }
    
    print("Route Training Endpoints:")
    for name, present in checks.items():
        status = "✓" if present else "✗"
        print(f"  {status} {name}")
    
    return all(checks.values())

def check_data_collector():
    """Check data_collector.py modifications."""
    with open('src/ml/data_collector.py') as f:
        content = f.read()
    
    checks = {
        'AccessEvent data_source field': 'data_source: str' in content,
        'record_access data_source param': 'def record_access(' in content and 'data_source' in content,
        'import_events data_source param': 'def import_events(' in content and 'data_source' in content,
        'get_stats breakdown': 'data_source_breakdown' in content,
    }
    
    print("\nData Collector Modifications:")
    for name, present in checks.items():
        status = "✓" if present else "✗"
        print(f"  {status} {name}")
    
    return all(checks.values())

def check_settings():
    """Check settings.py configuration."""
    with open('config/settings.py') as f:
        content = f.read()
    
    checks = {
        'ml_collector_max_events = 500000': 'default=500000' in content,
        'ML_COLLECT_PRODUCTION_DATA': 'ML_COLLECT_PRODUCTION_DATA' in content,
        'ML_COLLECT_SIMULATION_DATA': 'ML_COLLECT_SIMULATION_DATA' in content,
    }
    
    print("\nSettings Configuration:")
    for name, present in checks.items():
        status = "✓" if present else "✗"
        print(f"  {status} {name}")
    
    return all(checks.values())

def check_ml_service():
    """Check ml_service.py."""
    with open('src/api/ml_service.py') as f:
        content = f.read()
    
    checks = {
        'import_events with data_source': 'import_events(' in content and 'data_source="simulation"' in content,
    }
    
    print("\nML Service Modifications:")
    for name, present in checks.items():
        status = "✓" if present else "✗"
        print(f"  {status} {name}")
    
    return all(checks.values())

if __name__ == '__main__':
    results = [
        check_route_training(),
        check_data_collector(),
        check_settings(),
        check_ml_service(),
    ]
    
    if all(results):
        print("\n✓ All implementation checks passed!")
        sys.exit(0)
    else:
        print("\n✗ Some implementation checks failed!")
        sys.exit(1)
