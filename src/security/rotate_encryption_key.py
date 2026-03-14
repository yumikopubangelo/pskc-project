#!/usr/bin/env python3
# ============================================================
# PSKC — Encryption Key Rotation (FILE BARU)
# scripts/rotate_encryption_key.py
# ============================================================
#
# Key rotation adalah salah satu kontrol keamanan paling kritis
# untuk sistem yang menyimpan key material terenkripsi.
#
# KENAPA PERLU KEY ROTATION:
#   - Batas kriptografis AES-GCM: setelah 2^32 enkripsi dengan key
#     yang sama, nonce space mulai exhausted (birthday bound)
#   - Jika key bocor (mis: insider threat), data historis ikut bocor
#   - Compliance: PCI-DSS, SOC2, ISO 27001 mensyaratkan periodic rotation
#   - Principle of least exposure: minimize window of key compromise
#
# CARA PAKAI:
#   python scripts/rotate_encryption_key.py --new-key $NEW_KEY
#   python scripts/rotate_encryption_key.py --generate     # auto-generate key
#   python scripts/rotate_encryption_key.py --dry-run      # preview tanpa eksekusi
#
# ZERO-DOWNTIME PROCESS:
#   1. Generate new key
#   2. Re-encrypt semua cache entries dengan new key
#   3. Atomic swap: new key aktif
#   4. Zero-out old key dari memory
#   5. Update env var (manual step, diinstruksikan di akhir)
# ============================================================

import sys
import os
import json
import time
import secrets
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("key_rotation")


# ============================================================
# Key Rotation Manager
# ============================================================

