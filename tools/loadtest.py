"""
تست بار سبک: هزینه‌ی هر پروسه‌ی ربات (رم/CPU/thread) بدون نیاز به سرور تیم‌تاک.

دو حالت:
  python tools/loadtest.py spawn -n 20 -d 15   # N پروسه‌ی «ربات بیکار» (فقط
                                               # import کامل ربات + انتظار) بساز و بسنج
  python tools/loadtest.py attach [-m bot.py]  # پروسه‌های ربات در حال اجرا رو بسنج

خروجی: RSS هر پروسه (میانگین/بیشینه)، مجموع، CPU، و زمان import.
شبیه‌ساز، اتصال TeamTalk و mpv رو شامل نمی‌شه؛ هزینه‌ی پایه‌ی پایتون + کد
ربات رو نشون می‌ده که همون چیزیه که در مقیاس هزاران پروسه ضرب می‌شه.
"""

import argparse
import os
import subprocess
import sys
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# فرزند: ربات رو import می‌کنه (زمانش رو چاپ می‌کنه) و بیکار می‌مونه.
_CHILD = (
    "import sys,time;sys.argv=['bot.py'];t=time.perf_counter()\n"
    "try:\n import bot\nexcept BaseException:\n pass\n"
    "print('import_s',round(time.perf_counter()-t,3),flush=True)\n"
    "time.sleep(3600)\n"
)


def summarize(procs, seconds):
    """میانگین/بیشینه‌ی RSS و CPU در بازه‌ی seconds برای لیستی از psutil.Process."""
    t0 = time.time()
    cpu0 = {p.pid: sum(p.cpu_times()[:2]) for p in procs}
    time.sleep(seconds)
    dt = time.time() - t0
    rss, cpu, thr = [], [], []
    for p in procs:
        try:
            rss.append(p.memory_info().rss / 1048576)
            cpu.append(100 * (sum(p.cpu_times()[:2]) - cpu0[p.pid]) / dt)
            thr.append(p.num_threads())
        except psutil.Error:
            continue
    if not rss:
        return None
    return {
        "processes": len(rss),
        "rss_mb_avg": round(sum(rss) / len(rss), 1),
        "rss_mb_max": round(max(rss), 1),
        "rss_mb_total": round(sum(rss), 1),
        "cpu_percent_avg": round(sum(cpu) / len(cpu), 3),
        "threads_avg": round(sum(thr) / len(thr), 1),
    }


def spawn(n, seconds, root=ROOT):
    children = []
    for _ in range(n):
        children.append(subprocess.Popen([sys.executable, "-c", _CHILD], cwd=root,
                                         env=dict(os.environ, PYTHONPATH=root),
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True))
    try:
        imports = [float(c.stdout.readline().split()[1]) for c in children]
        result = summarize([psutil.Process(c.pid) for c in children], seconds)
        result["import_s_avg"] = round(sum(imports) / len(imports), 3)
        return result
    finally:
        for c in children:
            c.terminate()


def attach(marker):
    me = os.getpid()
    procs = [p for p in psutil.process_iter(["cmdline"])
             if p.pid != me and any(os.path.basename(a) == marker for a in (p.info["cmdline"] or [])[:3])]
    return summarize(procs, 5) if procs else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    sp = sub.add_parser("spawn")
    sp.add_argument("-n", type=int, default=10)
    sp.add_argument("--root", default=ROOT, help="پوشه‌ی پروژه (برای مقایسه‌ی قبل/بعد)")
    sp.add_argument("-d", type=float, default=10, help="طول اندازه‌گیری CPU (ثانیه)")
    at = sub.add_parser("attach")
    at.add_argument("-m", default="bot.py", help="اسم اسکریپت ربات توی cmdline")
    args = ap.parse_args(argv)
    result = spawn(args.n, args.d, args.root) if args.mode == "spawn" else attach(args.m)
    if not result:
        print("no processes measured")
        return 1
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
