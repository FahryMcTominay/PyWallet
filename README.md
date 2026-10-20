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

## Fitur saat ini (v0.6.0)

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
| **Kirim** | ETH/koin native dan token ERC-20 (termasuk token kustom): pilih aset, alamat, jumlah (tombol Maks), kecepatan gas Lambat/Normal/Cepat, tinjau, master password, lalu pantau sampai masuk blok |
| Halaman login | Font Poppins (SIL OFL 1.1, lihat `pywallet/assets/fonts/OFL.txt`), latar bercahaya, logo |
| **Tema baru** | Palet abu-abu gelap, teal, biru-teal tua, dan abu pucat; motif kucing/pita/bintang gambar sendiri (bukan gambar karakter mana pun) |
| **Animasi geser** | Berpindah Wallet/Swap/Profil menggeser halaman (280 ms); klik beruntun tidak macet |
| **Hiasan latar** | Pita besar, sketsa kucing, dan bintang kecil beropacity rendah di latar; Telinga kucing kecil gaya coretan pensil hanya di tombol Kirim/Terima/Trade (dan ikon aplikasi). Bisa dimatikan dari Profil (pilihan diingat) |

Belum ada: Trade (menampilkan pesan "akan hadir"), riwayat transaksi, buku alamat, nama ENS, jaringan buatan sendiri.

### Tambah token lewat contract address

Tombol **＋ Token** di lobi: pilih jaringan (Ethereum/Base di mainnet, Sepolia di testnet), tempel contract address,
lalu **Periksa**. Nama, simbol, dan desimal dibaca langsung dari blockchain (`rpc.fetch_token_info`). Sebelum
menambahkan kamu wajib mencentang bahwa alamat sudah dicocokkan dengan sumber resmi; jika simbolnya sama dengan token
bawaan tetapi alamatnya beda, muncul peringatan token palsu. Token kustom tersimpan di database lokal (tabel
`custom_tokens`, skema v3), berlaku untuk semua wallet, bertanda "Kustom", dan tidak punya harga (agar token palsu
tidak bisa meminjam harga token asli).

Klik baris token mana pun untuk melihat **detail**: saldo, jaringan, **contract address** (salin / buka di explorer),
dan tombol hapus untuk token kustom. ETH dijelaskan sebagai koin native yang memang tidak punya contract address.

### Kirim aset

Tombol **Kirim** di lobi (butuh aset bersaldo di mode yang sedang aktif). Alurnya tiga layar dalam satu dialog:
**form** (aset, alamat tujuan, jumlah) -> **tinjau** (ringkasan lengkap, pilihan kecepatan, master password) ->
**status** (hash transaksi, lalu menunggu masuk blok). Rincian teknis ada di `pywallet/tx.py` dan `ui/send_dialog.py`.

Pengaman yang dipasang:
- Master password **selalu** diminta untuk menandatangani (`Vault.sign_transfer`); kunci hanya hidup sesaat di memori
  dan tidak pernah dikembalikan. Penandatanganan ditolak bila kunci tidak cocok dengan alamat wallet.
- Alamat tujuan divalidasi: 40 hex, checksum EIP-55 bila huruf campuran, alamat nol ditolak, tidak boleh sama dengan
  alamat sendiri, token tidak boleh dikirim ke kontrak token itu sendiri; peringatan bila tujuan adalah kontrak.
- Chain ID dari RPC dicocokkan dengan jaringan sebelum menyusun transaksi (RPC yang menjawab jaringan lain ditolak).
- Biaya gas dihitung dari jaringan (EIP-1559 bila tersedia, kalau tidak gasPrice lama). Tampil sebagai **batas atas**;
  biaya sebenarnya biasanya lebih kecil. "Maks" pada koin native mengurangi biaya gas lebih dulu.
- Estimasi biaya lebih tua dari 2 menit diperbarui dulu sebelum menandatangani (nonce dan biaya bisa berubah).
- Di mainnet muncul peringatan tambahan bahwa dana sungguhan tidak bisa ditarik kembali.

Uji dulu di **Testnet (Sepolia)** dengan ETH uji dari faucet. Saldo dimuat ulang otomatis setelah transaksi terkirim.

### Daftar token mainnet

Mainnet menampilkan 10 aset meskipun saldonya 0: ETH (Ethereum dan Base), USDT, USDC (Ethereum dan Base), DAI,
WBTC, LINK, UNI, CAKE. Urutan: aset bernilai terbesar di atas, lalu yang lebih kecil, dan saldo 0 menyusul
berurutan abjad. Daftarnya ada di `pywallet/tokens.py`. Saklar `EXTENDED_TOKEN_LIST` di `pywallet/config.py`
(False = hanya ETH). Alamat kontrak harus berformat checksum (diperiksa tes); verifikasi alamat ke sumber
resmi sebelum mengandalkannya untuk dana sungguhan.

### Tema & motif

Warna ada di `pywallet/ui/theme.py` (satu tempat), motif di `pywallet/ui/decor.py`. Semua motif digambar dengan
kode (QPainter), tanpa file gambar. Untuk menonaktifkannya secara bawaan, ubah `ENABLED` di `decor.py`.

## Dokumentasi

Pemula? Mulai dari **`docs/PANDUAN.md`**: peta kode, contoh alur lengkap (ganti foto profil), cara kerja saldo/harga,
dan penjelasan bagaimana Kirim/Swap nanti berinteraksi dengan blockchain.

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
  tx.py                    Kirim: validasi, gas, susun transaksi, kirim, receipt
  httpclient.py, rpc.py    HTTP/JSON-RPC
  prices.py, portfolio.py  harga Binance, kurs, total aset & pengurutan
  formatting.py            USD, Rupiah, ETH, persen
  assets/                  logo ETH, font Poppins
  ui/                      tema, motif (decor.py), ikon, widget, halaman, dialog, jendela utama
tests/                     core, UI (offscreen), lapisan data (jaringan palsu), foto profil, motif latar, Kirim
```

## Rencana

3. ~~Daftar token mainnet yang diperluas dan tambah token via contract address~~ (selesai)
4. ~~Kirim ETH/token (uji di Sepolia)~~ (selesai)
5. Swap lewat kontrak PancakeSwap
6. Packaging `.exe` dengan PyInstaller
