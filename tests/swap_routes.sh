#!/bin/bash
# Backup old routes.py and use the new one
cd d:\pskc-project
mv src\api\routes.py src\api\routes_old.py.bak
mv src\api\routes_new.py src\api\routes.py
echo "Routes refactoring complete!"
echo "Old routes (2756 LOC) backed up to routes_old.py.bak"
echo "New routes (200 LOC) now active as routes.py"
