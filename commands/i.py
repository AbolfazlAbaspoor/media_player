from core import i18n, track_info

NAME = "i"
ADMIN_ONLY = False
USAGE = "i"


def run(ctx):
    """
    اطلاعات کاملِ ترک در حال پخش، برای هر نوع ترک (نه فقط یه سرویس): همه‌ی
    فیلدهایی که موقع resolve جمع شده (core/track_meta.py) و مشخصات فنیِ
    زنده‌ی پلیر. فیلد بدون مقدار نمایش داده نمی‌شه؛ لینکِ منبع فقط برای
    ترکِ قابل‌اشتراک -- ساختنِ متن توی core/track_info.py است.
    """
    bot = ctx["bot"]
    text = track_info.build_info_text(bot)
    if text is None:
        bot.t.user_message(ctx["uid"], i18n.t("nothing_playing"))
        return
    track_info.deliver(bot, ctx["uid"], text)
