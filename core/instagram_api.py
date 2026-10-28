"""
Instagram API operations for reels, likes, follows, comments.

Wraps instagrapi with error handling and graceful degradation.
"""

import json
import logging

from core import logging_setup
from core import proxy_state

# instagrapi (با pydantic/PIL/cryptography) حدود ۰.۵ ثانیه import و چند ده MB
# رم می‌خوره؛ فقط وقتی واقعاً یه دستور اینستاگرام اجرا بشه لود می‌شه، نه
# موقع بالا اومدن ربات.
def _load_client_class():
    try:
        from instagrapi import Client
    except ImportError:
        return None
    return Client


def _parse_settings(cookie_str):
    """
    settings ذخیره‌شده. سشن‌های جدید JSON‌ان؛ سشن‌های قدیمی با str() (repr
    پایتون) ذخیره شده بودن که json.loads همیشه روشون شکست می‌خورد -- اون‌ها
    با ast.literal_eval خونده می‌شن تا کاربرای قبلی لازم نباشه دوباره لاگین کنن.
    """
    try:
        return json.loads(cookie_str)
    except ValueError:
        pass
    try:
        import ast
        value = ast.literal_eval(cookie_str)
        return value if isinstance(value, dict) else None
    except (ValueError, SyntaxError):
        return None


def new_client():
    """
    instagrapi Client تازه، با پروکسیِ ربات (اینستاگرام اینجا فیلتره؛ بدونِ
    پروکسی همه‌چیز با خطای شبکه شکست می‌خوره). None اگه کتابخونه نصب نیست.
    تنها جایی که Client ساخته می‌شه -- لاگین، sessionid و بازیابیِ سشن همه
    از همین رد می‌شن تا هیچ درخواستی بدونِ پروکسی نره.
    """
    Client = _load_client_class()
    if Client is None:
        return None
    client = Client()
    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        client.set_proxy(proxy_url)
    return client


def load_client_from_session(session_data, cookie_str):
    """
    Reconstruct instagrapi Client from saved session.
    session_data: dict from instagram_user.load_saved_session()
    cookie_str: decrypted cookie string
    Returns: Client or None if failed
    """
    try:
        client = new_client()
        if client is None:
            return None
        if cookie_str:
            settings = _parse_settings(cookie_str)
            if settings:
                client.set_settings(settings)
        return client
    except Exception as e:
        logging_setup.log_debug(f"failed to restore instagrapi client: {e}")
        return None


# ---------------------------------------------------------------------------
# مرور و پخشِ محتوا (همه‌ی این‌ها استثنا رو *رد می‌کنن بالا*: دلیلِ واقعیِ
# شکست -- بلاک، چلنج، محدودیت -- باید به پیامِ مناسب ترجمه بشه، نه اینکه
# با «[]» قورت داده بشه.)
# ---------------------------------------------------------------------------

def fetch_feed_reels(client, amount=10):
    return client.reels_timeline_media("reels", amount)


def fetch_explore_reels(client, amount=10):
    return client.explore_reels(amount)


def fetch_user_reels(client, username, amount=10):
    return client.user_clips(client.user_id_from_username(username), amount)


def fetch_user_posts(client, username, amount=10):
    return client.user_medias(client.user_id_from_username(username), amount)


def fetch_user_stories(client, username):
    return client.user_stories(client.user_id_from_username(username))


def fetch_user_highlights(client, username, max_highlights=3):
    """آیتم‌های چند هایلایتِ اول (هر هایلایت یه درخواستِ جدا لازم داره)."""
    pks = [h.pk for h in client.user_highlights(client.user_id_from_username(username))]
    items = []
    for pk in pks[:max_highlights]:
        items.extend(client.highlight_info(pk).items or [])
    return items


def fetch_hashtag_reels(client, hashtag, amount=10):
    return client.hashtag_medias_reels_v1(hashtag, amount)


def fetch_saved(client, amount=10):
    return client.collection_medias("ALL_MEDIA_AUTO_COLLECTION", amount)


def fetch_liked(client, amount=10):
    return client.liked_medias(amount)


