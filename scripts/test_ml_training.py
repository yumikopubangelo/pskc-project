#!/usr/bin/env python3
# PSKC ML Training End-to-End Test Suite
# Test all ML training features

import httpx
import json
import time
from typing import Dict, Any

API_BASE = "http://localhost:8000"

def test_ml_training_workflow(client: httpx.Client) -> Dict[str, Any]:
    """Test complete ML training workflow"""
    results = {"success": True, "steps": []}
    
    try:
        # Step 1: Import data       print("1. Importing seed data...")
        resp = client.post(f"{API_BASE}/ml/data/import", timeout=30.0)
        if resp.status_code != 200:
            print(f"   Status: {resp.status_code}, Error: {resp.text[:200]}")
        results["steps"].append({"step": "import_data", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}, Imported: {resp.json().get('imported_events', 0)}")
        
        time.sleep(2)
        
        # Step 2: Check status
        print("2. Checking ML status...")
        resp = client.get(f"{API_BASE}/ml/status", timeout=10.0)
        results["steps"].append({"step": "check_status", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}, {resp.json()}")
        
        # Step 3: Generate training data
        print("3. Generating training data...")
        params = {
            "num_events": 100,  # Minimum
            "num_keys": 10,
            "num_services": 3,
            "scenario": "dynamic",
            "traffic_profile": "normal",
            "duration_hours": 1
        }
        resp = client.post(f"{API_BASE}/ml/training/generate", params=params, timeout=60.0)
        if resp.status_code != 200:
            print(f"   Status: {resp.status_code}, Error: {resp.text[:200]}")
        results["steps"].append({"step": "generate_data", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}, Events: {resp.json().get('events_generated', 'N/A')}")
        
        time.sleep(2)
        
        # Step 4: Train model
        print("4. Training model...")
        resp = client.post(f"{API_BASE}/ml/training/train?force=true&reason=test", timeout=120.0)
        results["steps"].append({"step": "train_model", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}, {resp.json().get('success', False)}")
        
        # Step 5: Check predictions
        print("5. Testing predictions...")
        resp = client.get(f"{API_BASE}/ml/predictions?n=5", timeout=10.0)
        results["steps"].append({"step": "predictions", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}, Predictions: {len(resp.json().get('predictions', []))}")
        
        # Step 6: ML diagnostics
        print("6. ML diagnostics...")
        resp = client.get(f"{API_BASE}/ml/diagnostics", timeout=10.0)
        results["steps"].append({"step": "diagnostics", "status": resp.status_code == 200})
        print(f"   Status: {resp.status_code}")
        
        results["overall"] = all(step["status"] for step in results["steps"])
        
    except httpx.TimeoutException as e:
        print(f"Timeout: {e}")
        results["success"] = False
        results["error"] = "timeout"
    except Exception as e:
        print(f"Test failed: {e}")
        results["success"] = False
        results["error"] = str(e)
    
    return results

def main():
    with httpx.Client(timeout=30.0, base_url=API_BASE) as client:
        print("PSKC ML Training E2E Test Suite")
        print("=" * 50)
        
        # Health check first
        try:
            resp = client.get("/health")
            print(f"Backend health: {resp.status_code} - {resp.json().get('status')}")
            if resp.status_code != 200:
                print("Backend unhealthy - aborting")
                return
        except Exception as e:
            print(f"Cannot connect to backend: {e}")
            return
        
        # Run full test
        result = test_ml_training_workflow(client)
        
        print("\n" + "=" * 50)
        print("TEST RESULTS")
        print("=" * 50)
        print(f"Overall success: {'✅ PASS' if result['success'] else '❌ FAIL'}")
        if "error" in result:
            print(f"Error: {result['error']}")
        
        for step in result["steps"]:
            status = "✅" if step["status"] else "❌"
            print(f"{status} {step['step']}")

if __name__ == "__main__":
    main()

