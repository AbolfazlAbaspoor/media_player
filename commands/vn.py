"""
رأی برای رد کردنِ آهنگِ فعلی. وقتی رأی‌ها از نصفِ کاربرهای کانال بیشتر بشه
(قابل‌تنظیم: vote_skip.ratio توی shared_config) آهنگ مثلِ n رد می‌شه؛ یه نفرِ
تنها فوراً رد می‌کنه. منطق و توضیح کامل توی core/voteskip.py.
"""

from core import voteskip

NAME = 'vn'
ADMIN_ONLY = False
USAGE = 'vn  (vote to skip the current track; it skips when more than half of the channel agrees)'


def run(ctx):
    voteskip.run_vote(ctx["bot"], ctx)
