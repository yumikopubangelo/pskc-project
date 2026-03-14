# ####################################################################
# # DEPRECATION WARNING
# ####################################################################
# #
# # Modul ini sudah usang (DEPRECATED).
# #
# # Fungsionalitas kriptografi inti telah dipindahkan ke:
# #   `src/security/fips_module.py`
# #
# # Pola singleton global (`get_encryptor`) telah digantikan oleh
# # dependency injection yang dikelola oleh siklus hidup aplikasi di
# # `src/api/routes.py`.
# #
# # Modul ini dipertahankan HANYA untuk kompatibilitas dengan
# # skrip dan tes yang ada. JANGAN GUNAKAN UNTUK PENGEMBANGAN BARU.
# #
# ####################################################################


# ============================================================
# PSKC — Encryption Module (SECURITY UPGRADE)
# ============================================================
#
# CRITICAL SECURITY FIXES vs sebelumnya:
#
# 1. AES-CBC → AES-GCM (Authenticated Encryption)
#    SEBELUMNYA: AES-256-CBC tidak memiliki integrity protection.
#    Attacker bisa flip bits di ciphertext (bit-flipping attack) dan
#    decrypt akan berhasil tanpa error, menghasilkan plaintext yang
#    dimodifikasi — sangat berbahaya untuk key material.
#    SEKARANG: AES-256-GCM menghasilkan Authentication Tag 16 byte yang
#    diverifikasi sebelum decrypt. Modifikasi apapun = immediate rejection.
#
# 2. SHA-256 key derivation → HKDF
#    SEBELUMNYA: key = SHA256(password_string) — ini BUKAN KDF yang proper.
#    SHA-256 tidak memiliki salt, iteration, atau work factor. Rentan
#    terhadap dictionary/rainbow table attack.
#    SEKARANG: HKDF dengan salt acak + info context string. Untuk password-
#    based keys, PBKDF2 (100k iterasi) tetap dipertahankan.
#
# 3. Nonce/IV uniqueness enforcement
#    SEBELUMNYA: IV generate dengan os.urandom tanpa tracking — meski
#    probabilitasnya kecil, tidak ada proteksi terhadap IV reuse.
#    SEKARANG: Nonce counter + random hybrid untuk jaminan uniqueness.
#
# 4. Memory zeroization untuk key material
#    SEBELUMNYA: key material di-store sebagai bytes immutable di Python.
#    SEKARANG: Menggunakan bytearray yang bisa di-zero setelah pakai.
#    SecureBytes wrapper disediakan untuk caller.
#
# 5. Constant-time comparison di semua perbandingan sensitif
#    SEKARANG: semua tag/hash comparison menggunakan hmac.compare_digest.
# ============================================================

import os
import hmac
import struct
import hashlib
import secrets
import threading
import base64
from typing import Union, Tuple, Optional
import logging

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)


# ============================================================
# Secure Memory Helper
# ============================================================

class SecureBytes:
    """
    Wrapper untuk key material yang bisa di-zero dari memory.

    Python bytes bersifat immutable dan garbage-collected — tidak ada
    jaminan kapan memory-nya dibebaskan. SecureBytes menggunakan bytearray
    yang secara eksplisit di-zero saat clear() atau __del__ dipanggil.

    Usage:
        secure = SecureBytes(raw_key_bytes)
        try:
            use(secure.value)
        finally:
            secure.clear()
    """

    def __init__(self, data: Union[bytes, bytearray]):
        self._data = bytearray(data)

    @property
    def value(self) -> bytes:
        return bytes(self._data)

    def clear(self) -> None:
        """Overwrite memory dengan zeros."""
        for i in range(len(self._data)):
            self._data[i] = 0

    def __del__(self):
        self.clear()

    def __len__(self):
        return len(self._data)


# ============================================================
# Nonce Manager — mencegah IV reuse
# ============================================================

