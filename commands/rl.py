"""فیدِ ریلزِ خودِ حسابِ اینستاگرام رو به صف می‌ریزه و پخش می‌کنه (فقط صدا).
بعدش n/b توی همون صف می‌چرخن و lr/cr/fr روی ریلِ جاری کار می‌کنن.

    rl            -> فیدِ ریلزِ خودت
    rl explore    -> ریلزِ کشف (Explore)
"""
from core import i18n, instagram_api, instagram_bot

NAME = 'rl'
ADMIN_ONLY = False
USAGE = 'rl [explore]  (your Instagram reels feed, audio only)'


def run(ctx):
    explore = (ctx.get('args') or [''])[0].lower() == 'explore'
    fetch = instagram_api.fetch_explore_reels if explore else instagram_api.fetch_feed_reels
    instagram_bot.run_browse(ctx, fetch, i18n.t('ig_what_explore' if explore else 'ig_what_feed'))
