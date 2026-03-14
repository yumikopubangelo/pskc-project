import secrets

from src.security.fips_module import FipsCryptographicModule
from src.security.fips_self_tests import run_power_on_self_tests


def test_run_power_on_self_tests_passes_with_runtime_module():
    fips_module = FipsCryptographicModule(
        secrets.token_bytes(FipsCryptographicModule.AES_KEY_SIZE)
    )

    try:
        run_power_on_self_tests(fips_module)
    finally:
        fips_module.destroy()
