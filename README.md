# Penerima Tamu Perpustakaan

Aplikasi desktop untuk mencatat pengunjung perpustakaan dengan **face recognition**: anggota cukup menghadap kamera, lalu kunjungannya tercatat dan mereka disambut dengan sapaan suara.

**Stack:** Python 3.11+ · PySide6 (Qt 6 + QtMultimedia) · OpenCV DNN (deteksi YuNet + pengenalan SFace) · SQLite/SQLAlchemy · pandas/openpyxl · gTTS

## Fitur
- **Kunjungan:** wajah anggota dikenali otomatis dari kamera lalu kunjungan dicatat. Ada jeda catat ulang supaya orang yang sama tidak tercatat berkali-kali. Tersedia juga input manual (No. anggota / scan barcode) dan form tamu non-anggota.
- **Registrasi Anggota:** mengambil beberapa sampel wajah, wajib dengan persetujuan data biometrik. Ada peringatan bila wajahnya mirip anggota lain.
- **Data Anggota:** cari, hapus data wajah, atau hapus anggota. Riwayat kunjungan anggota yang dihapus tetap ada tetapi dianonimkan.
- **Laporan:** filter per rentang tanggal dan ekspor Excel (sheet detail + rekap harian per kategori).
- **Sapaan:** pesan sambutan sesuai jam ("Selamat pagi/siang/sore/malam"). Templatenya bisa diubah, lalu ditampilkan di layar dan diucapkan.
- **Suara:** bunyi notifikasi (bawaan atau file sendiri) dan text-to-speech via gTTS. Sapaan disimpan di cache MP3, jadi yang pernah diucapkan tetap bisa diputar saat offline.
- **Pengaturan:** semua parameter (kamera, ambang pengenalan, jeda catat ulang, sapaan, suara, volume) diubah dari tab Pengaturan dan langsung berlaku.
- **Mode kios:** PIN admin dan/atau login admin eksternal mengunci tab selain Kunjungan, dan terkunci lagi otomatis saat kembali ke tab Kunjungan.
- **Integrasi opsional:** lookup data anggota dari API direktori dan login admin via OAuth2/OpenID Connect (lihat di bawah).
- **Lain-lain:** backup database, layar penuh (F11), dan log ke `data/app.log`.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/library-visitor --download-models   # ±39 MB, otomatis juga saat pertama dijalankan
.venv/bin/library-visitor
```
Di Linux, user perlu akses ke `/dev/video*`, biasanya lewat grup `video`: `sudo usermod -aG video $USER`, lalu login ulang.

## Konfigurasi
Pengaturan aplikasi diubah dari tab **Pengaturan** dan disimpan di `data/settings.json`.
Lokasi folder data/model bisa dipindah dengan environment variable `LV_HOME`.

Placeholder sapaan: `{salam}`, `{nama}`, `{nama_depan}`, `{kategori}`, `{perpustakaan}`.

> gTTS membutuhkan internet dan mengirim teks sapaan (termasuk nama anggota) ke server Google.
> Matikan "Ucapkan sapaan" bila hal ini tidak diizinkan kebijakan privasi instansi.

## Integrasi opsional
Kedua integrasi aktif hanya jika variabelnya diisi di file `.env`. Tanpa itu, aplikasi berjalan penuh secara lokal.

```bash
cp .env.example .env    # isi variabel yang dibutuhkan
chmod 600 .env          # berisi kredensial: jangan commit/bagikan
```

### 1. Direktori anggota (lookup saat registrasi)
Saat registrasi, ketik nomor induk anggota. Nama, kategori, unit, dan status akan terisi dari API direktori milik institusi.

| Variabel | Keterangan |
|---|---|
| `DIRECTORY_LOOKUP_URL` | URL lookup dengan placeholder `{nomor}`, mis. `https://contoh.ac.id/api/members/{nomor}/` |
| `DIRECTORY_API_KEY`, `DIRECTORY_API_SECRET` | Dikirim sebagai header `X-API-Key` dan `X-API-Secret` |

Kontrak respons yang diharapkan:
```json
GET /api/members/2021010123/
200 {"status": true, "data": {"member_no": "2021010123", "name": "Siti Aminah",
     "category": "Mahasiswa", "unit": "Informatika", "status": "Aktif"}}
404 anggota tidak ditemukan
```
`category` dikenali sebagai `Mahasiswa`, `Dosen`, atau `Staf`; nilai lain menjadi `Umum`. Hanya field di atas yang dipakai, dan respons mentah tidak pernah disimpan atau ditulis ke log.
Sebaiknya API key yang dipakai hanya punya akses ke endpoint lookup ini, dengan data seminimal mungkin.

Tes koneksi: `.venv/bin/library-visitor --lookup <nomor>`

### 2. Login admin via OAuth2 / OpenID Connect
Dialog akses admin menampilkan tombol login eksternal. Alurnya memakai authorization code + PKCE (S256) dengan klien public tanpa secret, dan redirect loopback ke `http://127.0.0.1:8765/callback`. Daftarkan redirect URI ini persis di penyedia identitas.

| Variabel | Keterangan |
|---|---|
| `OAUTH_AUTHORIZE_URL`, `OAUTH_TOKEN_URL`, `OAUTH_USERINFO_URL` | Endpoint penyedia identitas |
| `OAUTH_CLIENT_ID` | ID klien public |
| `OAUTH_REDIRECT_URI` | Default `http://127.0.0.1:8765/callback` |
| `OAUTH_SCOPE` | Default `openid profile email` |
| `OAUTH_LABEL` | Teks tombol, default "Masuk dengan akun institusi" |

Userinfo dibaca dari `preferred_username` (atau `sub`), `name`, dan `groups`. Username atau grup yang boleh masuk diatur di **Pengaturan → Keamanan**. Token hanya dipakai sekali untuk membaca userinfo lalu dibuang.
Tetap isi **PIN admin sebagai cadangan**, supaya Pengaturan masih bisa dibuka saat penyedia identitas tidak dapat diakses.

## Struktur
```
src/library_visitor/
  config.py          pengaturan (settings.json) + PIN admin
  greeting.py        template sapaan
  audio.py           bunyi notifikasi + TTS (gTTS) dengan antrean & cache
  db.py              model SQLAlchemy (members, visits) + migrasi ringan
  services.py        logika registrasi, kunjungan, query
  reports.py         ekspor Excel
  camera.py          QThread kamera + deteksi/pengenalan
  extensions.py      antarmuka integrasi opsional (direktori, login admin)
  directory_api.py   klien API direktori anggota (read-only, field minimal)
  oidc_login.py      login admin OAuth2/OIDC (PKCE, redirect loopback)
  face/              engine YuNet+SFace, matcher, unduh model
  ui/                jendela utama & halaman-halaman
tests/               pytest
```

## Pengembangan
```bash
.venv/bin/pytest
.venv/bin/ruff check src tests && .venv/bin/ruff format src tests
```

## Build executable
```bash
.venv/bin/pip install -e ".[build]"
.venv/bin/pyinstaller --name LibraryVisitor --windowed src/library_visitor/__main__.py
```
Salin folder `models/` ke samping executable, atau biarkan aplikasi mengunduhnya saat pertama dijalankan.

## Privasi (UU No. 27/2022 PDP)
Yang disimpan hanya embedding wajah (vektor 128 angka), bukan foto. Embedding hanya disimpan bila persetujuan dicentang saat registrasi, dan bisa dihapus kapan saja dari halaman Data Anggota.
