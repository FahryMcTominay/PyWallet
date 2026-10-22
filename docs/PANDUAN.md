# Panduan Membaca Kode PyWallet

Panduan ini ditulis untuk pemula. Tujuannya bukan menjelaskan semua baris, tetapi memberi **peta**: file mana
mengerjakan apa, dan bagaimana satu fitur berjalan dari klik tombol sampai data tersimpan. Setiap bagian bisa
dibaca terpisah.

Isi:
1. Peta besar aplikasi
2. Tiga konsep Qt yang dipakai di mana-mana
3. Contoh lengkap: bagaimana ganti foto profil bekerja
4. Alur lain: buat wallet, buka kunci, lihat seed, saldo & harga, terima
5. Kirim dan Swap: cara kerjanya dengan blockchain (**belum dibuat**, ini rencana)
6. Cara belajar dari kode ini + istilah penting

---

## 1. Peta besar aplikasi

Aplikasi dibagi tiga lapisan. Aturan emasnya: **lapisan atas boleh memanggil lapisan bawah, tidak sebaliknya.**

```
┌─────────────────────────────────────────────────────────────┐
│ LAPISAN TAMPILAN (pywallet/ui/)        apa yang dilihat user │
│   main_window.py  pages.py  dialogs.py  widgets.py           │
│   theme.py (warna)  decor.py (motif)  icons.py  fonts.py     │
├─────────────────────────────────────────────────────────────┤
│ LAPISAN LOGIKA (pywallet/)             aturan aplikasi       │
│   vault.py        CRUD wallet, master password, jeda 5 menit │
│   wallet_core.py  seed phrase / private key -> alamat        │
│   crypto.py       enkripsi (scrypt + AES-256-GCM)            │
│   avatars.py      olah gambar foto profil                    │
│   portfolio.py    gabung saldo + harga, urutkan, hitung total│
├─────────────────────────────────────────────────────────────┤
│ LAPISAN DATA & JARINGAN                                      │
│   db.py        SQLite di komputer (file pywallet.db)         │
│   rpc.py       bicara dengan node blockchain (JSON-RPC)      │
│   prices.py    harga dari Binance                            │
│   httpclient.py  pengirim permintaan HTTP                    │
└─────────────────────────────────────────────────────────────┘
```

Contoh manfaatnya: `vault.py` sama sekali tidak tahu ada jendela, tombol, atau warna. Karena itu logikanya bisa
dites tanpa layar (`tests/test_vault.py`), dan kamu bisa mengubah tampilan tanpa merusak keamanan.

### Daftar file

| File | Tugasnya dalam satu kalimat |
|---|---|
| `main.py` | Titik masuk: membuat aplikasi Qt, memuat tema, membuka jendela utama |
| `config.py` | Konstanta (jeda 5 menit, lokasi folder data, versi) |
| `db.py` | Membuka SQLite dan membuat tabel `wallets` dan `settings` |
| `crypto.py` | Mengunci dan membuka rahasia wallet dengan password |
| `wallet_core.py` | Membuat/memulihkan akun EVM dari 12 kata atau private key |
| `vault.py` | "Brankas": semua operasi wallet (buat, impor, ganti nama, hapus, lihat seed, foto) |
| `avatars.py` | Menerima gambar dari komputer, memotong persegi, menyimpan salinan kecil |
| `networks.py`, `tokens.py` | Daftar jaringan (Ethereum, Base, Sepolia) dan token |
| `rpc.py` | Tanya saldo ke node blockchain |
| `history.py` | Riwayat transaksi: ambil dari explorer, gabung dengan catatan lokal, tandai yang mencurigakan |
| `tx.py` | Kirim aset: validasi alamat/jumlah, hitung gas, susun & kirim transaksi, cek receipt |
| `prices.py` | Tanya harga ke Binance dan kurs USD→IDR |
| `portfolio.py` | Menggabungkan saldo + harga menjadi satu "potret" (Snapshot) |
| `formatting.py` | Format angka: `$6,000.00`, `Rp96.000.000`, `0,05 ETH` |
| `ui/main_window.py` | Jendela utama; **menghubungkan klik tombol ke aksi** |
| `ui/pages.py` | Halaman-halaman (login, lobi, swap, profil, navigasi bawah) |
| `ui/history_dialog.py` | Dialog Riwayat: daftar transaksi, status, klik untuk buka explorer |
| `ui/send_dialog.py` | Dialog Kirim: form -> tinjau + password -> status transaksi |
| `ui/dialogs.py` | Kotak dialog kecil (password, buat wallet, impor, ganti nama, hapus) + `ScreenBase`, kerangka layar penuh dengan tombol ← |
| `ui/widgets.py` | Komponen kecil yang dipakai ulang (avatar, kartu, tombol bulat, QR, animasi geser) |
| `ui/theme.py` | Semua warna dan gaya (QSS, mirip CSS) |
| `ui/decor.py` | Motif latar (pita, kucing, bintang) yang digambar lewat kode |

