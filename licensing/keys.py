"""
مدیریتِ جفت‌کلید Ed25519 پلتفرم (data/licensing/keys/).

## این کلید کجا استفاده می‌شه

فقط یه مصرف‌کننده‌ی واقعی داره: **لایسنسِ اجاره‌ای روی Cloudflare Worker**
(docs/RENTAL.md). `manage.py deploy-worker`/`worker-key` همین کلید خصوصی رو
به‌عنوان `SIGNING_KEY` روی Worker می‌ذاره؛ کلید عمومی هم با `manage.py pubkey`
گرفته می‌شه و دستی توی `core/license_key.py` (PUBLIC_KEY_B64) جا می‌گیره.

نسخه‌ی self-host (کلاینتی که مستقیم به یه API لایسنسِ خودمون توکن می‌گرفت و
با همین کلید امضاش رو چک می‌کرد) بازنشسته شده -- کدش با تاریخچه‌ی گیت قابل
برگشته، ولی دیگه صدا زده نمی‌شه.

## آنچه این *نیست*

این DRM نیست و جلوی کسی که کد پایتون رو می‌خونه و چک رو حذف می‌کنه رو
نمی‌گیره. هدفش اینه که یه مشتری معمولی نتونه بعد از پایان اشتراک به کار
ادامه بده — نه مقاومت در برابر مهندسی معکوس.
"""

import base64
import os

from licensing import config

PRIVATE_KEY_FILE = "private.key"
PUBLIC_KEY_FILE = "public.key"


class SigningUnavailable(Exception):
    pass


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        return ed25519
    except ImportError as e:
        raise SigningUnavailable(
            "برای امضای توکن به کتابخانه‌ی cryptography نیاز هست: pip install cryptography"
        ) from e


def _keys_dir():
    os.makedirs(config.KEYS_DIR, exist_ok=True)
    return config.KEYS_DIR


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def ensure_keypair():
    """
    کلید خصوصی/عمومی رو می‌سازه اگه نباشن. خروجی (private_path, public_path).
    کلید خصوصی با chmod 600 نوشته می‌شه.
    """
    ed25519 = _ed25519()
    directory = _keys_dir()
    private_path = os.path.join(directory, PRIVATE_KEY_FILE)
    public_path = os.path.join(directory, PUBLIC_KEY_FILE)

    if os.path.isfile(private_path) and os.path.isfile(public_path):
        return private_path, public_path

    from cryptography.hazmat.primitives import serialization

    private_key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    with open(private_path, "w", encoding="ascii") as f:
        f.write(_b64(private_bytes))
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    with open(public_path, "w", encoding="ascii") as f:
        f.write(_b64(public_bytes))

    return private_path, public_path


def load_private_key():
    ed25519 = _ed25519()
    private_path, _public_path = ensure_keypair()
    with open(private_path, "r", encoding="ascii") as f:
        raw = _unb64(f.read().strip())
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def public_key_b64():
    """کلید عمومی به base64 — همین رشته باید توی بیلد کلاینت باشه."""
    _private_path, public_path = ensure_keypair()
    with open(public_path, "r", encoding="ascii") as f:
        return f.read().strip()


def load_public_key(public_b64=None):
    ed25519 = _ed25519()
    raw = _unb64((public_b64 or public_key_b64()).strip())
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)
