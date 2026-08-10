# Freebuff GitHub Farmer

Otomasi farming **token freebuff (Codebuff)** — AI coding assistant gratis — menggunakan akun GitHub via **OAuth + auto-polling kode verifikasi IMAP**. Hasil akhirnya berupa `authToken` yang bisa dipakai langsung sebagai Bearer token ke endpoint model AI, atau dikombinasikan (dipisah koma) sebagai `FREEBUFF_TOKEN` di [freebuff2api-workers](https://github.com/pingmike2/freebuff2api-wokers).

> ⚠️ **Disclaimer**: Proyek ini untuk keperluan edukasi & penggunaan pribadi. Pastikan kamu mematuhi ToS layanan yang dipakai. Gunakan dengan risiko sendiri.

---

## Daftar Isi

- [Fitur](#fitur)
- [Arsitektur / Alur Kerja](#arsitektur--alur-kerja)
- [Persyaratan](#persyaratan)
- [Instalasi](#instalasi)
- [Konfigurasi](#konfigurasi)
  - [1. `.env` — kredensial IMAP](#1-env--kredensial-imap)
  - [2. `accounts.txt` — daftar akun GitHub](#2-accountstxt--daftar-akun-github)
  - [3. `freebuff_tools/extract_freebuff.py`](#3-freebuff_toolsextract_freebuffpy)
- [Cara Pakai](#cara-pakai)
  - [Mode 1: Satu akun (single)](#mode-1-satu-akun-single)
  - [Mode 2: Batch banyak akun](#mode-2-batch-banyak-akun)
  - [Mode 3: Manual / semi-otomatis](#mode-3-manual--semi-otomatis)
- [File Output](#file-output)
- [Deploy ke Cloudflare Worker (freebuff2api)](#deploy-ke-cloudflare-worker-freebuff2api)
- [Pemecahan Masalah (Troubleshooting)](#pemecahan-masalah-troubleshooting)
- [Keamanan & Privasi](#keamanan--privasi)
- [Lisensi](#lisensi)

---

## Fitur

| Fitur | Keterangan |
|---|---|
| **OAuth GitHub** | Login via tombol "Continue with GitHub" di codebuff.com — tidak perlu email random |
| **Auto-polling IMAP** | Kode verifikasi perangkat GitHub (device verification) diambil otomatis dari inbox Gmail (bisa via iCloud Hide My Email + forwarding) |
| **Batch farming** | Satu perintah untuk banyak akun; otomatis skip akun yang sudah di-farm |
| **Resume / skip list** | `skipped.txt` + skip otomatis dari `freebuff_credentials.json` |
| **Tanpa dependensi berat** | `extract_freebuff.py` murni stdlib Python; `playwright` untuk otomasi browser |
| **Anti-overwrite token** | Token dibaca dari output proses (regex UUID), bukan dari `freebuff_credentials.json` yang **ditimpa** tiap run |

---

## Arsitektur / Alur Kerja

```
┌──────────────┐   1. auth_code     ┌──────────────────────────┐
│ extract_     │ ─────────────────▶ │ codebuff.com/login?      │
│ freebuff.py  │                    │ auth_code=...            │
└──────────────┘                    └───────────┬──────────────┘
        ▲                                       │ 2. Klik "Continue with GitHub"
        │ 6. token                              ▼
        │                              ┌──────────────────────────┐
        │                              │ github.com/login         │
        │                              │ (isi email + password)   │
        │                              └───────────┬──────────────┘
        │                                          │ 3. Device verification
        │                                          ▼
        │                              ┌──────────────────────────┐
        │                              │ Gmail IMAP               │
        │                              │ (email_imap.py           │
        │                              │  wait_code)              │
        │                              └───────────┬──────────────┘
        │                                          │ 4. Kode 6 digit
        │                                          ▼
        │                              ┌──────────────────────────┐
        │                              │ GitHub verify → redirect │
        │                              │ → codebuff Authorize     │
        └──────────────────────────────┴───────────┬──────────────┘
                                                   │ 5. /api/auth/cli/status
                                                   ▼
                                       authToken (UUID) → tokens.txt
```

**Alur detail (batch):**

1. `freebuff_batch_farm.py` menjalankan `extract_freebuff.py login` di background → menghasilkan link `https://www.codebuff.com/login?auth_code=...`
2. Playwright membuka link, klik **Continue with GitHub**, isi email+password akun GitHub
3. GitHub mengirim kode verifikasi perangkat ke inbox email akun (bisa lewat iCloud HME yang di-forward ke Gmail)
4. `email_imap.wait_code()` polling Gmail IMAP → menangkap kode → diisi otomatis di browser
5. Redirect balik ke codebuff → klik **Authorize** → `extract_freebuff.py` mendeteksi login sukses
6. Token (UUID) diekstrak dari output proses → **langsung di-append ke `tokens.txt`**

> ⚠️ **Penting**: `extract_freebuff.py` **menimpa** `freebuff_credentials.json` setiap run. Jangan membaca token dari file itu di dalam loop batch — baca dari output proses (seperti yang dilakukan script ini).

---

## Persyaratan

- **Python 3.9+**
- **Gmail** dengan **App Password** (aktifkan 2FA → [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords))
- **Playwright + Chromium**: `pip install playwright && playwright install chromium`
- (Opsional) **Xvfb** untuk mode headful di server tanpa display: `Xvfb :99 -screen 0 1920x1080x24 &`
- Akun GitHub aktif (lihat [Konfigurasi](#konfigurasi) — akun bisa didapat dari hasil farming lain)

---

## Instalasi

```bash
git clone https://github.com/<username>/freebuff-farmer.git
cd freebuff-farmer

# (Opsional) venv
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt   # playwright
playwright install chromium       # unduh browser chromium

cp .env.example .env
# ... isi .env (lihat Konfigurasi)
```

---

## Konfigurasi

### 1. `.env` — kredensial IMAP

```ini
# .env (jangan di-commit — sudah di .gitignore)
IMAP_HOST=imap.gmail.com
IMAP_USER=you@gmail.com
IMAP_APP_PASSWORD=your_gmail_app_password

DISPLAY=:99        # dipakai kalau mode headful (Xvfb)
HEADLESS=true      # true = tanpa jendela browser (disarankan untuk server)
```

| Variabel | Wajib? | Default | Keterangan |
|---|---|---|---|
| `IMAP_HOST` | Tidak | `imap.gmail.com` | Server IMAP Gmail |
| `IMAP_USER` | **Ya** | — | Email Gmail tujuan polling kode |
| `IMAP_APP_PASSWORD` | **Ya** | — | App Password Gmail (16 karakter, tanpa spasi) |
| `DISPLAY` | Tidak | `:99` | Display X server (Xvfb) untuk headful |
| `HEADLESS` | Tidak | `true` | Mode browser: `true` = headless |

### 2. `accounts.txt` — daftar akun GitHub

Format: satu akun per baris, dipisah `:` atau `|`, **wajib urutan `email:password:username`**:

```
you@example.com:Password123:your_username
another@mail.com:Passw0rd!:user2
```

> Baris yang diawali `#` diabaikan (komentar).

### 3. `freebuff_tools/extract_freebuff.py`

Script resmi dari [pingmike2/freebuff2api-wokers](https://github.com/pingmike2/freebuff2api-wokers). Dipakai untuk:

- Generate link OAuth (`login`)
- Polling status auth (`/api/auth/cli/status`)
- Simpan credential (`freebuff_credentials.json`)

Command yang tersedia:

```bash
python3 freebuff_tools/extract_freebuff.py login    # mulai login + polling
python3 freebuff_tools/extract_freebuff.py show     # tampilkan kredensial (ter-mask)
python3 freebuff_tools/extract_freebuff.py session  # uji buka session
python3 freebuff_tools/extract_freebuff.py chat "halo"  # uji chat ke model
python3 freebuff_tools/extract_freebuff.py quota    # cek pemakaian kuota
```

---

## Cara Pakai

### Mode 1: Satu akun (single)

```bash
# Jalankan extractor, catat LOGIN_LINK yang muncul
python3 freebuff_github_auto.py --email you@example.com --password 's3cret'
```

Script akan:
1. Menjalankan `extract_freebuff.py login` di background
2. Mencetak `LOGIN_LINK=...` → **buka link itu di browser** (atau otomatiskan dengan Playwright)
3. Klik **Continue with GitHub** → isi kredensial
4. Menunggu 15 detik, lalu polling IMAP untuk kode verifikasi GitHub
5. Mencetak `VERIFICATION_CODE=...` → isi di browser
6. Menunggu `extract_freebuff.py` mendeteksi auth → mencetak `TOKEN=...`

### Mode 2: Batch banyak akun

```bash
# Farm SEMUA akun yang belum di-farm
python3 freebuff_batch_farm.py

# Batasi maksimal 5 akun per run
python3 freebuff_batch_farm.py --limit 5

# Skip email tertentu (bisa diulang)
python3 freebuff_batch_farm.py --skip someone@mail.com
```

Perilaku:

- Membaca daftar akun dari `accounts.txt`
- **Skip otomatis**: akun yang email-nya sudah ada di `freebuff_credentials.json`, `skipped.txt`, atau via `--skip`
- Setiap token sukses **langsung di-append** ke `tokens.txt`
- Di akhir run, `tokens.txt` ditulis ulang (deduplikasi) + ringkasan batch dicetak

### Mode 3: Manual / semi-otomatis

```bash
cd freebuff_tools
python3 extract_freebuff.py login
# → muncul link auth_code; buka di browser, login GitHub/Google, authorize
# → script polling otomatis, token tersimpan di freebuff_credentials.json
```

---

## File Output

| File | Isi | Git? |
|---|---|---|
| `tokens.txt` | `authToken` freebuff (UUID), satu per baris | ❌ di-ignore |
| `freebuff_tools/freebuff_credentials.json` | Kredensial terakhir (ditimpa tiap run) | ❌ di-ignore |
| `logs/` | Log per-akun (dari output extractor) | ❌ di-ignore |
| `skipped.txt` | Email yang mau di-skip manual | ❌ di-ignore |
| `auth_link.txt` | Link OAuth terakhir | ❌ di-ignore |

---

## Deploy ke Cloudflare Worker (freebuff2api)

Token yang sudah terkumpul bisa dipakai sebagai sumber kuota API:

1. Fork/deploy [freebuff2api-wokers](https://github.com/pingmike2/freebuff2api-wokers) ke Cloudflare Worker
2. Set secret `FREEBUFF_TOKEN` = semua token digabung koma:
   ```bash
   # dari tokens.txt
   TOKENS=$(paste -sd, tokens.txt)
   ```
3. Set secret `FREEBUFF_API_KEY` = password akses API kamu
4. Pakai endpoint OpenAI-compatible:
   ```
   Base URL: https://<worker>.workers.dev/v1
   API Key : <FREEBUFF_API_KEY>
   ```

Contoh uji:

```bash
curl https://<worker>.workers.dev/v1/chat/completions \
  -H "Authorization: Bearer <FREEBUFF_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek/deepseek-v4-flash","messages":[{"role":"user","content":"hi"}]}'
```

---

## Pemecahan Masalah (Troubleshooting)

| Masalah | Penyebab | Solusi |
|---|---|---|
| `No auth_code generated` | `extract_freebuff.py` gagal / jaringan diblokir | Cek koneksi ke `www.codebuff.com`; jalankan manual dulu |
| `No IMAP code found` | Kode tidak sampai ke Gmail / filter IMAP salah | Cek spam; pastikan forwarding iCloud HME aktif; coba `python3 email_imap.py <target_email>` |
| Token selalu yang terakhir saja | Salah baca dari `freebuff_credentials.json` | **Baca dari output proses** (lihat `farm_one`) — file itu ditimpa tiap run |
| `context crashed` / browser error | Playwright Chromium belum install | `playwright install chromium` |
| 403 / bot detection di github | IP di-flag GitHub | Gunakan proxy / IP bersih; jangan batch terlalu agresif |
| Rate limit GitHub OAuth | Terlalu banyak OAuth dalam waktu singkat | Beri jeda 24 jam antar gelombang; `--limit` |
| Error `tcsetattr: Inappropriate ioctl` | Proses di background tanpa TTY | Normal di background; abaikan |

---

## Keamanan & Privasi

- **`.gitignore` sudah mengunci** file sensitif: `accounts*.txt`, `tokens.txt`, `*.json` credential, `.env`, `logs/`, `state.json`, dll. Verifikasi dengan `git status` sebelum push.
- Kredensial hanya dibaca dari `.env` / `accounts.txt` lokal — jangan pernah hardcode di source.
- Jangan bagikan `tokens.txt` / `accounts.txt` — token bisa dipakai orang lain untuk memakai kuota akun kamu.
- Disarankan jalankan di VPS/container terpisah, bukan di mesin utama.

---

## Lisensi

MIT — lihat [LICENSE](LICENSE). Kode `freebuff_tools/extract_freebuff.py` © pingmike2 (MIT).
