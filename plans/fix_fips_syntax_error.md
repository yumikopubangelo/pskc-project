# Fix Plan: Syntax Error in fips_module.py

## Problem
The API fails to start with a syntax error in `src/security/fips_module.py` at line 242. The error is caused by HTML-style comments (`<!-- COMMENT: ... -->`) being used inside Python docstrings, which Python cannot parse.

## Root Cause
The file contains comments like:
```python
"""
<!-- COMMENT: This is a comment -->
"""
```

This is invalid Python syntax because the `<!--` and `-->` are not valid Python comment markers.

## Solution
Replace all HTML-style comments (`<!-- COMMENT: ... -->`) inside docstrings with standard Python comments (`# ...`).

## Affected Locations in fips_module.py
The HTML comments appear in the following lines (approximate):
- Line 73-76: Inside `__init__` docstring
- Line 99-101: Inside `encrypt_data` docstring
- Line 141-145: Inside `generate_random_bytes` docstring
- Line 158-164: Inside `sign_data` docstring
- Line 198-201: Inside `derive_key_from_password` docstring
- Line 238-242: Inside `destroy` docstring

## Action Items
1. Replace all `<!-- COMMENT:` with `#` in docstrings
2. Replace all `-->` with nothing in docstrings
3. Verify the file can be imported without syntax errors
4. Start the API to confirm it works
