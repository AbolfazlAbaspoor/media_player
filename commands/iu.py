"""ریلز (یا پست‌های ویدیویی) یه پروفایلِ اینستاگرام رو از طریق اکانتِ وصل‌شده‌ت
به صف می‌ریزه و فقط صداش رو پخش می‌کنه. (ir همین کار رو بدونِ لاگین با
yt-dlp می‌کنه؛ این یکی با API خودِ اینستاگرامه و قابل‌اعتمادتره.)

    iu <username>          -> ریلزهای اخیر
    iu <username> posts    -> پست‌های ویدیویی اخیر
"""
from core import instagram_api, instagram_bot

NAME = 'iu'
ADMIN_ONLY = False
USAGE = 'iu <username> [posts]  (recent reels or video posts of a profile, audio only)'


def run(ctx):
    name = instagram_bot.username_arg(ctx, USAGE)
    if not name:
        return
    posts = (ctx['args'][1:2] or [''])[0].lower() == 'posts'
    fetch = instagram_api.fetch_user_posts if posts else instagram_api.fetch_user_reels
    instagram_bot.run_browse(ctx, lambda client: fetch(client, name), f"@{name}")
