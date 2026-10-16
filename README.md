# Penerima Tamu (Visitor Counter)

Aplikasi desktop untuk mencatat dan menghitung pengunjung dengan **face recognition**: perpustakaan, kantor, layanan publik, museum, ruang baca, atau lokasi lain. Anggota cukup menghadap kamera, lalu kunjungannya tercatat dan mereka disambut dengan sapaan suara. Tamu non-anggota dicatat lewat form singkat, dan wajah yang tidak dikenal tetap terhitung sebagai pengunjung anonim.

**Stack:** Python 3.11+ · PySide6 (Qt 6 + QtMultimedia) · OpenCV DNN (deteksi YuNet, pengenalan SFace, anti-spoofing MiniFASNet) · SQLite/SQLAlchemy · pandas/openpyxl · gTTS

## Fitur
- **Kunjungan:** wajah anggota dikenali otomatis dari kamera lalu kunjungan dicatat. Ada jeda catat ulang supaya orang yang sama tidak tercatat berkali-kali. Tersedia juga input manual (No. anggota / scan barcode) dan form tamu non-anggota.
- **Beberapa wajah sekaligus:** semua anggota yang dikenali dalam satu frame dicatat bersamaan dan disapa dalam satu sapaan ("Selamat pagi, Siti dan Budi!"). Konfirmasi wajah dihitung per orang. Bisa diubah ke mode satu wajah terdekat, dan jumlah maksimal wajah per frame bisa diatur.
- **Pengunjung anonim:** wajah yang tidak dikenali dan terlihat stabil beberapa frame dihitung sebagai kunjungan "Anonim" (hanya waktunya yang dicatat). Supaya orang yang sama tidak terhitung berulang, wajahnya diingat **di memori saja** selama jeda catat ulang, lalu dibuang. Kalau orang itu kemudian scan kartu atau mengisi form tamu, catatan anonimnya dihapus otomatis agar tidak ganda. Jumlahnya perkiraan, dan fitur ini bisa dimatikan di Pengaturan.
- **Anti-spoofing:** wajah dari foto cetak atau layar HP ditolak, baik saat kunjungan maupun registrasi, memakai MiniFASNet (sekitar 3 ms per wajah di CPU). Ambang skornya bisa diatur di Pengaturan.
- **Bantuan registrasi:** auto-complete nomor induk dan nama (anggota lokal + pencarian direktori), serta **tebakan identitas dari foto profil direktori**: wajah di kamera dicocokkan ke galeri foto, lalu beberapa calon terdekat ditampilkan untuk dipilih.
- **Registrasi Anggota:** mengambil beberapa sampel wajah, wajib dengan persetujuan data biometrik. Ada peringatan bila wajahnya mirip anggota lain.
- **Data Anggota:** cari, hapus data wajah, atau hapus anggota. Riwayat kunjungan anggota yang dihapus tetap ada tetapi dianonimkan.
- **Laporan:** filter per rentang tanggal dan ekspor Excel (sheet detail + rekap harian per kategori).
- **Sapaan:** pesan sambutan sesuai jam ("Selamat pagi/siang/sore/malam"). Templatenya bisa diubah, lalu ditampilkan di layar dan diucapkan.
- **Suara:** bunyi notifikasi (bawaan atau file sendiri) dan text-to-speech via gTTS. Sapaan disimpan di cache MP3, jadi yang pernah diucapkan tetap bisa diputar saat offline.
- **Pengaturan:** semua parameter (kamera, ambang pengenalan, jeda catat ulang, sapaan, suara, volume) diubah dari tab Pengaturan dan langsung berlaku.
- **Jendela Mode Kios:** jendela layar penuh terpisah khusus pencatatan, dengan kamera, sapaan besar, input scan kartu/NIM, tombol tamu, dan daftar kunjungan hari ini. Dibuka lewat tombol "Mode Kios" atau F10. Kalau ada monitor kedua, otomatis tampil di sana. Untuk keluar tekan Esc; kalau kunci admin aktif, wajib PIN/login admin. Bisa diatur agar langsung terbuka saat aplikasi dimulai.
- **Kunci admin:** PIN admin dan/atau login admin eksternal mengunci tab selain Kunjungan, dan terkunci lagi otomatis saat kembali ke tab Kunjungan.
- **Integrasi opsional:** lookup data anggota dari API direktori dan login admin via OAuth2/OpenID Connect (lihat di bawah).
- **Backup otomatis:** database dibackup sekali sehari ke `data/backups/` atau folder pilihan (mis. flashdisk), dengan menyimpan N salinan terakhir. Backup manual tetap tersedia.
- **Privasi layar kios:** secara default layar kios hanya menampilkan jumlah pengunjung hari ini, bukan nama pengunjung lain.
- **Lain-lain:** layar penuh (F11) dan log ke `data/app.log`.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/library-visitor --download-models   # ±39 MB, otomatis juga saat pertama dijalankan
.venv/bin/library-visitor
```
Di Linux, user perlu akses ke `/dev/video*`, biasanya lewat grup `video`: `sudo usermod -aG video $USER`, lalu login ulang.

## Lisensi
Aplikasi wajib diaktivasi dengan key lisensi. Saat dibuka tanpa lisensi yang valid (belum ada atau sudah kedaluwarsa), hanya dialog aktivasi yang tampil.
- Key memuat nama institusi pemegang lisensi dan masa berlakunya. Key ditandatangani Ed25519 dan diverifikasi offline memakai kunci publik di `src/library_visitor/licensing.py`.
- Key tersimpan di `data/license.key`. Untuk menggantinya, buka **Pengaturan → Identitas Perpustakaan → Ganti Lisensi...**
- Lisensi yang kedaluwarsa saat aplikasi sedang berjalan terdeteksi dalam pengecekan per jam, lalu dialog aktivasi muncul.
- Key dibuat dengan aplikasi **license-generator** di folder terpisah (tidak ada di repo ini), karena folder itu menyimpan kunci privat.

## Registrasi via web (LAN)
Anggota bisa didaftarkan dari HP atau laptop petugas lewat browser, dengan wajah difoto memakai kamera perangkat itu.
- Aktifkan di **Pengaturan → Registrasi via Web (LAN)** dan tentukan port (default 8443). Fitur ini butuh **PIN admin**, yang juga dipakai untuk login di web.
- Buka alamat yang ditampilkan (mis. `https://192.168.1.20:8443`) dari perangkat di jaringan yang sama. Sertifikat HTTPS dibuat otomatis di `data/web/`, karena browser hanya mengizinkan kamera di halaman HTTPS. Peringatan sertifikat muncul sekali per perangkat; pilih lanjutkan.
- Isi data (dengan auto-complete, lookup, dan foto profil direktori), ambil beberapa foto wajah, centang persetujuan, lalu simpan. Foto diproses di PC dengan model wajah dan anti-spoofing yang sama dengan aplikasi, lalu dibuang. Yang disimpan hanya embedding.
- Dokumentasi API (endpoint, autentikasi, contoh `curl`, dan kontrak integrasi direktori) tersedia di `https://<IP-PC>:<port>/docs`.
- Keamanan: hanya alamat jaringan lokal yang diterima. Setelah 5 kali PIN salah, alamat IP tersebut dikunci 60 detik. Sesi login berlaku 8 jam dan disimpan di cookie HttpOnly/Secure/SameSite=Strict. Saat pertama aktif, Windows akan meminta izin firewall untuk port tersebut.