---

## 2. Tiga konsep Qt yang dipakai di mana-mana

### a. Widget = kotak di layar
Hampir semua yang terlihat adalah *widget*: tombol (`QPushButton`), teks (`QLabel`), halaman (`QWidget`).
Widget bisa ditaruh di dalam widget lain. Penataan posisinya memakai *layout* (`QVBoxLayout` = tersusun ke
bawah, `QHBoxLayout` = tersusun ke samping).

### b. Signal dan slot = "kalau X terjadi, panggil Y"
Ini konsep terpenting untuk membaca kode UI. Widget tidak memanggil logika langsung. Ia **memancarkan sinyal**
("aku diklik"), dan pihak lain **menyambungkan** sinyal itu ke fungsi:

```python
self.photo_btn.clicked.connect(self.avatarRequested)   # klik tombol -> pancarkan sinyal avatarRequested
pt.avatarRequested.connect(self.change_avatar)         # sinyal itu -> jalankan change_avatar
```

Halaman (`pages.py`) hanya bilang "user minta ganti foto". Jendela utama (`main_window.py`) yang memutuskan
apa yang dilakukan. Jadi `pages.py` tampilan saja; `main_window.py` otaknya.

### c. QPainter = menggambar dengan kode
Latar bergambar (pita, kucing), ikon, grafik harga, dan QR code **tidak berasal dari file gambar**. Semuanya
digambar di fungsi `paintEvent` memakai `QPainter` (`drawPath`, `drawEllipse`, dst). Qt memanggil `paintEvent`
setiap kali widget perlu digambar ulang; `self.update()` meminta gambar ulang.

---

## 3. Contoh lengkap: bagaimana ganti foto profil bekerja

Ini contoh yang paling mewakili pola seluruh aplikasi: **UI → logika → penyimpanan → UI diperbarui**.

### Gambaran satu kalimat
User memilih gambar → gambar dipotong persegi dan diperkecil menjadi `wallet_<id>_<acak>.png` di folder
`avatars` → **nama file** itu dicatat di database pada baris wallet → tampilan digambar ulang membaca file tersebut.

### Alur langkah demi langkah

```
[Profil] klik avatar kecil / tombol "Pilih foto profil"
        │  pages.py: ProfileTab memancarkan sinyal avatarRequested
        ▼
main_window.py: MainWindow.change_avatar()
  1. wallet = vault.get_active_wallet()          -> wallet mana yang sedang aktif?
  2. QFileDialog.getOpenFileName(...)            -> jendela "pilih file" Windows
  3. store.import_image(wallet.id, path)         -> avatars.py (lihat di bawah)
  4. vault.set_avatar(wallet.id, filename)       -> vault.py -> UPDATE di SQLite
  5. store.remove(wallet.avatar)                 -> hapus foto LAMA agar folder tidak menumpuk
  6. home.refresh()                              -> semua halaman memuat ulang data wallet
        ▼
widgets.py: Avatar.set_wallet() membaca file foto, lalu paintEvent menggambarnya berbentuk lingkaran
```