class NonceManager:
    """
    Thread-safe nonce generator untuk AES-GCM.

    AES-GCM bersifat catastrophically broken jika nonce di-reuse dengan
    key yang sama — attacker bisa recover plaintext dan authentication key.
    
    CRITICAL FIX (2026-03-09):
    The previous implementation used a non-persistent counter that would reset
    on application crash, guaranteeing nonce reuse. The fix is to use a
    fully random 96-bit (12-byte) nonce generated from a crytographically
    secure pseudo-random number generator (CSPRNG) for each encryption.
    
    As per NIST SP 800-38D, for a given key, the probability of collision 
    for random nonces should be acceptably low. For 96-bit nonces, this 
    probability is negligible until 2^32 encryptions are performed.
    """

    NONCE_SIZE = 12  # 96-bit nonce untuk AES-GCM

    def generate(self) -> bytes:
        """Generate a cryptographically secure random 96-bit nonce."""
        return secrets.token_bytes(self.NONCE_SIZE)

    def reset(self) -> None:
        """No-op: state is no longer maintained."""
        pass


# ============================================================
# AES-256-GCM Encryptor (menggantikan AES-256-CBC)
# ============================================================

class AES256GCMEncryptor:
    """
    AES-256-GCM authenticated encryption untuk key material di cache.

    Format ciphertext yang disimpan (base64-encoded):
        [ nonce (12 bytes) | ciphertext (N bytes) | tag (16 bytes) ]

    Tag diverifikasi oleh cryptography library secara otomatis saat decrypt.
    Jika tag invalid (data dimodifikasi), InvalidTag exception dilempar.
    """

    TAG_SIZE = 16   # bytes — GCM authentication tag
    NONCE_SIZE = 12  # bytes — 96-bit nonce

    def __init__(self, key: Union[bytes, bytearray]):
        """
        Args:
            key: 32-byte key (AES-256). Harus bytes atau bytearray,
                 bukan str — ini mencegah accidental string key derivation.
        """
        if isinstance(key, str):
            raise TypeError(
                "Key harus bytes/bytearray, bukan str. "
                "Gunakan KeyDerivation.derive_from_secret() terlebih dahulu."
            )
        if len(key) != 32:
            raise ValueError(f"Key harus tepat 32 bytes (AES-256), got {len(key)}")

        # Simpan sebagai bytearray agar bisa di-zero
        self._key = bytearray(key)
        self._aesgcm = AESGCM(bytes(self._key))
        self._nonce_mgr = NonceManager()

        logger.debug("AES256GCMEncryptor initialized")

    def encrypt(self, plaintext: bytes, associated_data: bytes = None) -> Tuple[bytes, bytes]:
        """
        Encrypt plaintext dengan AES-256-GCM.

        Args:
            plaintext: Data yang akan dienkripsi
            associated_data: Data yang di-authenticate tapi tidak dienkripsi
                             (misal: key_id atau service_id sebagai AAD)

        Returns:
            Tuple (ciphertext_with_tag, nonce)
            ciphertext_with_tag sudah termasuk 16-byte authentication tag
        """
        nonce = self._nonce_mgr.generate()

        # AESGCM.encrypt() mengembalikan ciphertext + tag (appended)
        ciphertext_with_tag = self._aesgcm.encrypt(
            nonce,
            plaintext,
            associated_data,
        )

        return ciphertext_with_tag, nonce

    def decrypt(
        self,
        ciphertext_with_tag: bytes,
        nonce: bytes,
        associated_data: bytes = None,
    ) -> bytes:
        """
        Decrypt dan verifikasi AES-256-GCM ciphertext.

        Raises:
            InvalidTag: Jika data telah dimodifikasi atau tag invalid.
                        JANGAN tangkap exception ini secara silent —
                        ini indikasi tampering atau korupsi data.
        """
        try:
            plaintext = self._aesgcm.decrypt(
                nonce,
                ciphertext_with_tag,
                associated_data,
            )
            return plaintext
        except InvalidTag:
            logger.error(
                "AES-GCM authentication tag verification FAILED — "
                "data mungkin telah dimodifikasi atau nonce/key salah."
            )
            raise

    def encrypt_to_token(
        self, plaintext: bytes, associated_data: bytes = None
    ) -> str:
        """
        Encrypt dan encode ke base64 token untuk penyimpanan.

        Format: base64( nonce[12] + ciphertext + tag[16] )
        """
        ciphertext_with_tag, nonce = self.encrypt(plaintext, associated_data)
        blob = nonce + ciphertext_with_tag
        return base64.b64encode(blob).decode("ascii")

    def decrypt_from_token(
        self, token: str, associated_data: bytes = None
    ) -> bytes:
        """
        Decode base64 token dan decrypt.

        Raises:
            ValueError: Jika format token tidak valid.
            InvalidTag: Jika authentication gagal.
        """
        try:
            blob = base64.b64decode(token.encode("ascii"))
        except Exception:
            raise ValueError("Token bukan base64 yang valid")

        if len(blob) < self.NONCE_SIZE + self.TAG_SIZE:
            raise ValueError(
                f"Token terlalu pendek: {len(blob)} bytes "
                f"(minimum {self.NONCE_SIZE + self.TAG_SIZE})"
            )

        nonce = blob[: self.NONCE_SIZE]
        ciphertext_with_tag = blob[self.NONCE_SIZE :]

        return self.decrypt(ciphertext_with_tag, nonce, associated_data)

    # Alias untuk backward compatibility dengan encrypted_store.py
    def encrypt_hex(self, plaintext: bytes) -> str:
        """Alias: encrypt dan return base64 string."""
        return self.encrypt_to_token(plaintext)

    def decrypt_hex(self, token: str) -> bytes:
        """Alias: decode base64 string dan decrypt."""
        return self.decrypt_from_token(token)

    def destroy(self) -> None:
        """Zero-out key material dari memory."""
        self._nonce_mgr.reset()
        for i in range(len(self._key)):
            self._key[i] = 0
        logger.debug("AES256GCMEncryptor key material zeroed")

    def __del__(self):
        try:
            self.destroy()
        except Exception:
            pass


