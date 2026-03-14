# =================================================================
# TAMPER-EVIDENT AUDIT LOGGER
# =================================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# TUJUAN:
# Kelas `TamperEvidentAuditLogger` ini menggantikan logger audit
# in-memory yang lama. Tujuannya adalah untuk membuat log yang
# memenuhi persyaratan FIPS 140-2 dan NIST SP 800-53 (AU-9),
# yaitu melindungi informasi audit dari modifikasi yang tidak sah.
#
# ARSITEKTUR:
# Logger ini menggunakan dua mekanisme utama:
# 1. HASH CHAINING: Setiap entri log berisi hash dari entri sebelumnya.
#    Ini menciptakan rantai kriptografi (mirip blockchain sederhana).
#    Jika satu entri diubah atau dihapus, hash dari entri berikutnya
#    tidak akan cocok, sehingga kerusakan rantai dapat dideteksi.
#
# 2. DIGITAL SIGNATURES: Setiap entri (termasuk hash-nya) ditandatangani
#    secara digital menggunakan kunci yang dikelola oleh FipsCryptographicModule.
#    Ini membuktikan bahwa entri log dibuat oleh sistem yang sah dan
#    tidak diubah setelah dibuat.
#
# KETERGANTUNGAN:
# Logger ini secara eksplisit bergantung pada `FipsCryptographicModule`.
# Ini memastikan bahwa operasi penandatanganan yang kritis terhadap
# keamanan dilakukan di dalam boundary FIPS yang telah ditentukan.

import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Impor modul FIPS yang menjadi boundary kriptografi
from src.security.fips_module import FipsCryptographicModule

logger = logging.getLogger(__name__)