### Langkah 3 lebih dekat: `AvatarStore.import_image` (file `avatars.py`)

1. **Cek ukuran file** (maks 20 MB) dan resolusi (maks 60 juta piksel) supaya aplikasi tidak macet.
2. **Baca gambar** dengan `QImageReader` (`setAutoTransform(True)` membuat foto dari ponsel tidak miring).
   Kalau bukan gambar, muncul pesan "File ini bukan gambar yang didukung".
3. **Potong persegi dari tengah**: `side = min(lebar, tinggi)`, lalu `image.copy(...)` dari titik tengah.
4. **Perkecil ke 256×256** dan simpan sebagai PNG.
5. **Nama file acak**: `wallet_{id}_{secrets.token_hex(4)}.png`, misalnya `wallet_1_a3f09c12.png`.

Kenapa dibuat begini?

| Keputusan | Alasannya |
|---|---|
| Menyimpan **salinan**, bukan alamat file asli | Kalau gambar asli dipindah/dihapus, foto di aplikasi tetap ada |
| Di database hanya **nama file**, bukan gambarnya | Database tetap kecil dan cepat; gambar ada di folder terpisah |
| Nama file ada bagian acak | Foto baru tidak tertukar dengan foto lama yang masih tampil/ter-cache |
| `_NAME_RE` (pola nama file) divalidasi di `AvatarStore.path` | Kalau database diutak-atik dan berisi `../../sesuatu`, aplikasi menolaknya, jadi tidak bisa membaca file di luar folder `avatars` |
| Foto lama dihapus setelah foto baru berhasil tersimpan | Kalau penyimpanan gagal, foto lama tidak hilang |

### Di mana datanya?
- Folder foto: `%APPDATA%\PyWallet\avatars\`
- Database: `%APPDATA%\PyWallet\pywallet.db`, tabel `wallets`, kolom `avatar` berisi nama file atau kosong
  (`NULL` = pakai avatar bawaan: huruf pertama nama + warna gradasi dari alamat wallet).

### Bagian tampilan: `Avatar` (file `ui/widgets.py`)
- `set_wallet(wallet, store)` mencari file foto lewat `store.path(wallet.avatar)`. Kalau ada, dimuat sebagai
  `QPixmap`; kalau tidak, dipakai gradasi + huruf.
- `paintEvent` memotong area gambar berbentuk lingkaran (`setClipPath`) lalu menggambar foto atau gradasi.
- `badge=True` menambahkan ikon kamera kecil dan membuat avatar bisa diklik (sinyal `clicked`).

> **Pola yang sama dipakai untuk fitur lain.** Coba cari "ganti nama wallet": tombol di `pages.py` →
> sinyal `renameRequested` → `MainWindow.rename_wallet` → dialog `RenameDialog` → `vault.rename_wallet` → `UPDATE`.

---

## 4. Alur lain

### 4.1 Buat wallet baru
1. `CreateWalletDialog` (dialog.py) memanggil `wallet_core.generate_mnemonic()` → **12 kata acak** (standar BIP39).
2. User menyalin kata, lalu diminta mengisi 3 kata sebagai bukti sudah mencatat.
3. User memasukkan master password; dialog memanggil `vault.create_wallet(nama, mnemonic, password)`.
4. Di `vault._add_wallet`:
   - `wallet_core.account_from_mnemonic` menurunkan **kunci pribadi dan alamat** dari 12 kata memakai jalur
     `m/44'/60'/0'/0/0` (standar yang sama dengan MetaMask).
   - `_key_for(password)` membuat kunci enkripsi dari password dan sekaligus memastikan password benar.
   - `crypto.encrypt(...)` mengunci 12 kata → data acak (`secret_enc`).
   - `INSERT INTO wallets` menyimpan nama, alamat, dan data terenkripsi.