class KeyRotationManager:
    """
    Orchestrates zero-downtime encryption key rotation.

    Process:
        1. Load old encryptor (current active key)
        2. Create new encryptor dengan key baru
        3. Re-encrypt semua data dari old → new
        4. Swap encryptor secara atomic
        5. Zero-out old key
        6. Write rotation audit log
    """

    AUDIT_LOG_PATH = "data/security/key_rotation_audit.jsonl"

    def __init__(
        self,
        old_raw_key: str,
        new_raw_key: str,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self._rotation_id = secrets.token_hex(8)
        self._start_time = datetime.now(timezone.utc)

        # Import setelah path setup
        from src.security.encryption import AES256GCMEncryptor, KeyDerivation

        # Derive proper keys via HKDF
        old_key = KeyDerivation.derive_from_secret(
            old_raw_key, info="pskc-cache-encryption-key-v1"
        )
        new_key = KeyDerivation.derive_from_secret(
            new_raw_key, info="pskc-cache-encryption-key-v1"
        )

        self._old_enc = AES256GCMEncryptor(old_key)
        self._new_enc = AES256GCMEncryptor(new_key)
        self._new_raw_key = new_raw_key

        logger.info(
            f"KeyRotationManager initialized "
            f"[rotation_id={self._rotation_id}, dry_run={dry_run}]"
        )

    def rotate(self) -> Dict:
        """
        Execute full key rotation.

        Returns:
            Rotation report dict dengan stats dan status.
        """
        logger.info("=" * 60)
        logger.info("  PSKC Encryption Key Rotation")
        logger.info(f"  Rotation ID : {self._rotation_id}")
        logger.info(f"  Dry run     : {self.dry_run}")
        logger.info("=" * 60)

        report = {
            "rotation_id":     self._rotation_id,
            "started_at":      self._start_time.isoformat(),
            "dry_run":         self.dry_run,
            "entries_found":   0,
            "entries_success": 0,
            "entries_failed":  0,
            "errors":          [],
            "status":          "pending",
        }

        try:
            # Step 1: Collect all encrypted entries
            entries = self._collect_cache_entries()
            report["entries_found"] = len(entries)
            logger.info(f"Found {len(entries)} cache entries to re-encrypt")

            if not entries:
                logger.info("No entries to rotate. Key rotation complete (no-op).")
                report["status"] = "completed_noop"
                self._write_audit(report)
                return report

            # Step 2: Re-encrypt each entry
            reencrypted: List[Tuple[str, str]] = []

            for key_id, old_ciphertext in entries:
                try:
                    # Decrypt dengan old key
                    plaintext = self._old_enc.decrypt_from_token(old_ciphertext)

                    # Re-encrypt dengan new key
                    new_ciphertext = self._new_enc.encrypt_to_token(plaintext)

                    reencrypted.append((key_id, new_ciphertext))
                    report["entries_success"] += 1

                    # Zero-out plaintext setelah pakai
                    plaintext_arr = bytearray(plaintext)
                    for i in range(len(plaintext_arr)):
                        plaintext_arr[i] = 0

                except Exception as e:
                    logger.error(f"Failed to re-encrypt entry {key_id!r}: {e}")
                    report["entries_failed"] += 1
                    report["errors"].append({"key_id": key_id, "error": str(e)})

            logger.info(
                f"Re-encryption complete: "
                f"{report['entries_success']} ok, "
                f"{report['entries_failed']} failed"
            )

            if report["entries_failed"] > 0:
                logger.warning(
                    f"{report['entries_failed']} entries failed to re-encrypt. "
                    f"Old key will NOT be rotated to preserve data integrity."
                )
                report["status"] = "partial_failure"
                self._write_audit(report)
                return report

            # Step 3: Commit (write new ciphertexts)
            if not self.dry_run:
                committed = self._commit_reencrypted(reencrypted)
                if not committed:
                    report["status"] = "commit_failed"
                    self._write_audit(report)
                    return report

                # Step 4: Swap active encryptor
                self._swap_global_encryptor()

            # Step 5: Destroy old key from memory
            self._old_enc.destroy()

            report["completed_at"] = datetime.now(timezone.utc).isoformat()
            report["status"] = "completed" if not self.dry_run else "dry_run_ok"

            self._print_completion_instructions()

        except Exception as e:
            logger.error(f"Key rotation failed: {e}", exc_info=True)
            report["status"] = "failed"
            report["errors"].append({"phase": "rotation", "error": str(e)})

        self._write_audit(report)

        logger.info(f"\nRotation status: {report['status'].upper()}")
        return report

    # ----------------------------------------------------------
    # Cache Entry Collection
    # ----------------------------------------------------------

    def _collect_cache_entries(self) -> List[Tuple[str, str]]:
        """
        Collect all encrypted entries from local cache.
        Returns list of (key_id, encrypted_token) tuples.
        """
        try:
            from src.cache.local_cache import get_cache
            cache = get_cache()

            # LocalCache perlu expose method untuk enumerate keys
            # Implementasi ini tergantung backend cache
            if hasattr(cache, "_store"):
                # In-memory store
                entries = []
                for cache_key, value in cache._store.items():
                    if isinstance(value, str) and len(value) > 30:
                        # Heuristic: nilai yang panjang kemungkinan ciphertext
                        entries.append((cache_key, value))
                return entries
            else:
                logger.warning(
                    "Cache backend tidak mendukung enumerate keys. "
                    "Re-encryption di-skip (keys akan expired dan di-re-cache dengan key baru)."
                )
                return []

        except Exception as e:
            logger.warning(f"Could not collect cache entries: {e}")
            return []

    def _commit_reencrypted(self, entries: List[Tuple[str, str]]) -> bool:
        """Write re-encrypted entries back to cache."""
        try:
            from src.cache.local_cache import get_cache
            cache = get_cache()

            for key_id, new_ciphertext in entries:
                if hasattr(cache, "_store"):
                    cache._store[key_id] = new_ciphertext

            logger.info(f"Committed {len(entries)} re-encrypted entries to cache")
            return True
        except Exception as e:
            logger.error(f"Failed to commit re-encrypted entries: {e}")
            return False

    def _swap_global_encryptor(self) -> None:
        """Atomic swap of global encryptor instance."""
        try:
            import src.security.encryption as enc_module
            import threading

            with enc_module._encryptor_lock:
                old = enc_module._encryptor_instance
                enc_module._encryptor_instance = self._new_enc
                if old and old is not self._new_enc:
                    old.destroy()

            logger.info("Global encryptor swapped atomically")
        except Exception as e:
            logger.error(f"Failed to swap global encryptor: {e}")
            raise

    # ----------------------------------------------------------
    # Audit Logging
    # ----------------------------------------------------------

    def _write_audit(self, report: Dict) -> None:
        """Write rotation report to append-only audit log."""
        try:
            os.makedirs(os.path.dirname(self.AUDIT_LOG_PATH), exist_ok=True)
            with open(self.AUDIT_LOG_PATH, "a") as f:
                f.write(json.dumps(report) + "\n")
            logger.info(f"Audit log written: {self.AUDIT_LOG_PATH}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    # ----------------------------------------------------------
    # Instructions
    # ----------------------------------------------------------

    def _print_completion_instructions(self) -> None:
        new_key_preview = self._new_raw_key[:8] + "..." + self._new_raw_key[-4:]
        print("\n" + "=" * 60)
        print("  KEY ROTATION COMPLETE")
        print("=" * 60)
        print(f"\n  Rotation ID : {self._rotation_id}")
        print(f"  New key     : {new_key_preview}")
        print("\n  ACTION REQUIRED:")
        print("  Update CACHE_ENCRYPTION_KEY di environment variable:")
        print(f"\n    export CACHE_ENCRYPTION_KEY='{self._new_raw_key}'")
        print("\n  Atau update di .env file dan restart service.")
        print("\n  JANGAN simpan key ini di source code atau log!")
        print("=" * 60 + "\n")


# ============================================================
# Key Generation Helper
# ============================================================

def generate_secure_key() -> str:
    """
    Generate cryptographically secure 256-bit key sebagai hex string.
    Equivalent dengan: openssl rand -hex 32
    """
    return secrets.token_hex(32)


def validate_key_strength(key: str) -> Tuple[bool, str]:
    """
    Validate bahwa key memenuhi minimum entropy requirements.

    Returns:
        (is_valid, message)
    """
    if len(key) < 32:
        return False, f"Key terlalu pendek: {len(key)} chars (minimum 32)"

    # Check entropy: tidak boleh semua karakter sama
    if len(set(key)) < 8:
        return False, "Key memiliki entropy terlalu rendah (terlalu banyak karakter berulang)"

    # Check bukan default keys yang umum
    weak_patterns = ["dev_key", "test_key", "secret", "password", "changeme"]
    key_lower = key.lower()
    for p in weak_patterns:
        if p in key_lower:
            return False, f"Key mengandung pola lemah: '{p}'"

    return True, "Key memenuhi minimum strength requirements"


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="PSKC Encryption Key Rotation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-generate new key dan rotate
  python scripts/rotate_encryption_key.py --generate

  # Gunakan key spesifik
  python scripts/rotate_encryption_key.py --new-key <64-char-hex>

  # Preview tanpa eksekusi
  python scripts/rotate_encryption_key.py --generate --dry-run
        """,
    )

    parser.add_argument(
        "--new-key",
        type=str,
        default=None,
        help="New encryption key (hex string, min 32 chars)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Auto-generate a cryptographically secure new key",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate rotation without writing any changes",
    )
    parser.add_argument(
        "--old-key",
        type=str,
        default=None,
        help="Current encryption key (default: read from CACHE_ENCRYPTION_KEY env var)",
    )

    args = parser.parse_args()

    # ── Resolve old key ─────────────────────────────────────
    old_key = args.old_key or os.environ.get("CACHE_ENCRYPTION_KEY")
    if not old_key:
        logger.error(
            "Old key tidak ditemukan. Set CACHE_ENCRYPTION_KEY env var "
            "atau gunakan --old-key."
        )
        sys.exit(1)

    # ── Resolve new key ─────────────────────────────────────
    if args.generate:
        new_key = generate_secure_key()
        logger.info(f"Generated new key (first 8 chars): {new_key[:8]}...")
    elif args.new_key:
        new_key = args.new_key
    else:
        logger.error("Harus menyediakan --new-key atau --generate")
        sys.exit(1)

    # ── Validate new key ────────────────────────────────────
    valid, msg = validate_key_strength(new_key)
    if not valid:
        logger.error(f"New key validation failed: {msg}")
        sys.exit(1)

    logger.info(f"Key validation: {msg}")

    # ── Confirm (non-dry-run) ────────────────────────────────
    if not args.dry_run:
        confirm = input("\n⚠️  Key rotation akan memodifikasi cache. Lanjutkan? (yes/no): ")
        if confirm.strip().lower() != "yes":
            logger.info("Rotation dibatalkan.")
            sys.exit(0)

    # ── Execute ──────────────────────────────────────────────
    manager = KeyRotationManager(
        old_raw_key=old_key,
        new_raw_key=new_key,
        dry_run=args.dry_run,
    )

    report = manager.rotate()

    # Exit code berdasarkan status
    success_statuses = {"completed", "completed_noop", "dry_run_ok"}
    sys.exit(0 if report["status"] in success_statuses else 1)


if __name__ == "__main__":
    main()