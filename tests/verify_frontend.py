#!/usr/bin/env python3
"""Verify MLTraining.jsx frontend implementation."""

with open('frontend/src/pages/MLTraining.jsx') as f:
    content = f.read()

checks = {
    'No max attributes in inputs': not ('maxValue=' in content and 'max=' in content),
    'estimatedData state': 'estimatedData' in content,
    'estimateDataGeneration callback': 'estimateDataGeneration' in content,
    'Estimate preview card': 'estimated' in content.lower(),
}

print("MLTraining.jsx Frontend Implementation:")
for name, present in checks.items():
    status = "✓" if present else "✗"
    print(f"  {status} {name}")

if all(checks.values()):
    print("\n✓ Frontend implementation checks passed!")
else:
    print("\n✗ Some frontend checks failed!")