**Yang tersimpan di komputer:** nama, alamat (publik), dan rahasia **terenkripsi**.
**Yang tidak pernah tersimpan:** password dan kunci enkripsinya (diturunkan ulang setiap kali dibutuhkan, lalu dibuang).

### 4.2 Enkripsi, lebih dekat (`crypto.py`)
```
password ──scrypt(+salt)──▶ kunci 32 byte ──AES-256-GCM──▶ rahasia terenkripsi
```
- **scrypt** sengaja *lambat dan memakan memori*, jadi menebak password jutaan kali menjadi mahal.
- **AES-GCM** mengenkripsi sekaligus memberi "segel": kalau data diubah satu bit pun atau password salah,
  proses membuka gagal (`DecryptionError`) alih-alih memberi hasil acak.
- **AAD** (`_aad(address)`): data dikunci ke alamat wallet-nya, jadi isi satu baris tidak bisa ditempel ke baris lain.

Kamu bisa mencobanya langsung di terminal (tanpa membuka aplikasi):
```python
from pywallet import wallet_core, crypto
acc = wallet_core.account_from_mnemonic("test test test test test test test test test test test junk")
print(acc.address)        # 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266  (wallet uji publik, jangan dipakai uang asli!)
salt = crypto.new_salt()
key = crypto.derive_key("passwordku123", salt)
blob = crypto.encrypt(key, b"rahasia", b"label")
print(crypto.decrypt(key, blob, b"label"))   # b'rahasia'
```

### 4.3 Buka aplikasi dan jeda 5 menit (`vault.py`, `main_window.py`)
- Aplikasi mencatat `last_active` (waktu terakhir aktif) tiap 30 detik (`_beat`) dan saat ditutup.
- `MainWindow.start()` bertanya `vault.within_grace()`: *apakah selisih waktu sekarang dan `last_active` < 300 detik?*
  Ya → langsung ke lobi. Tidak → layar password.
- Jeda ini hanya membuka **lobi**. Lihat seed, hapus wallet, dan (nanti) kirim/swap tetap selalu minta password,
  karena ditegakkan di dalam `vault.py` (bukan hanya di tombol), jadi tidak bisa dilewati dari UI.

### 4.4 Saldo dan harga (lobi)
Alurnya: `WalletTab.refresh_data()` → thread terpisah → `PortfolioService.load()` → hasil dikirim balik lewat sinyal.

```
PortfolioService.load(alamat, mode)
   ├─ rpc.fetch_balances      -> tanya saldo ke node blockchain  (rpc.py)
   ├─ prices.quotes           -> harga ETH, perubahan 24 jam     (prices.py -> Binance)
   ├─ prices.usd_idr          -> kurs rupiah
   └─ prices.sparkline        -> data grafik mini
        ▼  digabung menjadi Snapshot, diurutkan (aset terbesar di atas)
WalletTab._on_loaded(snapshot) -> _render() menggambar angka dan daftar token
```

**Kenapa memakai thread?** Permintaan internet bisa makan beberapa detik. Kalau dijalankan di thread utama,
jendela akan *membeku*. Maka pekerjaan lambat dijalankan di thread lain dan hasilnya dikirim kembali lewat
sinyal (`self._loaded.emit(...)`). `_request_id` mencegah hasil lama menimpa hasil baru (misalnya user keburu
ganti wallet atau mode).

**Bagaimana "saldo" didapat?** Aplikasi mengirim JSON seperti ini ke node publik (`rpc.py`):
```json
{"jsonrpc":"2.0","id":0,"method":"eth_getBalance","params":["0xf39F…2266","latest"]}
```
Node menjawab angka heksadesimal dalam satuan **wei** (1 ETH = 10¹⁸ wei). `portfolio.py` membaginya dengan
10^desimal untuk jadi ETH. Untuk token ERC-20 (USDT, USDC), dipakai `eth_call` ke kontrak token dengan fungsi
`balanceOf(alamat)` (lihat `encode_balance_of`). Jika satu node mati, `rpc.py` mencoba node cadangan (*failover*).

