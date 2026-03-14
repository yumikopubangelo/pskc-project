from pathlib import Path

from src.security.fips_module import FipsCryptographicModule
from src.security.tamper_evident_logger import TamperEvidentAuditLogger


def _build_fips_module() -> FipsCryptographicModule:
    return FipsCryptographicModule(b"\x01" * FipsCryptographicModule.AES_KEY_SIZE)


def _build_log_line(
    fips_module: FipsCryptographicModule,
    timestamp: str,
    user: str,
    action: str,
    outcome: str,
    previous_hash_hex: str,
) -> tuple[str, str]:
    log_content = f"{timestamp}|{user}|{action}|{outcome}|{previous_hash_hex}"
    current_hash = fips_module.hash_data(log_content.encode("utf-8"))
    signature = fips_module.sign_data(
        current_hash,
        TamperEvidentAuditLogger.LOG_SIGNING_KEY_LABEL,
    )
    return f"{log_content}|{signature.hex()}", current_hash.hex()


def test_audit_log_chain_survives_restart(tmp_path):
    log_dir = tmp_path / "logs"

    logger1 = TamperEvidentAuditLogger(_build_fips_module(), str(log_dir), allow_recovery=False)
    logger1.log("SYSTEM", "APP_STARTUP", "SUCCESS")

    logger2 = TamperEvidentAuditLogger(_build_fips_module(), str(log_dir), allow_recovery=False)
    logger2.log("SYSTEM", "APP_SHUTDOWN", "SUCCESS")

    log_lines = (log_dir / "pskc_audit.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 3
    assert not list(log_dir.glob("pskc_audit_corrupt_*.log"))


def test_audit_log_recovery_starts_a_valid_new_chain(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pskc_audit.log"
    log_path.write_text("corrupt-line\n", encoding="utf-8")

    recovered_logger = TamperEvidentAuditLogger(_build_fips_module(), str(log_dir), allow_recovery=True)
    recovered_logger.log("SYSTEM", "APP_STARTUP", "SUCCESS")

    backup_logs = list(log_dir.glob("pskc_audit_corrupt_*.log"))
    assert len(backup_logs) == 1

    reopened_logger = TamperEvidentAuditLogger(_build_fips_module(), str(log_dir), allow_recovery=False)
    reopened_logger.log("SYSTEM", "APP_SHUTDOWN", "SUCCESS")

    log_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 3


def test_audit_log_accepts_legacy_zero_hash_second_entry_without_recovery(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pskc_audit.log"
    fips_module = _build_fips_module()

    line1, _ = _build_log_line(
        fips_module,
        "2026-03-11T12:00:00+00:00",
        "SYSTEM",
        "LOG_START",
        "SUCCESS",
        "0" * 64,
    )
    line2, line2_hash = _build_log_line(
        fips_module,
        "2026-03-11T12:00:01+00:00",
        "SYSTEM",
        "APP_STARTUP",
        "SUCCESS",
        "0" * 64,
    )
    line3, _ = _build_log_line(
        fips_module,
        "2026-03-11T12:00:02+00:00",
        "SYSTEM",
        "APP_SHUTDOWN",
        "SUCCESS",
        line2_hash,
    )
    log_path.write_text(f"{line1}\n{line2}\n{line3}\n", encoding="utf-8")

    reopened_logger = TamperEvidentAuditLogger(_build_fips_module(), str(log_dir), allow_recovery=False)
    reopened_logger.log("SYSTEM", "APP_STARTUP", "SUCCESS")

    assert not list(log_dir.glob("pskc_audit_corrupt_*.log"))
