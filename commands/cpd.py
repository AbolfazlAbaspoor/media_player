"""
بقیه‌ی دسته‌بندی‌های یه کانال: پادکست‌ها و ریلیزهای موسیقی.

    cpd     -> پادکست‌های کانال
    crl     -> آلبوم/ریلیزهای موسیقیِ کانال

هر کانال همه‌ی این تب‌ها رو نداره؛ اگه نداشته باشه همون رو می‌گیم به‌جای
یه خطای گنگ.
"""

from core import command_helpers
from core import i18n

NAME = ("cpd", "crl")
ADMIN_ONLY = False
USAGE = "cpd (channel podcasts) | crl (channel music releases)"

_TABS = {
    "cpd": ("get_channel_podcasts", "channel_podcasts_loading", "channel_no_podcasts"),
    "crl": ("get_channel_releases", "channel_releases_loading", "channel_no_releases"),
}


def run(ctx):
    tab = _TABS.get(ctx["cmd"])
    if tab is None:
        ctx["bot"].t.user_message(ctx["uid"], i18n.t("usage_generic", usage=USAGE))
        return
    method, loading_key, empty_key = tab
    command_helpers.run_channel_content_command(
        ctx, method, loading_key=loading_key, empty_key=empty_key)
