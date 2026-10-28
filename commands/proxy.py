"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import proxy_state

NAME = 'proxy'
REQUIRED_ROLE = "admin_server"
USAGE = 'proxy <link|off>'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        cur = bot.cfg.get('proxy', {})
        state = i18n.t('state_enabled') if cur.get('enabled') else i18n.t('state_disabled')
        bot.t.user_message(ctx['uid'], i18n.t('proxy_status', state=state, url=proxy_state.mask(cur.get('url')) or 'not set'))
        return
    if args[0].lower() in ('off', 'none', 'clear'):
        # حذف کاملِ پروکسی (و بستنِ xray اگه لینک V2Ray بود)
        bot.cfg.setdefault('proxy', {})['url'] = None
        bot.cfg['proxy']['enabled'] = False
        proxy_state.configure(False, None)
        bot.apply_proxy_to_player()
        bot.save_config()
        bot.t.user_message(ctx['uid'], i18n.t('proxy_cleared'))
        return
    # اعتبارسنجی قبل از ذخیره: یه آدرس خراب (مثل "http:127.0.0.1:2080" بدون //)
    # اگه ذخیره بشه، از اون به بعد هر سرچ/دانلودی بی‌صدا fail می‌شه و کاربر
    # هیچ‌وقت نمی‌فهمه چرا. پس همین‌جا یا اصلاحش می‌کنیم یا ردش می‌کنیم.
    url, error = proxy_state.validate(args[0])
    if error:
        bot.t.user_message(ctx['uid'], i18n.t('proxy_invalid', error=error))
        return
    bot.cfg.setdefault('proxy', {})['url'] = url
    bot.cfg['proxy']['enabled'] = True
    proxy_state.configure(True, url)
    bot.apply_proxy_to_player()
    bot.save_config()
    if proxy_state.is_v2ray(url) and not proxy_state.get_proxy_url():
        # xray بالا نیومد (باینری نیست یا سرور/لینک مشکل داره)؛ جزئیات توی لاگ
        bot.t.user_message(ctx['uid'], i18n.t('proxy_v2ray_unavailable', url=proxy_state.mask(url)))
        return
    bot.t.user_message(ctx['uid'], i18n.t('proxy_set_confirm', url=proxy_state.mask(url)))