## Identitas lokasi
Diatur di **Pengaturan → Identitas Lokasi**: nama lokasi (mis. Perpustakaan Pusat, Kantor Dinas, Museum Kota), alamat, kontak, dan logo. Logo disalin ke `data/logo.png`. Nama institusi diambil dari lisensi. Identitas ini tampil di header aplikasi, layar Mode Kios, dan sheet **Info** pada ekspor Excel.

## Konfigurasi
Pengaturan aplikasi diubah dari tab **Pengaturan** dan disimpan di `data/settings.json`.
Lokasi folder data/model bisa dipindah dengan environment variable `LV_HOME`.

Placeholder sapaan: `{salam}`, `{nama}`, `{nama_depan}`, `{kategori}`, `{lokasi}`. Template lama yang memakai `{perpustakaan}` tetap berfungsi.

**Lupa PIN admin?** Tutup aplikasi (dari Mode Kios, tekan Esc lalu **Tutup Aplikasi**), kemudian jalankan `library-visitor --reset-pin <PIN baru>` (versi terinstal: `penerima-tamu --reset-pin <PIN baru>`). PIN berupa angka, minimal 4 digit.

Panduan pengguna bergambar ada di [`src/library_visitor/docs/Panduan-Penerima-Tamu.pdf`](src/library_visitor/docs/Panduan-Penerima-Tamu.pdf), dan bisa dibuka dari tombol **Panduan** di aplikasi.

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
**Opsional, foto profil:** bila objek anggota memuat `photo` (JPEG/PNG base64 atau URL), `photo_url`, atau `picture`, fotonya ditampilkan di form Registrasi. Foto hanya ditampilkan di memori dan tidak disimpan. Kredensial API hanya ikut dikirim bila URL foto berada di host yang sama dengan `DIRECTORY_LOOKUP_URL`.

`category` dikenali sebagai `Mahasiswa`, `Dosen`, atau `Staf`; nilai lain menjadi `Umum`. Hanya field di atas yang dipakai, dan respons mentah tidak pernah disimpan atau ditulis ke log.
Sebaiknya API key yang dipakai hanya punya akses ke endpoint lookup ini, dengan data seminimal mungkin.

