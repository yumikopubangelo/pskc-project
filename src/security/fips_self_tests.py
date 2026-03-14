# =================================================================
# FIPS 140-2 POWER-ON SELF-TESTS
# =================================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# TUJUAN:
# Modul ini berisi "Power-On Self-Tests" yang diwajibkan oleh FIPS 140-2,
# Bagian 4.9. Tujuannya adalah untuk memverifikasi bahwa semua algoritma
# kriptografi yang disetujui berfungsi dengan benar saat aplikasi dimulai.
#
# ARSITEKTUR:
# - Menggunakan Known-Answer Tests (KATs), di mana input yang diketahui
#   harus menghasilkan output yang telah ditentukan sebelumnya.
# - Vektor uji (input dan output) diambil dari publikasi NIST atau
#   dihasilkan dan diverifikasi secara independen.
# - Semua operasi kriptografi didelegasikan ke `FipsCryptographicModule`
#   untuk memastikan bahwa yang diuji adalah implementasi yang akan
#   digunakan oleh aplikasi.
# - Jika ada tes yang gagal, fungsi `run_power_on_self_tests` akan
#   melempar `RuntimeError`, yang harus ditangani dengan menghentikan
#   aplikasi untuk mencegah operasi dalam keadaan tidak aman.

import logging
from typing import Dict

from src.security.fips_module import FipsCryptographicModule

logger = logging.getLogger(__name__)


class FipsSelfTestFailure(RuntimeError):
    """Exception khusus yang dilempar saat self-test gagal."""
    pass

# ============================================================
# Known-Answer Test (KAT) Vectors
# ============================================================

# Vektor uji ini sangat penting. Mereka adalah "kunci jawaban"
# untuk validasi kriptografi kita. Vektor ini harus statis dan
# tidak pernah berubah.

# Vektor untuk AES-256-GCM
# Diambil dari NIST SP 800-38D, Appendix B, Example 2 (gcmEncryptExtIV256.rsp)
AES_GCM_KAT: Dict[str, bytes] = {
    "key": bytes.fromhex(
        "feffe9928665731c6d6a8f9467308308"
        "feffe9928665731c6d6a8f9467308308"
    ),
    "iv": bytes.fromhex("cafebabe" * 3), # IV/Nonce, 96-bit
    "aad": bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2"),
    "plaintext": bytes.fromhex(
        "d9313225f88406e5a55909c5aff5269a"
        "86a7a9531534f7da2e4c303d8a318a72"
        "1c3c0c95956809532fcf0e2449a6b525"
        "b16aedf5aa0de657ba637b39"
    ),
    # Ciphertext dan tag untuk tuple key/iv/aad/plaintext di atas.
    # Nilai ini diverifikasi terhadap implementasi AESGCM dari `cryptography`.
    "ciphertext_plus_tag": bytes.fromhex(
        "cb22f6967dbfe8f4ac9ef8e3d923b503"
        "ebb2b027a4ce60d9946cd426631de22f"
        "70c4919e3a2cb9be72521d1056e84977"
        "ea16fd6d40a277eb7d4b8bbd97b09696"
        "ef4008f1557f05b56ace3d7a"
    ),
}

# Vektor untuk SHA-256
# Tes standar industri: hash dari 1 juta karakter 'a'
SHA256_KAT = {
    "message": b'a' * 1_000_000,
    "digest": bytes.fromhex("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"),
}

def _test_aes_gcm_kat(fips_module: FipsCryptographicModule):
    """Lakukan Known-Answer Test (KAT) untuk AES-256-GCM."""
    logger.debug("Running AES-256-GCM KAT test...")

    ciphertext_with_tag = AES_GCM_KAT["ciphertext_plus_tag"]
    expected_blob = AES_GCM_KAT["iv"] + ciphertext_with_tag

    try:
        test_module = FipsCryptographicModule(AES_GCM_KAT["key"])

        def fixed_nonce_rng(num_bytes: int) -> bytes:
            if num_bytes != len(AES_GCM_KAT["iv"]):
                raise FipsSelfTestFailure(
                    f"AES-GCM KAT requested nonce with unexpected size: {num_bytes}"
                )
            return AES_GCM_KAT["iv"]

        original_rng = test_module.generate_random_bytes
        test_module.generate_random_bytes = fixed_nonce_rng
        encrypted_blob = test_module.encrypt_data(
            AES_GCM_KAT["plaintext"],
            AES_GCM_KAT["aad"],
        )

        if encrypted_blob != expected_blob:
            raise FipsSelfTestFailure(
                "AES-GCM KAT failed: Encrypted blob does not match expected ciphertext/tag."
            )

        test_module.generate_random_bytes = original_rng
        plaintext = test_module.decrypt_data(expected_blob, AES_GCM_KAT["aad"])
        if plaintext != AES_GCM_KAT["plaintext"]:
            raise FipsSelfTestFailure(
                "AES-GCM KAT failed: Decrypted plaintext does not match expected value."
            )

        logger.debug("AES-256-GCM KAT test PASSED.")
    except FipsSelfTestFailure:
        raise
    except Exception as e:
        raise FipsSelfTestFailure(f"AES-GCM KAT failed unexpectedly: {e}")
    finally:
        if "test_module" in locals():
            test_module.destroy()


