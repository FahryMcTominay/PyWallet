# PyWallet

Wallet crypto desktop (EVM) berbasis Python + PySide6. Non-custodial: kunci wallet dibuat dan disimpan
terenkripsi di komputermu sendiri. Bawaan: **Testnet (Sepolia)**; **Mainnet (Ethereum)** bisa dipilih dari
chip di pojok kanan atas lobi.

## Menjalankan di Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Tes: `python -m pytest -q`. Data aplikasi: `%APPDATA%\PyWallet\` (database `pywallet.db` + folder `avatars`).

## Fitur saat ini (v0.3.0)

| Fitur | Keterangan |
|---|---|
| Master password + jeda 5 menit | Lobi terbuka tanpa password jika terakhir aktif < 5 menit lalu; aksi sensitif tetap minta password |
| Buat / impor wallet | Seed 12 kata (wajib verifikasi 3 kata) atau impor seed/private key |
| Ganti nama, hapus, lihat seed/private key | Dari tab Profil (hapus & lihat rahasia wajib master password) |
| **Foto profil kustom** | Pilih gambar dari komputer (PNG/JPG/WebP/BMP/GIF); di-crop persegi dari tengah dan disimpan sebagai salinan 256×256 di folder `avatars` |
| **Total aset USD / IDR / ETH** | Tombol pil di kartu saldo; pilihan diingat. Testnet = ETH Sepolia, aset testnet tidak bernilai uang (USD/IDR = 0) |
| **Mainnet / Testnet** | Chip di header lobi; pilihan diingat |
| **Logo Ethereum** | Ikon token ETH memakai logo Ethereum |
| Harga pasar | Binance (publik, tanpa API key) + kurs USD→IDR; grafik mini ETH 24 jam |
| Saldo on-chain | RPC publik (failover antar-endpoint) |
| Terima | Alamat + QR code |
| Halaman login | Font Poppins (SIL OFL 1.1, lihat `pywallet/assets/fonts/OFL.txt`), latar bercahaya, logo |
| **Tema baru** | Palet abu-abu gelap, teal, biru-teal tua, dan abu pucat; motif kucing/pita/bintang gambar sendiri (bukan gambar karakter mana pun) |
| **Hiasan latar** | Pita besar, sketsa kucing, dan bintang kecil beropacity rendah di latar; telinga kucing hanya di tombol Kirim/Terima/Trade dan ikon aplikasi. Bisa dimatikan dari Profil (pilihan diingat) |

Belum ada: Kirim dan Trade (menampilkan pesan "akan hadir"), serta daftar token mainnet yang diperluas.

### Daftar token mainnet yang diperluas (sengaja dimatikan)

Kode untuk menampilkan ETH di Base, USDT/USDC di Ethereum, dan koin populer lain (diurutkan dari aset terbesar,
saldo 0 menyusul berurutan abjad) sudah ada di `pywallet/tokens.py` dan `pywallet/portfolio.py`, tetapi dimatikan
lewat `EXTENDED_TOKEN_LIST = False` di `pywallet/config.py` sampai sesi khususnya. Selama False, lobi hanya
menampilkan ETH native. Tes jalur yang diperluas tetap dijalankan.

### Tema & motif

Warna ada di `pywallet/ui/theme.py` (satu tempat), motif di `pywallet/ui/decor.py`. Semua motif digambar dengan
kode (QPainter), tanpa file gambar. Untuk menonaktifkannya secara bawaan, ubah `ENABLED` di `decor.py`.

## Keamanan

- Seed phrase / private key dienkripsi **AES-256-GCM**; kunci diturunkan dari master password dengan **scrypt**
  dan tidak pernah disimpan. Ciphertext terikat ke alamat wallet (AAD).
- Membuat, mengimpor, melihat rahasia, dan menghapus wallet selalu meminta master password (ditegakkan di `vault.py`).
- Foto profil dan preferensi tampilan bukan data sensitif dan tidak dienkripsi. Nama file foto divalidasi agar
  database yang dimodifikasi tidak bisa menunjuk ke file di luar folder `avatars`.
- Aplikasi hanya **membaca** data jaringan (saldo, harga) lewat alamat publik; kunci tidak pernah dikirim keluar.
- **Batasan:** kode belum diaudit; pakai di testnet dulu. Data jaringan memakai endpoint publik gratis yang bisa
  dibatasi lajunya atau berubah. Lupa master password tidak bisa dipulihkan (hapus `pywallet.db`, impor ulang wallet).

## Struktur

```
main.py                    titik masuk
pywallet/
  config.py                konstanta, lokasi data, saklar EXTENDED_TOKEN_LIST
  crypto.py, db.py         enkripsi, SQLite (skema v2: kolom avatar)
  wallet_core.py, vault.py akun EVM, master password, CRUD wallet, preferensi
  avatars.py               impor foto profil
  networks.py, tokens.py   jaringan & token
  httpclient.py, rpc.py    HTTP/JSON-RPC
  prices.py, portfolio.py  harga Binance, kurs, total aset & pengurutan
  formatting.py            USD, Rupiah, ETH, persen
  assets/                  logo ETH, font Poppins
  ui/                      tema, motif (decor.py), ikon, widget, halaman, dialog, jendela utama
tests/                     core, UI (offscreen), lapisan data (jaringan palsu), foto profil, motif latar
```

## Rencana

3. Manajemen token via contract address; daftar token mainnet yang diperluas
4. Kirim ETH/token (uji di Sepolia)
5. Swap lewat kontrak PancakeSwap
6. Packaging `.exe` dengan PyInstaller
