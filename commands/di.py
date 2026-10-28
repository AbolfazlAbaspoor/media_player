from core import track_info

NAME = "di"
ADMIN_ONLY = False
USAGE = "di"


def run(ctx):
    """
    توضیحاتِ ترک در حال پخش، برای هر نوع ترک. توضیحات موقع resolve توی
    متادیتای نرمال (core/track_meta.py) ذخیره شده، پس هیچ درخواستی به
    شبکه نمی‌ره و چیزی مخصوص یوتیوب نیست.
    """
    bot = ctx["bot"]
    _kind, text = track_info.build_description_text(bot)
    track_info.deliver(bot, ctx["uid"], text)