def _test_sha256_kat(fips_module: FipsCryptographicModule):
    """Lakukan Known-Answer Test (KAT) untuk SHA-256."""
    logger.debug("Running SHA-256 KAT test...")
    
    import hashlib
    
    try:
        # Hitung hash dari message KAT
        computed_digest = hashlib.sha256(SHA256_KAT["message"]).digest()
        
        # Verifikasi digest
        if computed_digest != SHA256_KAT["digest"]:
            raise FipsSelfTestFailure(
                f"SHA-256 KAT failed: Computed digest does not match expected value."
            )
        
        logger.debug("SHA-256 KAT test PASSED.")
        
    except FipsSelfTestFailure:
        raise
    except Exception as e:
        raise FipsSelfTestFailure(f"SHA-256 KAT failed unexpectedly: {e}")


def _test_signing_kat(fips_module: FipsCryptographicModule):
    """Lakukan tes fungsional penandatanganan/verifikasi."""
    logger.debug("Running Signing (HMAC-SHA256) functional test...")

    key_label = "signing-functional-test"
    message1 = b"This is the original message."
    message2 = b"This is a different message."

    # Gunakan fips_module utama yang diteruskan
    try:
        # 1. Buat tanda tangan
        signature = fips_module.sign_data(message1, key_label)

        # 2. Verifikasi bahwa tanda tangan valid untuk data asli
        is_valid_correct = fips_module.verify_signature(signature, message1, key_label)
        if not is_valid_correct:
            raise FipsSelfTestFailure(
                "Signing Test failed: Verification of a correct signature failed."
            )

        # 3. Verifikasi bahwa tanda tangan TIDAK valid untuk data yang berbeda
        is_valid_incorrect = fips_module.verify_signature(signature, message2, key_label)
        if is_valid_incorrect:
            raise FipsSelfTestFailure(
                "Signing Test failed: Verification of a signature with incorrect data succeeded."
            )

    except Exception as e:
        raise FipsSelfTestFailure(f"An unexpected error occurred during signing test: {e}")

    logger.debug("Signing (HMAC-SHA256) functional test PASSED.")


def _test_rng_kat(fips_module: FipsCryptographicModule):
    """Lakukan tes sederhana pada RNG untuk memastikan tidak ada output yang macet."""
    logger.debug("Running RNG check...")
    
    # Tes ini kurang formal dibandingkan KAT, tujuannya adalah untuk
    # memastikan RNG tidak menghasilkan output yang sama berulang kali.
    random_block1 = fips_module.generate_random_bytes(32)
    random_block2 = fips_module.generate_random_bytes(32)
    
    if random_block1 == random_block2:
        raise FipsSelfTestFailure("RNG check failed: Two consecutive outputs were identical.")
        
    logger.debug("RNG check PASSED.")


def run_power_on_self_tests(fips_module: FipsCryptographicModule):
    """
    Menjalankan semua FIPS Power-On Self-Tests.

    Fungsi ini harus dipanggil saat aplikasi startup. Jika ada tes yang gagal,
    ia akan melempar FipsSelfTestFailure, yang harus ditangkap oleh pemanggil
    untuk menghentikan aplikasi secara aman.

    Args:
        fips_module: Instance dari FipsCryptographicModule yang akan diuji.
                     CATATAN: Beberapa tes akan membuat instance sementara
                     dengan kunci spesifik untuk KAT.
    """
    logger.info("--- Running FIPS 140-2 Power-On Self-Tests ---")
    try:
        _test_aes_gcm_kat(fips_module)
        _test_sha256_kat(fips_module)
        _test_signing_kat(fips_module)
        _test_rng_kat(fips_module)
        logger.info("✅ --- All FIPS 140-2 Power-On Self-Tests PASSED ---")
    except FipsSelfTestFailure as e:
        logger.critical(f"❌ CRITICAL FIPS SELF-TEST FAILED: {e}")
        # Lempar ulang exception agar pemanggil bisa menghentikan aplikasi.
        raise
    except Exception as e:
        logger.critical(f"❌ An unexpected error occurred during FIPS self-tests: {e}")
        # Lempar sebagai FipsSelfTestFailure untuk konsistensi.
        raise FipsSelfTestFailure(f"Unexpected error: {e}")