def search_users(client, query, limit=8):
    """[(username, full_name, is_private)] برای iss."""
    return [(u.username, u.full_name or "", bool(u.is_private))
            for u in client.search_users(query)[:limit]]


def _playable_url(media):
    """لینکِ ویدیوی مدیا (یا اولین ویدیوی آلبوم). None برای عکس -- فقط صدا پخش می‌شه."""
    url = getattr(media, "video_url", None)
    if not url:
        for res in getattr(media, "resources", None) or []:
            url = getattr(res, "video_url", None)
            if url:
                break
    return str(url) if url else None


def _public_url(media):
    """لینکِ صفحه‌ی مدیا (برای k/اشتراک -- لینکِ CDN منقضی می‌شه)."""
    code = getattr(media, "code", None)
    if not code:
        return None
    if getattr(media, "product_type", "") == "story":
        return f"https://www.instagram.com/stories/{media.user.username}/{media.pk}/"
    if getattr(media, "media_type", None) == 2 and getattr(media, "product_type", "") == "clips":
        return f"https://www.instagram.com/reel/{code}/"
    return f"https://www.instagram.com/p/{code}/"


def playable_medias(medias):
    """فقط مدیاهایی که ویدیو دارن (عکس صدا نداره)."""
    return [m for m in medias or [] if _playable_url(m)]


def to_play_items(medias):
    """
    مدیاها -> آیتم‌های قابل‌پخشِ bot.load_and_play ({url,title,public_url}).
    آیتم‌های بدونِ ویدیو (عکس) رد می‌شن. verified_media: لینکِ CDN مستقیمه،
    نباید دوباره برای m3u بودن دانلود/چک بشه.
    """
    items = []
    for media in playable_medias(medias):
        url = _playable_url(media)
        info = get_reel_info(media)
        caption = " ".join((info["caption"] or "").split())[:80]
        title = f"{info['author']}: {caption}" if caption else info["author"]
        items.append({"url": url, "title": title,
                      "public_url": _public_url(media), "verified_media": True})
    return items


def get_reel_info(reel):
    """Extract human-friendly info from reel object."""
    try:
        return {
            "id": reel.pk if hasattr(reel, "pk") else None,
            # instagrapi فیلدِ caption_text داره (نه caption)؛ استوری کپشن نداره.
            "caption": getattr(reel, "caption_text", None) or getattr(reel, "caption", None) or "",
            "author": reel.user.username if hasattr(reel, "user") and hasattr(reel.user, "username") else "unknown",
            "likes": reel.like_count if hasattr(reel, "like_count") else 0,
            "is_liked": reel.has_liked if hasattr(reel, "has_liked") else False,
        }
    except Exception:
        return {"id": None, "caption": "", "author": "unknown", "likes": 0, "is_liked": False}


def like_reel(client, reel_pk):
    """Like a reel by media PK."""
    if not client or not reel_pk:
        return False
    try:
        client.media_like(reel_pk)
        return True
    except Exception as e:
        logging_setup.log_debug(f"failed to like reel {reel_pk}: {e}")
        return False


def unlike_reel(client, reel_pk):
    """Unlike a reel."""
    if not client or not reel_pk:
        return False
    try:
        client.media_unlike(reel_pk)
        return True
    except Exception as e:
        logging_setup.log_debug(f"failed to unlike reel {reel_pk}: {e}")
        return False


def comment_reel(client, reel_pk, text):
    """Comment on a reel."""
    if not client or not reel_pk:
        return False
    try:
        client.media_comment(reel_pk, text)
        return True
    except Exception as e:
        logging_setup.log_debug(f"failed to comment on reel {reel_pk}: {e}")
        return False


def follow_user(client, user_pk):
    """Follow a user by user PK."""
    if not client or not user_pk:
        return False
    try:
        client.user_follow(user_pk)
        return True
    except Exception as e:
        logging_setup.log_debug(f"failed to follow user {user_pk}: {e}")
        return False


def unfollow_user(client, user_pk):
    """Unfollow a user."""
    if not client or not user_pk:
        return False
    try:
        client.user_unfollow(user_pk)
        return True
    except Exception as e:
        logging_setup.log_debug(f"failed to unfollow user {user_pk}: {e}")
        return False
