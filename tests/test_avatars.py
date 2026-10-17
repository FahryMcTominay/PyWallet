import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pywallet import avatars  # noqa: E402
from pywallet.avatars import AvatarError, AvatarStore  # noqa: E402
from pywallet.db import Database  # noqa: E402
from pywallet.vault import Vault  # noqa: E402

FAST_KDF = {"n": 2**10, "r": 8, "p": 1}
MNEMONIC = "test test test test test test test test test test test junk"


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def make_image(path, w=400, h=200):
    """Kiri biru (100px), tengah hijau (200px), kanan merah (100px)."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("green"))
    for x in range(100):
        for y in range(h):
            img.setPixelColor(x, y, QColor("blue"))
            img.setPixelColor(w - 1 - x, y, QColor("red"))
    assert img.save(str(path))
    return path


def test_import_center_crops_and_resizes(tmp_path):
    src = make_image(tmp_path / "foto.png")
    store = AvatarStore(tmp_path / "avatars")
    name = store.import_image(7, src)
    saved = store.path(name)
    assert saved is not None and name.startswith("wallet_7_")
    img = QImage(str(saved))
    assert (img.width(), img.height()) == (avatars.AVATAR_SIZE, avatars.AVATAR_SIZE)
    # crop persegi dari tengah => hanya bagian hijau yang tersisa
    for x, y in [(0, 0), (255, 0), (0, 255), (255, 255), (128, 128)]:
        assert img.pixelColor(x, y).green() > 100 and img.pixelColor(x, y).red() < 60


def test_replacing_creates_new_file_name(tmp_path):
    src = make_image(tmp_path / "foto.png")
    store = AvatarStore(tmp_path / "avatars")
    a = store.import_image(1, src)
    b = store.import_image(1, src)
    assert a != b
    store.remove(a)
    assert store.path(a) is None and store.path(b) is not None


def test_rejects_non_image_and_missing_and_oversize(tmp_path, monkeypatch):
    store = AvatarStore(tmp_path / "avatars")
    fake = tmp_path / "bukan.png"
    fake.write_text("ini bukan gambar")
    with pytest.raises(AvatarError):
        store.import_image(1, fake)
    with pytest.raises(AvatarError):
        store.import_image(1, tmp_path / "tidak-ada.png")
    big = make_image(tmp_path / "besar.png")
    monkeypatch.setattr(avatars, "MAX_FILE_BYTES", 10)
    with pytest.raises(AvatarError, match="besar"):
        store.import_image(1, big)
    assert list((tmp_path / "avatars").iterdir()) == []       # tidak ada sisa file


@pytest.mark.parametrize("bad", ["../secret.png", "wallet_1_zzzzzzzz.png", "/etc/passwd", "", None, "wallet_1_abcd1234.jpg"])
def test_path_rejects_unsafe_filenames(tmp_path, bad):
    store = AvatarStore(tmp_path / "avatars")
    (tmp_path / "secret.png").write_bytes(b"x")
    assert store.path(bad) is None


def test_vault_avatar_roundtrip_and_prefs(tmp_path):
    v = Vault(Database(tmp_path / "a.db"))
    v.setup_master_password("rahasia-kuat-123", kdf=FAST_KDF)
    w = v.import_mnemonic("A", MNEMONIC, "rahasia-kuat-123")
    assert w.avatar is None
    assert v.set_avatar(w.id, "wallet_1_abcd1234.png").avatar == "wallet_1_abcd1234.png"
    assert v.get_wallet(w.id).avatar == "wallet_1_abcd1234.png"
    assert v.set_avatar(w.id, None).avatar is None
    assert v.get_pref("unit", "usd") == "usd"
    v.set_pref("unit", "idr")
    assert v.get_pref("unit") == "idr"


def test_migration_from_v1_keeps_existing_wallets(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            address TEXT NOT NULL UNIQUE,
            secret_type TEXT NOT NULL CHECK (secret_type IN ('mnemonic', 'private_key')),
            secret_enc BLOB NOT NULL,
            derivation_path TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        INSERT INTO wallets (name, address, secret_type, secret_enc) VALUES ('Lama', '0xabc', 'mnemonic', x'00');
        PRAGMA user_version = 1;
        """
    )
    con.commit()
    con.close()
    db = Database(path)
    row = db.conn.execute("SELECT name, avatar FROM wallets").fetchone()
    assert row["name"] == "Lama" and row["avatar"] is None
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 2