class TamperEvidentAuditLogger:
    """
    Mencatat peristiwa keamanan ke file log yang dilindungi secara kriptografis.
    """
    LOG_SIGNING_KEY_LABEL = "audit-log-signing-key-v1"

    def __init__(self, fips_module: FipsCryptographicModule, log_directory: str, allow_recovery: bool = True):
        """
        Inisialisasi logger.

        Args:
            fips_module: Instance dari modul kriptografi FIPS yang aktif.
            log_directory: Direktori untuk menyimpan file log.
            allow_recovery: If True, attempts to recover from a corrupt log file by backing it up and starting fresh.
        """
        self._fips_module = fips_module
        self._log_path = Path(log_directory) / "pskc_audit.log"
        self._allow_recovery = allow_recovery
        self._last_hash = self._initialize_log_file()
        logger.info(f"TamperEvidentAuditLogger initialized. Log file at: {self._log_path}")

    def _initialize_log_file(self) -> bytes:
        """
        Siapkan file log. Jika file sudah ada, verifikasi integritasnya
        dan kembalikan hash dari entri terakhir. Jika tidak, buat file baru.
        Jika file corrupt dan recovery diizinkan, backup file corrupt dan buat baru.
        """
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._log_path.exists():
            # Ini adalah file log baru, buat entri pertama (genesis record)
            genesis_hash = b'\x00' * 32
            self._write_log_entry("SYSTEM", "LOG_START", "SUCCESS", genesis_hash)
            return self._last_hash
        else:
            # File sudah ada, verifikasi seluruh rantai hash
            try:
                return self._verify_log_chain()
            except IOError as e:
                # Log corrupt - coba recovery jika diizinkan
                if self._allow_recovery:
                    logger.warning(f"Audit log corrupt: {e}. Attempting recovery...")
                    return self._recover_from_corruption()
                else:
                    # Re-raise exception jika recovery tidak diizinkan
                    raise

    def _verify_log_chain(self) -> bytes:
        """
        Verifikasi integritas seluruh file log saat startup.
        Membaca setiap baris, menghitung ulang hash, dan membandingkannya.
        """
        logger.debug("Verifying integrity of existing audit log chain...")
        last_valid_hash = b'\x00' * 32
        zero_hash_hex = last_valid_hash.hex()
        previous_action: Optional[str] = None
        verified_entries = 0
        with open(self._log_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('|')
                if len(parts) != 6:
                    raise IOError(f"CRITICAL: Audit log corrupt at line {i+1}. Invalid format.")

                timestamp, user, action, outcome, previous_hash_hex, signature_hex = parts
                
                # Verifikasi hash chain
                log_content_for_hash = f"{timestamp}|{user}|{action}|{outcome}|{previous_hash_hex}".encode('utf-8')

                legacy_genesis_compat = (
                    verified_entries == 1
                    and previous_hash_hex == zero_hash_hex
                    and previous_action in {"LOG_START", "LOG_RECOVERY"}
                    and last_valid_hash.hex() != zero_hash_hex
                )

                if previous_hash_hex != last_valid_hash.hex() and not legacy_genesis_compat:
                    raise IOError(f"CRITICAL: Audit log corrupt at line {i+1}. Hash chain broken!")
                if legacy_genesis_compat:
                    logger.warning(
                        "Detected legacy audit log chain bug at line %s; accepting compatibility path.",
                        i + 1,
                    )
                
                # Verifikasi tanda tangan
                current_hash = self._fips_module.hash_data(log_content_for_hash)
                signature = bytes.fromhex(signature_hex)
                
                if not self._fips_module.verify_signature(signature, current_hash, self.LOG_SIGNING_KEY_LABEL):
                    raise IOError(f"CRITICAL: Audit log corrupt at line {i+1}. Invalid signature!")
                
                last_valid_hash = current_hash
                previous_action = action
                verified_entries += 1
        
        logger.info("Audit log chain integrity verified successfully.")
        return last_valid_hash

    def _recover_from_corruption(self) -> bytes:
        """
        Recover from a corrupt log file by backing up the corrupt file
        and creating a new log with a fresh genesis record.
        """
        import shutil
        from datetime import datetime, timezone
        
        # Create backup filename with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = self._log_path.parent / f"pskc_audit_corrupt_{timestamp}.log"
        
        # Move corrupt file to backup
        shutil.move(str(self._log_path), str(backup_path))
        logger.warning(f"Corrupt audit log backed up to: {backup_path}")
        
        # Create new genesis record
        genesis_hash = b'\x00' * 32
        self._write_log_entry("SYSTEM", "LOG_RECOVERY", "SUCCESS", genesis_hash)
        logger.info("Audit log recovered successfully with new genesis record.")
        return self._last_hash

    def _write_log_entry(self, user: str, action: str, outcome: str, previous_hash: bytes):
        """
        Memformat, menandatangani, dan menulis satu entri log.
        Ini adalah fungsi internal inti.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # 1. Buat konten log untuk di-hash dan ditandatangani
        log_content = f"{timestamp}|{user}|{action}|{outcome}|{previous_hash.hex()}"
        log_content_bytes = log_content.encode('utf-8')
        
        # 2. Hash konten (menggunakan FIPS module)
        current_hash = self._fips_module.hash_data(log_content_bytes)
        
        # 3. Tanda tangani hash tersebut (menggunakan FIPS module)
        # Di sini kita menggunakan kunci berlabel 'audit-log-signing-key-v1'.
        # Di lingkungan nyata, kunci ini akan ada di dalam HSM dan tidak
        # pernah bisa diekstraksi.
        signature = self._fips_module.sign_data(current_hash, self.LOG_SIGNING_KEY_LABEL)
        
        # 4. Buat baris log final
        final_log_line = f"{log_content}|{signature.hex()}\n"
        
        # 5. Tulis ke file (mode append)
        # Idealnya, file ini harus ada di filesystem WORM
        # (Write-Once, Read-Many) untuk lapisan perlindungan ekstra.
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(final_log_line)
        
        # 6. Perbarui hash terakhir untuk entri berikutnya
        self._last_hash = current_hash

    def log(self, user: str, action: str, outcome: str = "SUCCESS", metadata: Optional[Dict[str, Any]] = None):
        """
        Mencatat peristiwa keamanan. Ini adalah metode publik utama.

        Args:
            user: ID pengguna atau sistem yang melakukan aksi. (misal: 'user_123', 'SYSTEM', 'ANONYMOUS')
            action: Aksi yang dilakukan. (misal: 'LOGIN', 'KEY_FETCH_ATTEMPT', 'ENCRYPT_DATA')
            outcome: Hasil dari aksi. (misal: 'SUCCESS', 'FAILURE_INVALID_PASSWORD', 'FAILURE_TAMPERING_DETECTED')
            metadata: Metadata tambahan untuk kompatibilitas call site lama. Saat ini
                tidak diserialisasikan ke format log file yang sudah ada.
        """
        try:
            # Menggunakan `_last_hash` yang disimpan di memori untuk efisiensi.
            # Verifikasi rantai penuh hanya terjadi saat startup.
            self._write_log_entry(user, action, outcome, self._last_hash)
        except Exception as e:
            logger.critical(f"Failed to write to tamper-evident audit log: {e}")
            # Di sini, kita bisa menambahkan fallback logging (misalnya, ke syslog)
            # jika penulisan ke log utama gagal.

    def read_recent_entries(self, limit: int = 100) -> Dict[str, Any]:
        """Read the most recent audit entries without mutating the log file."""
        if limit < 1:
            return {"entries": [], "total_count": 0}

        recent_lines = deque(maxlen=limit)
        total_count = 0

        if not self._log_path.exists():
            return {"entries": [], "total_count": 0}

        with open(self._log_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                total_count += 1
                recent_lines.append(line)

        entries = []
        for line in recent_lines:
            parts = line.split("|")
            if len(parts) != 6:
                continue

            timestamp, user, action, outcome, previous_hash_hex, signature_hex = parts
            entries.append(
                {
                    "timestamp": timestamp,
                    "user": user,
                    "event_type": action,
                    "outcome": outcome,
                    "previous_hash": previous_hash_hex,
                    "signature": signature_hex,
                }
            )

        return {"entries": entries, "total_count": total_count}
            
    def __del__(self):
        # Memastikan semua buffer ditulis saat objek dihancurkan.
        # Operasi file sebenarnya tidak dilakukan di sini untuk menghindari
        # masalah dengan garbage collector.
        logger.debug("TamperEvidentAuditLogger shutting down.")