Tes koneksi: `.venv/bin/library-visitor --lookup <nomor>`

**Opsional, auto-complete:** isi `DIRECTORY_SEARCH_URL`. Aplikasi memanggil `GET <url>?q=<teks>&limit=<n>` (minimal 3 karakter) dan mengharapkan `{"status": true, "data": [<objek anggota>, ...]}`.

**Opsional, galeri foto (tebakan identitas saat registrasi):** isi `DIRECTORY_FACES_URL`. Aplikasi memanggil `GET <url>?page=<n>&per_page=100[&updated_since=<ISO8601>]` dan mengharapkan:
```json
{"status": true,
 "data": [{"member_no": "...", "name": "...", "category": "...", "unit": "...", "status": "...",
           "photo": "<JPEG base64>", "photo_updated_at": "2026-10-01T08:00:00"}],
 "meta": {"current_page": 1, "last_page": 12, "total": 1150}}
```
Foto hanya diproses di memori menjadi embedding wajah lalu dibuang. Yang disimpan hanya embedding dan data minimal di atas. Sinkron berjalan otomatis sekali sehari (inkremental lewat `updated_since`) atau manual dari **Pengaturan → Galeri Foto Direktori**. Di sana juga bisa diatur filter isi galeri (kategori, awalan nomor induk, status), jumlah tebakan, dan kemiripan minimal.
> Galeri ini berisi data biometrik orang yang belum tentu memberi persetujuan langsung. Pastikan institusi memiliki dasar pemrosesan yang sah (UU PDP), dan batasi isinya seperlunya lewat filter di server maupun di aplikasi.

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
  backups.py         backup harian otomatis + rotasi
  gallery.py         galeri embedding dari foto direktori + sinkron
  face/              engine YuNet+SFace, matcher, anti-spoofing, unduh model
  ui/                jendela utama, halaman-halaman, jendela Mode Kios
tests/               pytest
packaging/           spec PyInstaller, ikon, installer Linux & Windows
```

## Pengembangan
```bash
.venv/bin/pytest
.venv/bin/ruff check src tests && .venv/bin/ruff format src tests
```

## Installer
Paket siap pakai untuk PC di lokasi. Model wajah sudah dibundel, jadi tidak perlu internet saat pertama dijalankan.

### Windows
Build di Windows dengan Python 3.11+ dan [Inno Setup 6](https://jrsoftware.org/isdl.php):
```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```
Hasilnya `dist\PenerimaTamuPerpustakaan-<versi>-setup.exe`. Installer ini:
- bisa dipasang tanpa hak admin (untuk user saat ini) atau untuk semua user,
- membuat shortcut Start Menu, opsional shortcut desktop, dan opsional **jalan otomatis saat Windows dinyalakan** (untuk PC kios),
- menyimpan data di `%LOCALAPPDATA%\PenerimaTamuPerpustakaan`. Taruh `.env` di folder ini. Data tidak ikut terhapus saat uninstall.

### Linux
```bash
bash packaging/linux/build.sh          # -> dist/penerima-tamu-perpustakaan-<versi>-linux-<arch>.tar.gz
```
Di PC tujuan, ekstrak lalu jalankan `./install.sh` (tambahkan `--autostart` untuk jalan otomatis saat login). Aplikasi terpasang untuk user saat ini tanpa sudo, muncul di menu aplikasi, dan bisa dijalankan dengan perintah `penerima-tamu`. Data dan `.env` ada di `~/.local/share/penerima-tamu-perpustakaan/`. Hapus dengan `./uninstall.sh` (`--purge` untuk ikut menghapus data).

Di sesi X11, Qt butuh paket sistem `libxcb-cursor0` (Debian/Ubuntu: `sudo apt install libxcb-cursor0`). Di sesi Wayland paket ini tidak diperlukan.

### Build otomatis (GitHub Actions)
Workflow `.github/workflows/build-installers.yml` membangun installer Windows dan Linux. Jalankan manual dari tab Actions, atau otomatis saat tag `v*` di-push. Hasilnya bisa diunduh sebagai artifact.

## Lisensi model
- YuNet dan SFace (OpenCV Zoo) memakai lisensi Apache-2.0 dan diunduh saat pertama kali dijalankan.
- MiniFASNet dari [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) (Minivision AI) juga berlisensi Apache-2.0. Modelnya dikonversi ke ONNX dan disertakan di `src/library_visitor/face/antispoof_models/`, beserta `LICENSE` dan `NOTICE`.

## Privasi (UU No. 27/2022 PDP)
Yang disimpan hanya embedding wajah (vektor 128 angka), bukan foto. Embedding hanya disimpan bila persetujuan dicentang saat registrasi, dan bisa dihapus kapan saja dari halaman Data Anggota.