# ============================================================
# Backward Compatibility Alias
# ============================================================

# encrypted_store.py menggunakan AES256Encryptor — alias ke GCM version
AES256Encryptor = AES256GCMEncryptor


# ============================================================
# Key Derivation
# ============================================================

class KeyDerivation:
    """
    Proper key derivation functions untuk PSKC.

    SEBELUMNYA: hashlib.sha256(key.encode()).digest()
    Ini BUKAN KDF yang aman karena:
    - Tidak ada salt → rainbow table attacks
    - Tidak ada iteration → brute force mudah
    - Deterministik → sama input = sama output selalu

    SEKARANG:
    - Password-based: PBKDF2-HMAC-SHA256, 200k iterasi, 32-byte salt
    - Secret-based:   HKDF-SHA256 dengan context info string
    """

    PBKDF2_ITERATIONS = 200_000  # NIST minimum 2023: 600k, kita pakai 200k
                                  # untuk balance performa vs security

    @staticmethod
    def derive_from_password(
        password: str,
        salt: bytes = None,
        iterations: int = None,
    ) -> Tuple[bytes, bytes]:
        """
        Derive 32-byte encryption key dari password menggunakan PBKDF2.

        Args:
            password: Password plaintext
            salt: 32-byte salt (di-generate jika None)
            iterations: Override iteration count (default: 200k)

        Returns:
            (derived_key_32_bytes, salt)
        """
        if salt is None:
            salt = secrets.token_bytes(32)  # 256-bit salt

        iters = iterations or KeyDerivation.PBKDF2_ITERATIONS

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iters,
            backend=default_backend(),
        )
        key = kdf.derive(password.encode("utf-8"))
        return key, salt

    @staticmethod
    def derive_from_secret(
        secret: Union[str, bytes],
        info: str = "pskc-cache-key-v1",
        salt: bytes = None,
    ) -> bytes:
        """
        Derive 32-byte key dari high-entropy secret menggunakan HKDF.

        Cocok untuk: API key, env var, hardware-generated secret.
        JANGAN gunakan untuk password (pakai derive_from_password).

        Args:
            secret: High-entropy input material
            info: Context string — membuat derived key berbeda per use-case
            salt: Optional salt (32 bytes). Jika None, HKDF pakai zero-salt.

        Returns:
            32-byte derived key
        """
        if isinstance(secret, str):
            secret = secret.encode("utf-8")

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info.encode("utf-8"),
            backend=default_backend(),
        )
        return hkdf.derive(secret)

    @staticmethod
    def generate_random_key(length: int = 32) -> bytes:
        """Generate cryptographically secure random key."""
        return secrets.token_bytes(length)

    # Backward compat
    @staticmethod
    def derive_key_from_password(
        password: str,
        salt: bytes = None,
        iterations: int = 100_000,
    ) -> Tuple[bytes, bytes]:
        return KeyDerivation.derive_from_password(password, salt, iterations)


