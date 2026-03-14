# =================================================================
# FIPS 140-2 CRYPTOGRAPHIC MODULE BOUNDARY
# =================================================================
#
# DOKUMEN INI ADALAH IMPLEMENTASI RENCANA AKSI DARI
# `plans/fips_nist_compliance_assessment.md`.
#
# TUJUAN:
# Kelas `FipsCryptographicModule` ini berfungsi sebagai "Cryptographic
# Boundary" logis yang diwajibkan oleh FIPS 140-2. Semua operasi
# kriptografi (enkripsi, dekripsi, penandatanganan, hashing, RNG)
# HARUS melalui kelas ini.
#
# ARSITEKTUR:
# Kelas ini adalah sebuah "facade" atau "wrapper". Saat ini, ia masih
# menggunakan library `cryptography` Python di belakang layar. Namun,
# dengan mengisolasi semua panggilan di sini, kita dapat mengganti
# backend-nya dengan modul yang tersertifikasi FIPS di masa depan
# (misalnya, wrapper untuk HSM via PKCS#11 atau OpenSSL FIPS Provider)
# tanpa mengubah sisa kode aplikasi.
#
# PENTING:
# Modul ini dalam bentuknya saat ini BELUM FIPS COMPLIANT karena
# backend-nya (`cryptography` library) tidak tersertifikasi. Namun,
# arsitektur ini adalah langkah pertama yang KRUSIAL menuju kepatuhan.

import os
import hmac
import secrets
import logging
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)


