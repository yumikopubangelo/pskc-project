# Dokumentasi Deteksi Penyimpangan Konsep (EWMA & ADWIN)

Dokumen ini menjelaskan mekanisme deteksi penyimpangan konsep (*concept drift*) yang digunakan oleh model Machine Learning (ML) dalam sistem ini. Deteksi ini krusial untuk memastikan model tetap akurat seiring waktu dengan cara memicu pelatihan ulang (retraining) secara otomatis ketika performanya menurun.

## 1. Apa itu Concept Drift?

Concept drift terjadi ketika pola statistik pada data yang diprediksi oleh model berubah dari waktu ke waktu. Dalam konteks sistem ini, ini berarti pola akses pengguna terhadap *keys* berubah, sehingga prediksi model tentang kunci mana yang akan diakses berikutnya menjadi kurang akurat. Jika tidak ditangani, ini akan menyebabkan penurunan *cache hit rate* dan peningkatan latensi.

Sistem ini menggunakan pendekatan hibrida canggih yang terinspirasi dari beberapa metode akademis untuk mendeteksi drift secara otomatis dan andal.

## 2. Algoritma Inti yang Digunakan

Sistem menggabungkan tiga metode utama untuk mendapatkan deteksi yang kuat dan sensitif.

### a. EWMA (Exponentially Weighted Moving Average)

EWMA adalah sebuah teknik statistik untuk menganalisis data dari waktu ke waktu (time series) dengan memberikan bobot atau "kepentingan" yang berbeda pada setiap data. Perbedaan utamanya dengan rata-rata biasa (*Simple Moving Average*) adalah **data yang lebih baru dianggap lebih penting daripada data yang lebih lama.** Ini membuatnya sangat efektif untuk melacak tren dan perubahan secara *real-time*.

#### Bagaimana Cara Kerjanya?

Bayangkan Anda ingin melacak akurasi (cache hit rate) dari model Anda. Setiap kali ada permintaan, hasilnya adalah "hit" (1) atau "miss" (0). Rumus dasar untuk menghitung EWMA adalah:

`EWMA_sekarang = (alpha * nilai_baru) + ((1 - alpha) * EWMA_sebelumnya)`

-   `nilai_baru`: Hasil terbaru (1 atau 0).
-   `EWMA_sebelumnya`: Nilai EWMA yang dihitung pada langkah sebelumnya.
-   `alpha`: **Faktor pembobotan** (sebuah angka antara 0 dan 1). Inilah parameter kunci yang mengontrol sensitivitas EWMA.

#### Peran `alpha` (Faktor Pembobotan)

Nilai `alpha` menentukan seberapa cepat EWMA "melupakan" data lama dan beradaptasi dengan data baru.

-   **`alpha` tinggi (misal, 0.9):** EWMA akan sangat dipengaruhi oleh data terbaru. Nilai EWMA akan berubah secara drastis mengikuti data baru. Ini cocok untuk melacak perubahan jangka pendek.
-   **`alpha` rendah (misal, 0.1):** EWMA akan lebih stabil dan perubahannya lebih halus. Data lama memiliki pengaruh yang lebih besar, sehingga EWMA merepresentasikan tren jangka panjang.

#### Strategi Dua EWMA: Jangka Pendek vs. Jangka Panjang

Di sistem ini, kita tidak hanya menggunakan satu EWMA, tetapi dua, untuk menciptakan sebuah mekanisme deteksi yang cerdas:

1.  **`ewma_short` (EWMA Jangka Pendek):**
    -   Menggunakan `alpha` yang **relatif tinggi**.
    -   **Tujuan:** Untuk mendapatkan gambaran performa model **saat ini**. Nilai ini sangat reaktif dan akan cepat naik atau turun berdasarkan beberapa hasil *cache* terakhir. Anggap saja ini adalah "performa 5 menit terakhir".

2.  **`ewma_long` (EWMA Jangka Panjang):**
    -   Menggunakan `alpha` yang **sangat rendah**.
    -   **Tujuan:** Untuk mendapatkan gambaran performa model yang **stabil dan historis**. Karena `alpha`-nya rendah, nilai ini tidak akan banyak terpengaruh oleh beberapa kesalahan kecil yang terjadi sesekali. Anggap saja ini adalah "performa rata-rata selama satu jam terakhir".

