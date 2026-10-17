# PyWallet

Wallet crypto desktop (EVM) berbasis Python + PySide6. Non-custodial: kunci wallet dibuat dan disimpan
terenkripsi di komputermu sendiri. Saat ini berjalan di jaringan **Sepolia (testnet)**.

> **Status: tahap 1–2 (fondasi + CRUD wallet).** Saldo, harga, kirim, dan swap menyusul di tahap berikutnya.

## Menjalankan di Windows

1. Pasang Python 3.10+ dari python.org (centang *Add Python to PATH*).
2. Di folder proyek, buka Command Prompt / PowerShell:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Menjalankan tes:

```bat
python -m pytest -q
```

Data aplikasi tersimpan di `%APPDATA%\PyWallet\pywallet.db`.

## Fitur saat ini

| Fitur | Keterangan |
|---|---|
| Master password | Dibuat saat pertama kali membuka aplikasi |
| Jeda 5 menit | Jika aplikasi terakhir aktif < 5 menit lalu, lobi terbuka tanpa password |
| Buat wallet | Seed phrase 12 kata (BIP39), wajib verifikasi 3 kata sebelum disimpan |
| Impor wallet | Lewat seed phrase (12/24 kata) atau private key |
| Ganti nama | Dari tab Profil |
| Lihat seed phrase / private key | Dari tab Profil, wajib master password, tertutup otomatis 30 detik |
| Hapus wallet | Wajib centang backup, ketik nama wallet, dan master password |
| Terima | Alamat + QR code |
| Kunci aplikasi | Menghapus jeda 5 menit; pembukaan berikutnya wajib password |

Tombol **Kirim** dan **Trade** sudah ada di lobi, tetapi masih menampilkan pesan "akan hadir".

## Keamanan

- Seed phrase / private key dienkripsi dengan **AES-256-GCM**; kuncinya diturunkan dari master password
  memakai **scrypt** (N=2^15, r=8, p=1) dan **tidak pernah disimpan**.
- Ciphertext terikat ke alamat wallet-nya (AAD), sehingga tidak bisa ditukar antar-wallet.
- Dua tingkat akses: data publik (nama, alamat) tidak terenkripsi agar lobi bisa dibuka dalam jeda 5 menit.
  Membuat, mengimpor, melihat rahasia, dan menghapus wallet **selalu** meminta master password
  (ditegakkan di `vault.py`, bukan hanya di UI).
- Clipboard dibersihkan otomatis 30 detik setelah menyalin seed phrase / private key.
- Database memakai `secure_delete`, dan di Linux/macOS izin file diatur 0600.
- **Batasan:** kode ini belum diaudit. Pakai di testnet dulu. Python tidak bisa menghapus string rahasia dari
  memori secara andal.
- **Lupa master password** tidak bisa dipulihkan. Jalan keluarnya: hapus `pywallet.db`, lalu impor ulang
  wallet dengan seed phrase / private key.

## Struktur

```
main.py                  titik masuk
pywallet/
  config.py              konstanta & lokasi data
  crypto.py              scrypt + AES-GCM
  db.py                  SQLite (skema & migrasi)
  wallet_core.py         seed/private key -> akun EVM (eth-account)
  vault.py               logika inti: master password, CRUD wallet, jeda 5 menit
  ui/
    theme.py             palette & stylesheet
    icons.py, widgets.py komponen visual
    pages.py             setup, unlock, lobi, swap, profil
    dialogs.py           buat, impor, rename, hapus, lihat rahasia, terima
    main_window.py       alur aplikasi
tests/                   37 tes core + 10 tes UI
```

## Rencana tahap berikutnya

3. Saldo on-chain (RPC) dan harga dari API bursa; manajemen token via contract address
4. Kirim ETH/token (uji di Sepolia)
5. Swap lewat kontrak PancakeSwap
6. Packaging `.exe` dengan PyInstaller