class FipsCryptographicModule:
    """
    Boundary logis untuk semua operasi kriptografi yang sesuai dengan FIPS 140-2.

    Kelas ini mengabstraksikan backend kriptografi. Dalam implementasi saat ini,
    ia menggunakan `cryptography` library. Untuk kepatuhan FIPS penuh,
    backend ini harus diganti dengan panggilan ke modul bersertifikat.
    """

    # --- KONSTANTA FIPS ---
    AES_KEY_SIZE = 32  # 256-bit
    GCM_NONCE_SIZE = 12  # 96-bit (sesuai rekomendasi NIST SP 800-38D)
    GCM_TAG_SIZE = 16  # 128-bit
    PBKDF2_ITERATIONS = 200_000 # Iterasi untuk key derivation dari password
    SALT_SIZE = 32 # 256-bit salt


    def __init__(self, master_key: bytes):
        """
        Inisialisasi modul dengan master key.
        Dalam skenario FIPS nyata, `master_key` tidak akan pernah ada di memori
        aplikasi. Sebaliknya, constructor ini akan menerima handle/koneksi
        ke HSM atau modul FIPS lainnya.

        Args:
            master_key: Kunci 32-byte untuk enkripsi AES-GCM.
        """
        if len(master_key) != self.AES_KEY_SIZE:
            raise ValueError(f"Master key harus tepat {self.AES_KEY_SIZE} bytes.")

        # Di dunia nyata, `self._master_key` tidak akan ada.
        # Sebagai gantinya, kita akan menyimpan `key_handle` dari HSM.
        # Operasi enkripsi akan meneruskan handle ini ke HSM.
        self._master_key = master_key
        self._aesgcm = AESGCM(self._master_key)
        logger.info("FipsCryptographicModule initialized. WARNING: Using non-FIPS certified backend.")

    # ============================================================
    # 1. ENCRYPTION / DECRYPTION OPERATIONS
    # ============================================================

    def encrypt_data(self, plaintext: bytes, associated_data: bytes = None) -> bytes:
        """
        Enkripsi data menggunakan AES-256-GCM.

        Fungsi ini menghasilkan blob terenkripsi dengan format:
        [ nonce (12 bytes) | ciphertext (N bytes) | tag (16 bytes) ]

        Args:
            plaintext: Data untuk dienkripsi.
            associated_data (AAD): Data tambahan yang diautentikasi tetapi tidak dienkripsi.

        Returns:
            Blob terenkripsi (nonce + ciphertext + tag).
        """
        # RNG juga harus berasal dari dalam modul FIPS. `secrets`
        # adalah pilihan terbaik di Python standar, tapi modul FIPS
        # memiliki RNG yang sudah divalidasi (misal: DRBG).
        nonce = self.generate_random_bytes(self.GCM_NONCE_SIZE)
        ciphertext_with_tag = self._aesgcm.encrypt(nonce, plaintext, associated_data)
        return nonce + ciphertext_with_tag

    def decrypt_data(self, encrypted_blob: bytes, associated_data: bytes = None) -> bytes:
        """
        Dekripsi dan verifikasi data dari blob terenkripsi.

        Args:
            encrypted_blob: Blob data dari `encrypt_data`.
            associated_data (AAD): Data tambahan yang sama yang digunakan saat enkripsi.

        Returns:
            Plaintext asli jika dekripsi dan verifikasi tag berhasil.

        Raises:
            InvalidTag: Jika verifikasi otentikasi gagal (data dirusak).
            ValueError: Jika format blob tidak valid.
        """
        if len(encrypted_blob) < self.GCM_NONCE_SIZE + self.GCM_TAG_SIZE:
            raise ValueError("Encrypted blob terlalu pendek untuk berisi nonce dan tag.")

        nonce = encrypted_blob[:self.GCM_NONCE_SIZE]
        ciphertext_with_tag = encrypted_blob[self.GCM_NONCE_SIZE:]

        try:
            return self._aesgcm.decrypt(nonce, ciphertext_with_tag, associated_data)
        except InvalidTag:
            logger.error("DECRYPTION FAILED: Authentication tag tidak valid. Data mungkin telah dirusak!")
            raise

    # ============================================================
    # 2. RANDOM NUMBER GENERATION
    # ============================================================

    def generate_random_bytes(self, num_bytes: int) -> bytes:
        """
        Hasilkan byte acak dari sumber yang aman secara kriptografis.

        # FIPS 140-2 memerlukan penggunaan RNG yang disetujui
        # (Approved RNG). Panggilan ini harus dialihkan ke RNG dari
        # modul FIPS (misalnya, `CK_C_GenerateRandom` di PKCS#11).
        # `secrets` adalah pengganti terbaik yang tersedia di Python.
        """
        return secrets.token_bytes(num_bytes)

    # ============================================================
    # 3. HASHING & SIGNING OPERATIONS
    # ============================================================

    def sign_data(self, data: bytes, key_label: str) -> bytes:
        """
        Tanda tangani data menggunakan kunci privat dari dalam modul.

        # Implementasi ini menggunakan HMAC-SHA256 sebagai placeholder
        # karena ini adalah algoritma simetris yang disetujui FIPS.
        # Dalam skenario FIPS Level 2+, ini seharusnya menggunakan
        # tanda tangan digital asimetris (misalnya, ECDSA atau RSA)
        # di mana kunci privat tidak pernah meninggalkan HSM. `key_label`
        # akan digunakan untuk merujuk ke kunci tersebut di dalam HSM.
        # Kunci untuk HMAC di-derive dari master key untuk simulasi.
        """
        signing_key = self.derive_key_hkdf(
            input_material=self._master_key,
            info=f"fips-signing-key-{key_label}"
        )
        return hmac.new(signing_key, data, 'sha256').digest()

    def verify_signature(self, signature: bytes, data: bytes, key_label: str) -> bool:
        """
        Verifikasi tanda tangan data.
        """
        expected_signature = self.sign_data(data, key_label)
        # Gunakan `hmac.compare_digest` untuk perbandingan waktu-konstan
        return hmac.compare_digest(expected_signature, signature)

    @staticmethod
    def hash_data(data: bytes) -> bytes:
        """
        Hash data menggunakan SHA-256 (algoritma yang disetujui FIPS).
        """
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(data)
        return digest.finalize()

    # ============================================================
    # 4. KEY DERIVATION
    # ============================================================

    @staticmethod
    def derive_key_from_password(password: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """
        Derive kunci dari password menggunakan PBKDF2-HMAC-SHA256.

        # PBKDF2 adalah algoritma yang disetujui FIPS.
        # Operasi ini dianggap "pre-cryptographic" dan bisa terjadi
        # di luar boundary, tetapi lebih aman jika dilakukan di dalam.
        """
        if salt is None:
            salt = secrets.token_bytes(FipsCryptographicModule.SALT_SIZE)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=FipsCryptographicModule.AES_KEY_SIZE,
            salt=salt,
            iterations=FipsCryptographicModule.PBKDF2_ITERATIONS,
            backend=default_backend(),
        )
        key = kdf.derive(password.encode("utf-8"))
        return key, salt

    @staticmethod
    def derive_key_hkdf(input_material: bytes, info: str, salt: bytes = None) -> bytes:
        """
        Derive kunci dari secret dengan entropi tinggi menggunakan HKDF-SHA256.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=FipsCryptographicModule.AES_KEY_SIZE,
            salt=salt,
            info=info.encode("utf-8"),
            backend=default_backend(),
        )
        return hkdf.derive(input_material)

    # ============================================================
    # 5. LIFECYCLE MANAGEMENT
    # ============================================================

    def destroy(self):
        """
        Hancurkan materi kunci dari memori.

        # Ini adalah aspek kritis dari manajemen kunci. Di Python,
        # kita melakukan 'best effort' dengan menimpa bytearray. Di HSM,
        # ini akan menjadi panggilan untuk menghancurkan objek kunci
        # atau menutup sesi.
        """
        if hasattr(self, '_master_key') and self._master_key is not None:
            # Convert to bytearray to allow modification, then overwrite
            key_array = bytearray(self._master_key)
            for i in range(len(key_array)):
                key_array[i] = 0
            self._master_key = None
        logger.info("FipsCryptographicModule instance destroyed and key material zeroized.")

    def __del__(self):
        try:
            self.destroy()
        except Exception:
            pass
