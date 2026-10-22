"""Dialog CRUD wallet: buat, impor, ganti nama, lihat rahasia, hapus, terima."""
from __future__ import annotations

import random
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import wallet_core
from ..config import SECRET_VIEW_TIMEOUT
from ..vault import (
    SECRET_MNEMONIC,
    InvalidPassword,
    RevealedSecret,
    Vault,
    VaultError,
    WalletRecord,
    validate_name,
)
from ..wallet_core import InvalidSecret
from . import theme
from .widgets import PasswordField, QRWidget, copy_to_clipboard, label

USER_ERRORS = (VaultError, InvalidSecret)


def button(text: str, name: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class _Helpers:
    """Pembantu kecil yang dipakai bersama oleh dialog (BaseDialog) dan layar penuh (ScreenBase)."""

    @staticmethod
    def error_label() -> QWidget:
        lb = label("", "error", wrap=True)
        lb.hide()
        return lb

    @staticmethod
    def show_error(lb, text: str) -> None:
        lb.setText(text)
        lb.setVisible(bool(text))

    @staticmethod
    def button_row(*buttons: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        return row


class BaseDialog(_Helpers, QDialog):
    """Jendela dialog kecil (modal). Dipakai untuk kotak singkat: password, ganti nama, konfirmasi."""

    def __init__(self, title: str, parent: QWidget | None = None, width: int = 440):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(26, 24, 26, 22)
        self.root.setSpacing(14)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Pastikan tinggi cukup untuk teks yang membungkus baris (hindari teks terpotong).
        needed = self.layout().totalHeightForWidth(self.width())
        if needed > self.height():
            self.resize(self.width(), needed)

    def fit_to_content(self) -> None:
        """Sesuaikan tinggi dengan isi (dipanggil saat isi berubah, mis. pindah halaman)."""
        if self.isVisible():
            self.resize(self.width(), 1)
            self.adjustSize()


class ScreenBase(_Helpers, QWidget):
    """Layar penuh di dalam jendela utama (bukan jendela baru): bilah atas dengan tombol ← lalu isi yang bisa digulir.

    API-nya sengaja mirip dialog (`root`, `accept`, `reject`, `done`) supaya isi layar tidak perlu ditulis ulang.
    Bedanya tidak ada `exec()`: layar dibuka lewat `MainWindow.open_screen`, dan sinyal `finished(kode)` dipancarkan
    saat layar selesai (kode 1 = diterima, 0 = dibatalkan).
    """

    finished = Signal(int)

    def __init__(self, title: str, parent: QWidget | None = None, width: int = 0, scroll: bool = True):
        super().__init__(parent)
        self.setObjectName("screen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#screen {{ background: {theme.BG}; }}")
        self.screen_title = title
        self._finished = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("screenHeader")
        header.setStyleSheet(
            f"QWidget#screenHeader {{ background: {theme.SURFACE}; border-bottom: 1px solid {theme.LINE}; }}"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 18, 8)
        hl.setSpacing(6)
        self.back_btn = QToolButton()
        self.back_btn.setText("←")
        self.back_btn.setToolTip("Kembali")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setFixedSize(40, 40)
        self.back_btn.setStyleSheet(
            f"QToolButton {{ color: {theme.TEXT_STRONG}; font-size: 22px; background: transparent; border-radius: 20px; }}"
            f"QToolButton:hover {{ background: {theme.SURFACE_HI}; }}"
        )
        self.back_btn.clicked.connect(self.go_back)
        hl.addWidget(self.back_btn)
        self.title_lbl = label(title)
        self.title_lbl.setStyleSheet(
            f"color: {theme.TEXT_STRONG}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        hl.addWidget(self.title_lbl, 1)
        outer.addWidget(header)

        content = QWidget()
        inner = QWidget()
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(22, 18, 22, 22)
        self.root.setSpacing(14)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(inner, 0 if scroll else 1)      # layar yang bisa digulir: isi setinggi kebutuhannya, sisa kosong di bawah
        if scroll:
            cl.addStretch(1)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            area.setWidget(content)
            outer.addWidget(area, 1)
        else:
            outer.addWidget(content, 1)

    # --- siklus hidup -------------------------------------------------------------------------
    def go_back(self) -> None:
        """Tombol ← / tombol Esc. Layar bertahap bisa menggantinya (mis. Kirim kembali ke form dulu)."""
        self.reject()

    def done(self, result: int) -> None:
        if self._finished:
            return
        self._finished = True
        self.finished.emit(result)

    def accept(self) -> None:
        self.done(1)

    def reject(self) -> None:
        self.done(0)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.go_back()
            return
        super().keyPressEvent(event)

    # Tinggi layar ditentukan oleh jendela utama, bukan isinya; pemanggilan lama (dari versi dialog) diabaikan.
    def adjustSize(self) -> None:
        self.updateGeometry()

    def fit_to_content(self) -> None:
        self.updateGeometry()


def word_grid(words: list[str], columns: int = 3) -> QWidget:
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(8)
    for i, w in enumerate(words):
        chip = label(f"{i + 1}.  {w}", "word")
        chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(chip, i // columns, i % columns)
    return host


# ==========================================================================
# Konfirmasi password untuk aksi sensitif
# ==========================================================================
class PasswordDialog(BaseDialog):
    """Meminta master password lalu menjalankan `action(password)`.

    Jika password salah, dialog tetap terbuka dan menampilkan galat.
    Hasil `action` tersedia di `.result_value` setelah dialog diterima.
    """

    def __init__(
        self,
        title: str,
        message: str,
        action: Callable[[str], object],
        ok_text: str = "Konfirmasi",
        parent: QWidget | None = None,
    ):
        super().__init__(title, parent, 420)
        self._action = action
        self.result_value = None
        self.root.addWidget(label(title, "heading"))
        self.root.addWidget(label(message, "muted", wrap=True))
        self.field = PasswordField("Master password")
        self.field.returnPressed.connect(self._submit)
        self.root.addWidget(self.field)
        self.err = self.error_label()
        self.root.addWidget(self.err)
        cancel = button("Batal")
        cancel.clicked.connect(self.reject)
        self.ok = button(ok_text, "primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._submit)
        self.root.addLayout(self.button_row(cancel, self.ok))
        self.field.setFocus()

    def _submit(self) -> None:
        pw = self.field.text()
        if not pw:
            self.show_error(self.err, "Masukkan master password.")
            return
        try:
            self.result_value = self._action(pw)
        except InvalidPassword:
            self.field.clear()
            self.show_error(self.err, "Password salah.")
            self.field.setFocus()
            return
        except USER_ERRORS as exc:
            self.show_error(self.err, str(exc))
            return
        self.accept()


# ==========================================================================
# Tampilkan seed phrase / private key
# ==========================================================================
class SecretDialog(BaseDialog):
    def __init__(self, wallet: WalletRecord, secret: RevealedSecret, parent: QWidget | None = None):
        is_seed = secret.kind == SECRET_MNEMONIC
        kind_name = "Seed Phrase" if is_seed else "Private Key"
        super().__init__(f"{kind_name} — {wallet.name}", parent, 480)
        self._secret = secret.value
        self._remaining = SECRET_VIEW_TIMEOUT

        self.root.addWidget(label(f"{kind_name} “{wallet.name}”", "heading"))
        self.root.addWidget(
            label(
                "Jangan bagikan ke siapa pun. Siapa pun yang memegang ini bisa mengambil seluruh dana "
                "di wallet. Pastikan tidak ada orang atau kamera yang melihat layarmu.",
                "warnbox",
                wrap=True,
            )
        )
        if is_seed:
            self.root.addWidget(word_grid(secret.value.split()))
        else:
            # Dipecah per 32 karakter agar seluruh private key terlihat tanpa terpotong.
            body = secret.value[2:] if secret.value.startswith("0x") else secret.value
            lines = ["0x" + body[:32]] + [body[i : i + 32] for i in range(32, len(body), 32)]
            self.root.addWidget(label("\n".join(lines), "secret", selectable=True))
            self.root.addWidget(
                label(
                    "Wallet ini diimpor lewat private key, jadi tidak memiliki seed phrase.",
                    "small",
                    wrap=True,
                )
            )

        self.countdown = label("", "small")
        self.root.addWidget(self.countdown)
        copy_btn = button("Salin")
        copy_btn.clicked.connect(lambda: copy_to_clipboard(self._secret, sensitive=True, anchor=copy_btn))
        close_btn = button("Tutup", "primary")
        close_btn.clicked.connect(self.accept)
        self.root.addLayout(self.button_row(copy_btn, close_btn))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._update_countdown()

    def _update_countdown(self) -> None:
        self.countdown.setText(f"Layar ini tertutup otomatis dalam {self._remaining} detik.")

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self.accept()
            return
        self._update_countdown()

    def done(self, result: int) -> None:
        self._timer.stop()
        self._secret = ""
        super().done(result)


# ==========================================================================
# Buat wallet baru
# ==========================================================================
class CreateWalletDialog(BaseDialog):
    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__("Buat Wallet Baru", parent, 500)
        self.vault = vault
        self.created: WalletRecord | None = None
        self._mnemonic = wallet_core.generate_mnemonic()
        self._words = self._mnemonic.split()
        self._check_idx = sorted(random.SystemRandom().sample(range(len(self._words)), 3))

        self.stack = QStackedWidget()
        self.root.addWidget(self.stack)
        self.stack.addWidget(self._page_name())
        self.stack.addWidget(self._page_seed())
        self.stack.addWidget(self._page_verify())

    # --- langkah 1: nama --------------------------------------------------
    def _page_name(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Beri nama wallet", "heading"))
        lay.addWidget(
            label("Nama hanya tampil di aplikasi ini dan bisa diubah kapan saja.", "muted", wrap=True)
        )
        self.name_edit = QLineEdit(self.vault.suggest_name())
        self.name_edit.setMaxLength(64)
        self.name_edit.returnPressed.connect(self._to_seed)
        lay.addWidget(self.name_edit)
        self.name_err = self.error_label()
        lay.addWidget(self.name_err)
        cancel = button("Batal")
        cancel.clicked.connect(self.reject)
        nxt = button("Lanjut", "primary")
        nxt.clicked.connect(self._to_seed)
        lay.addLayout(self.button_row(cancel, nxt))
        return page

    def _to_seed(self) -> None:
        try:
            name = validate_name(self.name_edit.text())
        except VaultError as exc:
            self.show_error(self.name_err, str(exc))
            return
        if any(w.name.lower() == name.lower() for w in self.vault.list_wallets()):
            self.show_error(self.name_err, f"Nama “{name}” sudah dipakai wallet lain.")
            return
        self.show_error(self.name_err, "")
        self.stack.setCurrentIndex(1)

    # --- langkah 2: catat seed ----------------------------------------------
    def _page_seed(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Catat seed phrase-mu", "heading"))
        lay.addWidget(
            label(
                "Tulis 12 kata ini berurutan di kertas dan simpan di tempat aman. Ini satu-satunya cara "
                "memulihkan wallet jika aplikasi dihapus atau komputer rusak. Jangan difoto atau dikirim "
                "lewat chat.",
                "warnbox",
                wrap=True,
            )
        )
        lay.addWidget(word_grid(self._words))
        copy_btn = button("Salin", "flat")
        copy_btn.clicked.connect(lambda: copy_to_clipboard(self._mnemonic, sensitive=True, anchor=copy_btn))
        back = button("Kembali")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        nxt = button("Saya sudah mencatat", "primary")
        nxt.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addStretch(1)
        row.addWidget(back)
        row.addWidget(nxt)
        lay.addLayout(row)
        return page

    # --- langkah 3: verifikasi + password ---------------------------------------
    def _page_verify(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Verifikasi catatanmu", "heading"))
        nums = ", ".join(f"#{i + 1}" for i in self._check_idx)
        lay.addWidget(
            label(f"Masukkan kata bernomor {nums} dari seed phrase-mu untuk memastikan catatannya benar.",
                  "muted", wrap=True)
        )
        self._check_edits: list[QLineEdit] = []
        for i in self._check_idx:
            row = QHBoxLayout()
            tag = label(f"Kata #{i + 1}")
            tag.setMinimumWidth(70)
            edit = QLineEdit()
            edit.setPlaceholderText("…")
            edit.setAutoFillBackground(False)
            row.addWidget(tag)
            row.addWidget(edit, 1)
            lay.addLayout(row)
            self._check_edits.append(edit)
        lay.addWidget(label("Master password (untuk mengenkripsi wallet)", "small"))
        self.pw_field = PasswordField("Master password")
        self.pw_field.returnPressed.connect(self._create)
        lay.addWidget(self.pw_field)
        self.verify_err = self.error_label()
        lay.addWidget(self.verify_err)
        back = button("Kembali")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.create_btn = button("Buat Wallet", "primary")
        self.create_btn.clicked.connect(self._create)
        lay.addLayout(self.button_row(back, self.create_btn))
        return page

    def _create(self) -> None:
        guesses = [e.text().strip().lower() for e in self._check_edits]
        expected = [self._words[i] for i in self._check_idx]
        if guesses != expected:
            self.show_error(self.verify_err, "Kata tidak cocok. Periksa kembali catatanmu.")
            return
        pw = self.pw_field.text()
        if not pw:
            self.show_error(self.verify_err, "Masukkan master password.")
            return
        try:
            self.created = self.vault.create_wallet(self.name_edit.text(), self._mnemonic, pw)
        except InvalidPassword:
            self.pw_field.clear()
            self.show_error(self.verify_err, "Password salah.")
            return
        except USER_ERRORS as exc:
            self.show_error(self.verify_err, str(exc))
            return
        self.accept()

    def done(self, result: int) -> None:
        self._mnemonic = ""
        self._words = []
        super().done(result)


# ==========================================================================
# Impor wallet
# ==========================================================================
class ImportWalletDialog(BaseDialog):
    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__("Impor Wallet", parent, 500)
        self.vault = vault
        self.imported: WalletRecord | None = None

        self.root.addWidget(label("Impor wallet", "heading"))
        self.root.addWidget(
            label("Pulihkan wallet yang sudah ada dengan seed phrase atau private key.", "muted", wrap=True)
        )

        self.root.addWidget(label("Nama wallet", "small"))
        self.name_edit = QLineEdit(vault.suggest_name())
        self.name_edit.setMaxLength(64)
        self.root.addWidget(self.name_edit)

        seg = QHBoxLayout()
        seg.setSpacing(8)
        self.seed_btn = button("Seed phrase", "segment")
        self.key_btn = button("Private key", "segment")
        for b in (self.seed_btn, self.key_btn):
            b.setCheckable(True)
            seg.addWidget(b)
        self.seed_btn.setChecked(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.seed_btn, 0)
        group.addButton(self.key_btn, 1)
        group.idClicked.connect(self._switch)
        self.root.addLayout(seg)

        self._mode = 0  # 0 = seed phrase, 1 = private key
        self.seed_edit = QPlainTextEdit()
        self.seed_edit.setPlaceholderText("Masukkan 12 kata seed phrase, dipisahkan spasi")
        self.seed_edit.setFixedHeight(92)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("0x… (64 karakter heksadesimal)")
        self.key_edit.hide()
        self.root.addWidget(self.seed_edit)
        self.root.addWidget(self.key_edit)

        self.root.addWidget(label("Master password (untuk mengenkripsi wallet)", "small"))
        self.pw_field = PasswordField("Master password")
        self.pw_field.returnPressed.connect(self._submit)
        self.root.addWidget(self.pw_field)

        self.err = self.error_label()
        self.root.addWidget(self.err)
        cancel = button("Batal")
        cancel.clicked.connect(self.reject)
        self.ok = button("Impor", "primary")
        self.ok.clicked.connect(self._submit)
        self.root.addLayout(self.button_row(cancel, self.ok))

    def _switch(self, idx: int) -> None:
        self._mode = idx
        self.seed_edit.setVisible(idx == 0)
        self.key_edit.setVisible(idx == 1)
        self.show_error(self.err, "")
        self.adjustSize()

    def _submit(self) -> None:
        pw = self.pw_field.text()
        if not pw:
            self.show_error(self.err, "Masukkan master password.")
            return
        name = self.name_edit.text()
        try:
            if self._mode == 0:
                self.imported = self.vault.import_mnemonic(name, self.seed_edit.toPlainText(), pw)
            else:
                self.imported = self.vault.import_private_key(name, self.key_edit.text(), pw)
        except InvalidPassword:
            self.pw_field.clear()
            self.show_error(self.err, "Password salah.")
            return
        except USER_ERRORS as exc:
            self.show_error(self.err, str(exc))
            return
        self.seed_edit.clear()
        self.key_edit.clear()
        self.accept()


# ==========================================================================
# Ganti nama
# ==========================================================================
class RenameDialog(BaseDialog):
    def __init__(self, vault: Vault, wallet: WalletRecord, parent: QWidget | None = None):
        super().__init__("Ganti Nama Wallet", parent, 400)
        self.vault = vault
        self.wallet = wallet
        self.updated: WalletRecord | None = None
        self.root.addWidget(label("Ganti nama wallet", "heading"))
        self.edit = QLineEdit(wallet.name)
        self.edit.setMaxLength(64)
        self.edit.selectAll()
        self.edit.returnPressed.connect(self._save)
        self.root.addWidget(self.edit)
        self.err = self.error_label()
        self.root.addWidget(self.err)
        cancel = button("Batal")
        cancel.clicked.connect(self.reject)
        save = button("Simpan", "primary")
        save.clicked.connect(self._save)
        self.root.addLayout(self.button_row(cancel, save))
        self.edit.setFocus()

    def _save(self) -> None:
        try:
            self.updated = self.vault.rename_wallet(self.wallet.id, self.edit.text())
        except USER_ERRORS as exc:
            self.show_error(self.err, str(exc))
            return
        self.accept()


# ==========================================================================
# Hapus wallet
# ==========================================================================
class DeleteWalletDialog(BaseDialog):
    def __init__(self, vault: Vault, wallet: WalletRecord, parent: QWidget | None = None):
        super().__init__("Hapus Wallet", parent, 480)
        self.vault = vault
        self.wallet = wallet
        self.deleted = False
        secret_name = "seed phrase" if wallet.secret_type == SECRET_MNEMONIC else "private key"

        self.root.addWidget(label(f"Hapus wallet “{wallet.name}”?", "heading"))
        self.root.addWidget(
            label(
                f"Wallet hanya dihapus dari aplikasi ini. Dana tidak ikut hilang karena tetap ada di "
                f"blockchain, dan wallet bisa diimpor kembali — tetapi HANYA jika kamu menyimpan "
                f"{secret_name}-nya. Tanpa itu, dana tidak bisa diakses lagi.",
                "warnbox",
                wrap=True,
            )
        )
        self.backup_check = QCheckBox(f"Saya sudah mencadangkan {secret_name} wallet ini")
        self.root.addWidget(self.backup_check)

        self.root.addWidget(label(f"Ketik nama wallet untuk konfirmasi:  {wallet.name}", "small", wrap=True))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(wallet.name)
        self.root.addWidget(self.name_edit)

        self.pw_field = PasswordField("Master password")
        self.root.addWidget(self.pw_field)

        self.err = self.error_label()
        self.root.addWidget(self.err)
        cancel = button("Batal")
        cancel.clicked.connect(self.reject)
        self.ok = button("Hapus Wallet", "dangerSolid")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._delete)
        self.root.addLayout(self.button_row(cancel, self.ok))

        self.backup_check.toggled.connect(self._refresh)
        self.name_edit.textChanged.connect(self._refresh)
        self.pw_field.textChanged.connect(self._refresh)
        self.pw_field.returnPressed.connect(self._delete)

    def _refresh(self, *_args) -> None:
        self.ok.setEnabled(
            self.backup_check.isChecked()
            and self.name_edit.text() == self.wallet.name
            and bool(self.pw_field.text())
        )

    def _delete(self) -> None:
        if not self.ok.isEnabled():
            return
        try:
            self.vault.delete_wallet(self.wallet.id, self.pw_field.text())
        except InvalidPassword:
            self.pw_field.clear()
            self.show_error(self.err, "Password salah.")
            return
        except USER_ERRORS as exc:
            self.show_error(self.err, str(exc))
            return
        self.deleted = True
        self.accept()


# ==========================================================================
# Terima
# ==========================================================================
class ReceiveDialog(ScreenBase):
    def __init__(self, wallet: WalletRecord, network_label: str, parent: QWidget | None = None):
        super().__init__("Terima", parent, 420)
        title = label(f"Terima ke “{wallet.name}”", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(title)
        qr = QRWidget(wallet.address, 220)
        self.root.addWidget(qr, 0, Qt.AlignmentFlag.AlignHCenter)
        addr = label(wallet.address, "secret", wrap=True, selectable=True)
        addr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(addr)
        note = label(
            f"Jaringan aktif: {network_label}. Alamat yang sama dipakai di semua jaringan EVM, "
            f"tetapi pastikan pengirim memakai jaringan yang sama dengan aplikasi ini.",
            "small",
            wrap=True,
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(note)
        copy_btn = button("Salin Alamat", "primary")
        copy_btn.clicked.connect(lambda: copy_to_clipboard(wallet.address, anchor=copy_btn))
        close_btn = button("Tutup")
        close_btn.clicked.connect(self.accept)
        self.root.addLayout(self.button_row(close_btn, copy_btn))
