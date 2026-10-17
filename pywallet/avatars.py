"""Foto profil wallet: impor gambar dari komputer -> crop persegi -> salinan lokal 256x256.

Yang disimpan hanya salinan yang sudah diperkecil di folder data aplikasi, jadi memindahkan atau
menghapus gambar aslinya tidak memengaruhi aplikasi. Nama file divalidasi agar data database yang
dimodifikasi tidak bisa menunjuk ke file di luar folder avatars.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QImageReader

AVATAR_SIZE = 256
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 60_000_000
IMAGE_FILTER = "Gambar (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Semua file (*)"

_NAME_RE = re.compile(r"^wallet_\d+_[0-9a-f]{8}\.png$")


class AvatarError(Exception):
    """Pesan aman ditampilkan ke pengguna."""


class AvatarStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, filename: str | None) -> Path | None:
        if not filename or not _NAME_RE.match(filename):
            return None
        p = self.dir / filename
        return p if p.is_file() else None

    def import_image(self, wallet_id: int, source: str | Path) -> str:
        source = Path(source)
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise AvatarError("File tidak bisa dibuka.") from exc
        if size > MAX_FILE_BYTES:
            raise AvatarError("Ukuran gambar terlalu besar (maksimal 20 MB).")

        reader = QImageReader(str(source))
        reader.setAutoTransform(True)               # hormati orientasi EXIF dari kamera
        dims = reader.size()
        if dims.isValid() and dims.width() * dims.height() > MAX_PIXELS:
            raise AvatarError("Resolusi gambar terlalu besar.")
        image = reader.read()
        if image.isNull():
            raise AvatarError("File ini bukan gambar yang didukung (PNG, JPG, WebP, BMP, GIF).")

        # Crop persegi dari tengah, lalu perkecil.
        side = min(image.width(), image.height())
        square = image.copy(QRect((image.width() - side) // 2, (image.height() - side) // 2, side, side))
        square = square.scaled(
            AVATAR_SIZE, AVATAR_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_ARGB32)

        filename = f"wallet_{wallet_id}_{secrets.token_hex(4)}.png"
        if not square.save(str(self.dir / filename), "PNG"):
            raise AvatarError("Gagal menyimpan foto profil.")
        return filename

    def remove(self, filename: str | None) -> None:
        p = self.path(filename)
        if p is not None:
            try:
                os.remove(p)
            except OSError:
                pass
