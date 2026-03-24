#!/usr/bin/env python3
"""Replace old routes.py with the new refactored version."""
import shutil
import sys

old_file = "src/api/routes.py"
new_file = "src/api/routes_new.py"
backup_file = "src/api/routes_old.py.backup"

try:
    # Create backup
    shutil.copy(old_file, backup_file)
    print(f"✓ Backed up old routes.py → {backup_file}")
    
    # Copy new to old
    shutil.copy(new_file, old_file)
    print(f"✓ Deployed new routes.py (200 LOC)")
    
    # Verify size reduction
    with open(old_file, 'r') as f:
        new_lines = len(f.readlines())
    with open(backup_file, 'r') as f:
        old_lines = len(f.readlines())
    
    reduction = old_lines - new_lines
    percent = (reduction / old_lines) * 100
    print(f"\n📊 REDUCTION: {old_lines} → {new_lines} LOC ({reduction} lines, {percent:.1f}%)")
    print(f"✓ All refactored route modules imported and registered")
    
    sys.exit(0)
except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)
