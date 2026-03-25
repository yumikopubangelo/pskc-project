# Arsitektur Halaman Frontend

Dokumen ini menjelaskan struktur dan kegunaan setiap halaman utama yang ada di antarmuka (frontend) aplikasi PSKC.

## 1. Halaman Utama (Dashboard)

Halaman ini berfungsi sebagai pusat informasi utama yang memberikan gambaran umum mengenai status sistem secara *real-time*.

-   **Kegunaan:**
    -   Menampilkan ringkasan status model *Machine Learning* (ML), seperti tahap saat ini (`Cold Start`, `Learning`, `Mature`) dan akurasinya.
    -   Memberikan visualisasi data lalu lintas (traffic) yang sedang masuk ke sistem.
    -   Menyajikan metrik-metrik kunci performa sistem, seperti latensi rata-rata dan jumlah permintaan per detik.

## 2. Halaman Simulasi (Simulation Runner)

Halaman ini adalah pusat kontrol untuk menjalankan berbagai skenario simulasi lalu lintas data organik untuk menguji ketahanan dan performa sistem.

-   **Kegunaan:**
    -   **Memilih Skenario:** Pengguna dapat memilih skenario simulasi yang telah didefinisikan (contoh: `pddikti_auth`, `sevima_cloud`, `siakad_sso`).
    -   **Mengatur Jenis Lalu Lintas:** Pengguna dapat memilih profil lalu lintas yang akan disimulasikan, seperti:
        -   `Normal`: Lalu lintas normal sehari-hari.
        -   `Heavy Load`: Beban lalu lintas yang tinggi namun masih dalam kapasitas wajar.
        -   `Prime Time`: Simulasi jam sibuk dengan lonjakan permintaan.
        -   `Overload/Degradation`: Lalu lintas yang melebihi kapasitas untuk menguji degradasi performa.
    -   **Memulai dan Menghentikan Simulasi:** Kontrol untuk memulai dan menghentikan proses simulasi.
    -   **Visualisasi Real-time:** Menampilkan grafik dan data hasil simulasi secara langsung saat berjalan.

## 3. Halaman Monitoring Model ML (ML Model Dashboard)

Halaman ini didedikasikan untuk memantau status, kesehatan, dan performa dari model *Machine Learning* yang digunakan.

-   **Kegunaan:**
    -   **Status Model:** Menampilkan informasi detail mengenai model yang aktif, termasuk:
        -   **Nama Model** dan **Versi Aktif**.
        -   **Tahap Model:** Menunjukkan apakah model berada dalam fase `Cold Start` (baru mulai dan belum banyak belajar), `Learning` (sedang aktif belajar dari data baru), atau `Mature` (sudah stabil).
        -   **Akurasi:** Metrik akurasi prediksi dari model.
        -   **Tanggal Pelatihan Terakhir:** Informasi kapan model terakhir kali diperbarui atau dilatih ulang.
    -   **Grafik Performa:** Visualisasi metrik performa model dari waktu ke waktu.

## 4. Halaman Pengaturan (Admin/Settings)

Halaman ini menyediakan akses untuk konfigurasi dan tugas-tugas administratif.

-   **Kegunaan:**
    -   Manajemen kunci API atau kredensial akses.
    -   Pengaturan parameter sistem atau konfigurasi-konfigurasi lainnya yang bersifat global.

## 5. Halaman Dokumentasi (Docs/Help)

Halaman ini berisi panduan dan dokumentasi teknis mengenai penggunaan aplikasi dan arsitekturnya.

-   **Kegunaan:**
    -   Menyediakan panduan bagi pengguna baru.
    -   Menjadi referensi teknis bagi administrator atau pengembang.