#### Momen Deteksi

"Keajaiban" terjadi ketika kita membandingkan kedua nilai ini:

-   **Kondisi Normal:** Jika model bekerja dengan baik, `ewma_short` akan berfluktuasi di sekitar `ewma_long`. Keduanya akan bernilai kurang lebih sama.
-   **Terjadi Penurunan Performa:** Ketika pola data mulai berubah (*concept drift*), model akan lebih sering salah. Akibatnya:
    -   `ewma_short` akan **turun drastis** karena sangat reaktif.
    -   `ewma_long` akan turun **sangat perlahan** karena ia lebih "keras kepala" dan memegang data historis.
-   **Deteksi Drift:** Sistem menghitung `ewma_drop = ewma_long - ewma_short`. Ketika selisih ini menjadi cukup besar dan melampaui ambang batas (`threshold`), sistem menyimpulkan bahwa performa saat ini secara signifikan lebih buruk daripada performa historis. Ini adalah sinyal kuat bahwa *concept drift* telah terjadi, dan model perlu dilatih ulang.

### b. ADWIN-like Adaptive Windowing

ADWIN (ADaptive WINdowing) adalah metode yang membandingkan perilaku data dari dua periode waktu yang berbeda.

- **Cara Kerja:** Sistem memelihara sebuah "jendela" (*window*) dari hasil *cache hit* terbaru (misalnya, 200 hasil terakhir).
    - Jendela ini dibagi menjadi dua bagian: "lama" dan "baru".
    - Sistem kemudian melakukan uji statistik untuk memeriksa apakah rata-rata akurasi di bagian "baru" secara signifikan berbeda dari bagian "lama".
- **Deteksi:** Jika ada perbedaan statistik yang signifikan, ini dianggap sebagai bukti kuat bahwa telah terjadi perubahan perilaku, dan sebuah *drift* terdeteksi.

### c. EDDM (Early Drift Detection Method)

EDDM adalah metode pelengkap yang dirancang untuk memberikan peringatan dini dengan menganalisis jarak antar kesalahan prediksi. Jika jarak rata-rata antar kesalahan mulai menurun, ini bisa menjadi indikasi awal dari adanya *drift*.

## 3. Logika Deteksi & Tindakan

Ketiga algoritma di atas tidak bekerja sendiri-sendiri, melainkan digabungkan dalam sebuah sistem skoring untuk membuat keputusan akhir.

1.  **Pengumpulan Skor:** Setiap kali sebuah *cache outcome* direkam, setiap algoritma (EWMA, ADWIN) memberikan "suara" atau "skor" jika mereka mendeteksi perubahan.
2.  **Keputusan:**
    - **Drift Dideteksi:** Jika `drift_score` (skor gabungan) melampaui ambang batas (misalnya, 2 poin), sistem secara resmi mendeklarasikan adanya *concept drift*.
    - **Warning Dideteksi:** Jika `warning_score` melampaui ambang batas, sistem hanya mencatatnya sebagai peringatan.
3.  **Tindakan Otomatis:**
    - Ketika **drift** terdeteksi, sistem secara otomatis **memicu proses pelatihan ulang (retraining) model ML** menggunakan data terbaru yang telah dikumpulkan.
    - Setelah proses retraining selesai, *window* jangka pendek dari detektor di-reset untuk memberikan model yang baru sebuah "kesempatan" untuk membuktikan performanya.

## 4. Menginterpretasikan Data dari API

Endpoint API `/ml/status` atau `/ml/drift` menyediakan statistik dari `DriftDetector` yang bisa Anda gunakan untuk memonitor kesehatan model.

- **`ewma_short`**: Akurasi (cache hit rate) model dalam jangka pendek.
- **`ewma_long`**: Akurasi model dalam jangka panjang (historis).
- **`ewma_drop`**: Selisih antara `ewma_long` dan `ewma_short`. Nilai positif yang besar mengindikasikan penurunan performa.
- **`drift_count`**: Jumlah total *drift* yang telah terdeteksi sejak sistem dimulai.
- **`warning_count`**: Jumlah total *warning* yang telah terdeteksi.
- **`drift_threshold` / `warning_threshold`**: Nilai ambang batas yang saat ini dikonfigurasi untuk `ewma_drop` agar memicu deteksi.