### 4.5 Terima
Paling sederhana: **tidak ada komunikasi jaringan sama sekali**. Dialog hanya menampilkan alamat wallet dan QR
code-nya. Siapa pun boleh tahu alamat; ia hanya bisa mengirim ke situ, tidak bisa mengambil dari situ. Dana
yang masuk langsung terlihat di blockchain, lalu muncul di aplikasi saat saldo dimuat ulang.

### 4.6 Kirim (`tx.py`, `ui/send_dialog.py`, `vault.py`)
Dialog Kirim punya tiga halaman. Berikut urutan panggilan kodenya:

```
Tombol Kirim (pages.py)  --sendRequested-->  MainWindow.send()            membuka SendDialog
  SendDialog "Lanjut"  -> tx.normalize_recipient / tx.parse_amount        periksa input (tanpa jaringan)
                       -> tx.prepare_transfer  (thread terpisah)          1 batch RPC: chain ID, nonce, base fee,
                                                                          priority fee, gasPrice, kode tujuan,
                                                                          saldo native, estimateGas
                       -> TransferPlan                                    "paket" berisi semua angka di atas
  Halaman Tinjau       -> plan.tx_fields(kecepatan)                       bidang transaksi sesuai pilihan Lambat/Normal/Cepat
  "Kirim sekarang"     -> Vault.sign_transfer(id, password, fields)       buka kunci, tanda tangan, buang kunci
                       -> tx.broadcast (thread)                           eth_sendRawTransaction -> hash
                       -> tx.fetch_receipt (diulang tiap 4 detik)         sukses / gagal / belum masuk blok
```
Tiga hal yang perlu diperhatikan:
- **Nonce** = nomor urut transaksi akunmu. Dua transaksi tidak boleh memakai nonce yang sama; node menolak yang lama.
- **Gas** = ongkos komputasi. `gas_limit` (batas jumlah pekerjaan) dikali harga per gas = biaya. Tampilan "maks"
  adalah batas atas; yang dibayar biasanya lebih kecil.
- Untuk **token**, transaksi ditujukan ke alamat kontrak token dengan `value = 0` dan data `transfer(tujuan, jumlah)`
  (`tx.encode_transfer`); biaya gasnya tetap dibayar dengan koin native (mis. ETH), jadi token saja tidak cukup.

### 4.7 Riwayat (`history.py`, `ui/history_dialog.py`)
Blockchain tidak bisa ditanya "tunjukkan semua transaksi alamat ini" lewat RPC biasa; node hanya menjawab
pertanyaan per blok atau per transaksi. Karena itu riwayat diambil dari **explorer** yang sudah mengindeks semuanya.

```
Tombol Riwayat -> MainWindow.show_history -> HistoryDialog.reload
   (thread)    -> HistoryService.load(alamat, mode, catatan_lokal, token_dikenal)
                    per jaringan: txlist  (koin native + panggilan kontrak)
                                  tokentx (transfer token ERC-20)
                    parse_txlist / parse_tokentx    validasi tiap bidang (data luar = tidak tepercaya)
                    merge                            buang "panggilan kontrak" yang sebenarnya transfer token
                    gabung catatan lokal tx_log      transaksi baru kirim muncul walau belum terindeks
                    cek receipt untuk yang "menunggu" -> status diperbarui ke database
   (utama)     -> _render: satu HistoryRow per transaksi
```
Perhatikan juga pemisahan tugasnya: SQLite hanya dibaca di thread utama (`list_sent_txs`), lalu datanya dibawa ke
thread kerja; hasil pembaruan status dikembalikan lewat signal dan ditulis lagi di thread utama.

---

## 5. Kirim dan Swap: cara kerjanya dengan blockchain

