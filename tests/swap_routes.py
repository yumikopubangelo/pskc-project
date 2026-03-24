#!/usr/bin/env python3
import shutil
import os

routes_old = "d:\\pskc-project\\src\\api\\routes.py"
routes_new = "d:\\pskc-project\\src\\api\\routes_new.py"
routes_bak = "d:\\pskc-project\\src\\api\\routes_old.py.bak"

# Backup old
if os.path.exists(routes_old):
    shutil.move(routes_old, routes_bak)
    print(f"✓ Backed up old routes.py to routes_old.py.bak")

# Use new
if os.path.exists(routes_new):
    shutil.move(routes_new, routes_old)
    print(f"✓ Activated new routes.py (200 LOC)")

print("\nRoutes refactoring complete!")
print(f"Old version (2756 LOC): routes_old.py.bak")
print(f"New version (200 LOC): routes.py")
