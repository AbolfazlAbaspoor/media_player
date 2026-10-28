"""
Runtime hook: خفه‌کردن هشدارهای خودِ PyInstaller قبل از هر چیز دیگه.

## چرا اینجا و نه توی خود برنامه

`warnings.filterwarnings()` داخل bot.py/launcher.py دیر اجرا می‌شه:
لودرِ PyInstaller هشدارِ deprecation مربوط به `pkg_resources` رو موقع
بوت‌استرپ چاپ می‌کنه، یعنی *قبل از* این‌که اولین خط کد ما اجرا بشه.

برای کاربر نهایی این یه پیام ترسناک و بی‌ربطه که سر هر اجرا می‌بینه.
runtime hook تنها جاییه که زودتر از لودر اجرا می‌شه.

فقط همین یه دسته هشدار خفه می‌شه؛ خطاهای واقعی و هشدارهای خود برنامه
دست‌نخورده باقی می‌مونن.
"""

import warnings

warnings.filterwarnings("ignore", message=r".*pkg_resources is deprecated.*")
warnings.filterwarnings("ignore", category=UserWarning, module=r"pkg_resources.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"pkg_resources.*")