> **Status:** Kirim (5.2 dan 5.3) **sudah dibuat** di tahap 4: lihat `tx.py` dan `ui/send_dialog.py`, dan alur
> kodenya di bagian 4.6. Tombol Trade masih menampilkan pesan "akan hadir"; 5.4 menjelaskan rencananya (tahap 5).

### 5.1 Pertama: apa itu "server desentralisasi"?
Blockchain Ethereum dijalankan oleh ribuan komputer (*node*) di seluruh dunia yang menyimpan **buku besar yang
sama**. Tidak ada satu perusahaan pemiliknya. Pada buku besar itu tertulis angka seperti "alamat 0xf39F… punya
2 ETH". **Koin tidak tersimpan di wallet**; wallet hanya menyimpan *kunci* yang membuktikan kamu berhak
memindahkan angka di buku besar itu.

Wallet berbicara dengan blockchain lewat **node RPC**, yaitu pintu masuk berupa alamat web. Contohnya
`https://ethereum-sepolia-rpc.publicnode.com` (lihat `networks.py`). Itulah satu-satunya "server" yang diajak
bicara, dan sifatnya hanya perantara. Ia tidak memegang kuncimu.

### 5.2 Kirim ETH
```
1. User isi alamat tujuan + jumlah
2. Aplikasi tanya ke node (RPC):
     eth_getTransactionCount  -> nonce (nomor urut transaksi akunmu)
     eth_gasPrice / eth_feeHistory, eth_estimateGas -> biaya (gas)
3. Susun transaksi: {to, value, nonce, gas, chainId, ...}
4. TANDA TANGAN di komputer sendiri memakai private key
     (kunci dibuka dengan master password sesaat, dipakai, lalu dibuang)
5. Kirim transaksi yang sudah bertanda tangan:  eth_sendRawTransaction  -> dapat "hash transaksi"
6. Tanya berkala eth_getTransactionReceipt sampai transaksi masuk blok (sukses/gagal)
```
Poin terpenting: **private key tidak pernah meninggalkan komputer.** Yang dikirim ke node hanya transaksi yang
sudah ditandatangani. Node bisa memeriksa tanda tangan itu sah, tetapi tidak bisa menirunya. `chainId` ikut
ditandatangani supaya transaksi Sepolia tidak bisa "diputar ulang" di mainnet. Karena itu pengiriman
wajib master password.

Pustaka `eth-account` (sudah dipakai di `wallet_core.py`) menyediakan penandatanganan ini.

### 5.3 Kirim token (USDT/USDC dst.)
Token ERC-20 bukan "uang di wallet", melainkan **catatan saldo di dalam sebuah kontrak pintar**. Mengirim token
berarti memanggil fungsi `transfer(tujuan, jumlah)` milik kontrak token itu. Transaksinya ditujukan ke alamat
**kontrak**, dengan `value = 0` dan data berisi pemanggilan fungsi. Prinsipnya sama dengan `encode_balance_of`
di `rpc.py`, hanya saja memakai pemilih fungsi `transfer`.

### 5.4 Swap lewat PancakeSwap (rencana tahap 5)
Swap = menukar token A dengan token B lewat **kontrak router** DEX. Tidak ada pihak yang mencocokkan pembeli
dan penjual; kontrak memakai *kolam likuiditas* (pool) dan rumus harga.
```
1. Perkiraan hasil:     router.getAmountsOut(jumlahA, [A, B])      (hanya membaca, gratis)
2. Izin (approve):      tokenA.approve(router, jumlahA)            (transaksi 1, jika A bukan ETH)
3. Tukar:               router.swapExactTokensForTokens(jumlahA, minimumB, jalur, penerima, batasWaktu)
                                                                    (transaksi 2)
```
- **Slippage**: harga bisa bergeser antara saat melihat dan saat transaksi masuk blok. `minimumB` adalah batas
  terendah yang kamu terima; jika hasil lebih kecil, transaksi dibatalkan otomatis.
