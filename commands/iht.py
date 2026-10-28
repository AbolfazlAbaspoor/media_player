"""ریلزِ یه هشتگ از طریق اکانتِ وصل‌شده (فقط صدا). ird همین رو بدونِ لاگین
با yt-dlp می‌کنه؛ این یکی ریلز رو مستقیم از API می‌گیره."""
from core import i18n, instagram_api, instagram_bot

NAME = 'iht'
ADMIN_ONLY = False
USAGE = 'iht <hashtag>  (reels of a hashtag, audio only)'


def run(ctx):
    args = ctx.get('args') or []
    tag = args[0].lstrip('#').strip() if args else ''
    if not tag:
        ctx['bot'].t.user_message(ctx['uid'], i18n.t('usage_generic', usage=USAGE))
        return
    instagram_bot.run_browse(ctx, lambda client: instagram_api.fetch_hashtag_reels(client, tag), f"#{tag}")