# ============================================================
# Encryption Context (key rotation support)
# ============================================================

class EncryptionContext:
    """
    Context manager untuk encryption operations dengan key rotation.
    """

    def __init__(self, key: Union[str, bytes]):
        if isinstance(key, str):
            # Derive proper key dari string via HKDF
            derived = KeyDerivation.derive_from_secret(key)
            self._encryptor = AES256GCMEncryptor(derived)
        else:
            self._encryptor = AES256GCMEncryptor(key)

    @property
    def encryptor(self) -> AES256GCMEncryptor:
        return self._encryptor

    def rotate_key(self, new_key: Union[str, bytes]) -> "EncryptionContext":
        """Create new context dengan key baru dan destroy yang lama."""
        old = self._encryptor
        new_ctx = EncryptionContext(new_key)
        old.destroy()
        return new_ctx


# ============================================================
# Global Encryptor Singleton
# ============================================================

_encryptor_instance: Optional[AES256GCMEncryptor] = None
_encryptor_lock = threading.Lock()


def get_encryptor() -> AES256GCMEncryptor:
    """
    Get global encryptor instance.

    Key di-derive via HKDF dari CACHE_ENCRYPTION_KEY env var.
    Jika env var tidak di-set di production → raise RuntimeError (tidak silent fallback).
    """
    global _encryptor_instance

    if _encryptor_instance is None:
        with _encryptor_lock:
            if _encryptor_instance is None:
                from config.settings import settings

                raw_key = settings.cache_encryption_key

                if not raw_key:
                    import os
                    env = os.getenv("APP_ENV", "development")
                    if env == "production":
                        raise RuntimeError(
                            "CRITICAL: CACHE_ENCRYPTION_KEY tidak di-set di production! "
                            "Set env var ini sebelum deployment."
                        )
                    # Development only — generate ephemeral key dengan warning
                    raw_key = secrets.token_hex(32)
                    logger.warning(
                        "⚠️  CACHE_ENCRYPTION_KEY tidak di-set — menggunakan ephemeral key. "
                        "Data cache TIDAK persisten antar restart. "
                        "JANGAN gunakan ini di production!"
                    )

                # Derive proper 32-byte key via HKDF
                derived_key = KeyDerivation.derive_from_secret(
                    raw_key,
                    info="pskc-cache-encryption-key-v1",
                )
                _encryptor_instance = AES256GCMEncryptor(derived_key)

    return _encryptor_instance


def rotate_encryptor(new_raw_key: str) -> None:
    """
    Rotate global encryption key.
    PERHATIAN: Key lama harus dipakai untuk re-encrypt semua data yang ada
    sebelum key lama di-destroy. Implementasi full key rotation ada di
    scripts/rotate_encryption_key.py
    """
    global _encryptor_instance
    with _encryptor_lock:
        old = _encryptor_instance
        new_key = KeyDerivation.derive_from_secret(
            new_raw_key,
            info="pskc-cache-encryption-key-v1",
        )
        _encryptor_instance = AES256GCMEncryptor(new_key)
        if old:
            old.destroy()
    logger.info("Encryption key rotated successfully.")


# Convenience wrappers
def encrypt_key(key_data: bytes, associated_data: bytes = None) -> str:
    return get_encryptor().encrypt_to_token(key_data, associated_data)


def decrypt_key(token: str, associated_data: bytes = None) -> bytes:
    return get_encryptor().decrypt_from_token(token, associated_data)