- **Batas waktu**: transaksi yang tertunda terlalu lama gugur sendiri.
- **Approve**: kontrak token harus diizinkan dulu memindahkan token milikmu. Ini juga alasan mengapa swap
  ke kontrak asing yang tidak dikenal berbahaya.

### 5.5 Risiko yang dijaga
Transaksi blockchain **tidak bisa dibatalkan**. Karena itu ada: layar konfirmasi yang menampilkan
alamat tujuan lengkap, jaringan, dan biaya; peringatan jika alamat salah format; dan **uji dulu di Sepolia**
dengan ETH uji gratis (faucet) sebelum menyentuh mainnet.

---

## 6. Cara belajar dari kode ini

### Urutan membaca yang disarankan
1. `config.py` dan `db.py`: pendek, tidak ada Qt.
2. `wallet_core.py` dan `crypto.py`: inti kripto (tiap fungsi kecil).
3. `vault.py`: baca `_add_wallet`, `reveal_secret`, `set_avatar`, `within_grace`.
4. `avatars.py`: contoh logika yang menyentuh file.
5. `main_window.py`: lihat bagaimana sinyal disambungkan (`__init__`) lalu tiap aksi.
6. `ui/pages.py` dan `ui/dialogs.py`: tampilan. Lewati `paintEvent` di awal; itu urusan menggambar.
7. Terakhir: `rpc.py`, `prices.py`, `portfolio.py`.
Abaikan `decor.py` dan `icons.py` sampai kamu butuh; isinya koordinat gambar.

### Tips praktis
- **Telusuri dari tombol.** Cari teks tombol di `pages.py` (misal `"Ganti nama wallet"`), lihat sinyal yang
  dipancarkan, cari sambungannya di `main_window.py`, lalu ikuti fungsinya sampai `vault.py`.
- **Jalankan tes** (`python -m pytest -q`). Tes di `tests/` adalah contoh pemakaian setiap fungsi; baca
  `test_vault.py` sebagai "dokumentasi yang hidup".
- **Eksperimen dengan folder data terpisah** supaya wallet asli tidak tersentuh. Di PowerShell:
  `$env:PYWALLET_HOME="C:\\temp\\pywallet-coba"; python main.py`
- **Pakai `print()`** atau `breakpoint()` di fungsi yang ingin dipahami, lalu klik tombolnya.
- **Ubah satu hal kecil** (mis. teks tombol atau warna di `theme.py`), jalankan, lihat efeknya.

### Istilah penting
| Istilah | Arti singkat |
|---|---|
| Seed phrase / mnemonic | 12 kata yang menjadi "kunci induk"; dari sini semua kunci dan alamat diturunkan |
| Private key | Angka rahasia yang menandatangani transaksi; siapa pegang, dia pegang dana |
| Alamat | Turunan publik dari private key (`0x…`); aman dibagikan |
| Derivation path | "Rute" menurunkan akun dari seed (`m/44'/60'/0'/0/0`); path sama = alamat sama di semua wallet standar |
| EVM | Mesin virtual Ethereum; Ethereum, Base, BNB Chain, dll. memakainya sehingga satu alamat berlaku di semuanya |
| RPC / node | Pintu masuk untuk membaca atau mengirim ke blockchain |
| Wei | Satuan terkecil ETH (1 ETH = 10¹⁸ wei) |
| Gas | Biaya transaksi, dibayar dengan ETH |
| Nonce | Nomor urut transaksi dari satu alamat |
| ERC-20 | Standar token (USDT, USDC); saldo dicatat di kontrak token |
| Testnet (Sepolia) | Blockchain percobaan; koinnya gratis dan tidak bernilai uang |
| Signal / slot | Mekanisme Qt: satu bagian memancarkan peristiwa, bagian lain bereaksi |
| QSS | Gaya tampilan Qt, mirip CSS (lihat `theme.py`) |

Kalau ada bagian yang masih membingungkan, sebutkan nama file atau fungsinya; kita bisa bahas baris demi baris.
