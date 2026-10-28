"""
بسته‌بندی نسخه‌ی اجاره‌ای برای تحویل به مشتری.

    python build/package_rental.py <کلید لایسنس> [پوشه‌ی مقصد]
    python build/package_rental.py --check [پوشه‌ی مقصد]

کاری که می‌کنه: فایل‌های اجرایی رو از dist/ برمی‌داره، rental.json رو با
کلید داده‌شده می‌سازه، README می‌ذاره، و **چیزهایی که نباید دست مشتری
باشه رو صراحتاً بیرون نگه می‌داره**.

## چرا اسکریپت و نه کپیِ دستی

چون یه بار فراموش‌کردنِ private.key یعنی مشتری می‌تونه لایسنس خودش رو
امضا کنه و کل سیستم بی‌معنی می‌شه. این‌جا اون تصمیم از حافظه‌ی آدم
برداشته شده.
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.paths import force_utf8_console, get_base_dir

force_utf8_console()

BASE_DIR = get_base_dir()
DIST_DIR = os.path.join(BASE_DIR, "dist")

#: فایل‌های اجرایی که مشتری لازم داره.
EXECUTABLES = ("ttbot", "ttbot-launcher")

#: هرچی اسمش با این‌ها بخوره، هیچ‌وقت توی بسته نمی‌ره.
#
#: `_machine_id` عمداً این‌جاست: اگه توی بسته بمونه، **همه‌ی کپی‌های
#: بسته یه شناسه‌ی یکسان دارن** و بایندِ «یک لایسنس = یک دستگاه» عملاً
#: از بین می‌ره. هر نصب باید شناسه‌ی خودش رو در اولین اجرا بسازه.
NEVER_SHIP = ("private.key", "licensing.sqlite3", "config.json", ".env",
              "_machine_id")


def _load_build_module():
    """
    build/build.py رو به‌عنوان ماژول لود می‌کنه (بدون اجرای main())،
    دقیقاً مثل الگویی که core/manager.py و core/command_manager.py برای
    لود فایل‌های پلاگین استفاده می‌کنن.

    چرا این‌جا لازمه: EXECUTABLES فقط ttbot و ttbot-launcher رو کپی
    می‌کنه، ولی چیزی که واقعاً بین این دو به‌اشتراک گذاشته می‌شه پوشه‌ی
    _internal *ttbot* است (پایین‌تر). پس چک «آیا native هایی که ربات
    لازم داره توی بسته هستن» باید از همون منبعی بخونه که build.py
    برای هدف bot استفاده می‌کنه (TARGETS["bot"]["native"])، نه یه
    کپی‌ی جدا که ممکنه از هم عقب بیفته.
    """
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py")
    spec = importlib.util.spec_from_file_location("_ttbot_build_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing_native_components(target_dir):
    """
    کدوم native هایی که هدف bot طبق build.py لازم داره، توی بسته نیستن.

    فقط native های *bot* چک می‌شن (نه لیست کامل NATIVE_FILES) چون طبق
    B10 هر هدف فقط زیرمجموعه‌ی لازمش رو می‌گیره، و تنها هدفی که واقعاً
    توی بسته‌ی مشتری می‌ره ttbot است (EXECUTABLES بالا). هر فایل با اسم
    (نه مسیر کامل) دنبال می‌شه چون داخل onedir زیر _internal/... است.
    """
    build_module = _load_build_module()
    needed_keys = build_module.TARGETS.get("bot", {}).get("native", [])

    missing = []
    for key in needed_keys:
        names = {os.path.basename(p) for p in build_module.NATIVE_FILES.get(key, [])}
        found = False
        for _root, _dirs, files in os.walk(target_dir):
            if names & set(files):
                found = True
                break
        if not found:
            missing.append(key)
    return missing


def _exe_name(stem):
    return stem + (".exe" if os.name == "nt" else "")


def _find_exe(stem):
    """
    فایل اجرایی رو توی dist/ پیدا می‌کنه، چه onefile چه onedir.

    onedir (پیش‌فرض) هر هدف رو توی پوشه‌ی خودش می‌ذاره:
    `dist/ttbot/ttbot.exe`. onefile مستقیم `dist/ttbot.exe` می‌سازه.
    """
    name = _exe_name(stem)
    for candidate in (os.path.join(DIST_DIR, name),
                      os.path.join(DIST_DIR, stem, name)):
        if os.path.isfile(candidate):
            return candidate
    return None


def inspect(target_dir):
    """
    بسته رو هم دنبال فایل‌هایی که نباید دست مشتری باشن می‌گرده، هم دنبال
    native هایی که *باید* باشن ولی نیستن (طبق TARGETS["bot"]["native"]
    توی build.py -- ببین _missing_native_components).

    جدا از package() است چون بسته بعد از ساخته‌شدن هم عوض می‌شه:
    کافیه یه بار برای تست از توی همون پوشه اجراش کنی تا `_machine_id`
    ساخته بشه -- و اون‌وقت همه‌ی کپی‌های بسته یه شناسهی یکسان
    دارن و بایند «یک لایسنس = یک دستگاه» عملاً از بین می‌ره.

    پس دقیقاً قبل از فرستادن یه بار بزن:

        python build/package_rental.py --check [پوشه]
    """
    if not os.path.isdir(target_dir):
        print(f"پوشهی {target_dir} نیست.")
        return 1
    leaked = []
    for root, _dirs, files in os.walk(target_dir):
        for name in files:
            if any(bad in name for bad in NEVER_SHIP):
                leaked.append(os.path.join(root, name))
    if leaked:
        print("⛔ این فایل‌ها نباید توی بسته باشن:")
        for item in leaked:
            print(f"   {item}")
        print("   حذفشون کن و دوباره اجرا کن.")
        return 1

    # طرف دیگه‌ی سکه‌ی B10: bot تنها هدفیه که واقعاً توی بسته می‌ره
    # (EXECUTABLES بالا) و تنها هدفیه که این native ها رو لازم داره؛ اگه
    # وقتِ بیلد SDK/mpv/ffmpeg کنار پروژه نبودن، بسته بی‌صدا (یا بدون
    # اتصال به تیم‌تاک) تحویل مشتری می‌شد و کسی تا شکایت مشتری نمی‌فهمید.
    missing = _missing_native_components(target_dir)
    if missing:
        print(f"⛔ این native ها توی بسته نیستن ولی {EXECUTABLES[0]} لازمشون داره: "
              f"{', '.join(missing)}")
        print("   قبل از بیلد، فایل‌های SDK/mpv/ffmpeg رو کنار پروژه بذار و "
              "دوباره build/build.py bot رو بزن.")
        return 1

    print(f"✅ بسته تمیزه: {target_dir}")
    return 0


def package(license_key, target_dir):
    if not os.path.isdir(DIST_DIR):
        print(f"پوشه‌ی {DIST_DIR} نیست. اول بیلد کن:")
        print("    python build/build.py bot launcher")
        return 1

    found = {stem: _find_exe(stem) for stem in EXECUTABLES}
    missing = [_exe_name(s) for s, path in found.items() if path is None]
    if missing:
        print(f"این فایل‌های اجرایی توی dist/ نیستن: {', '.join(missing)}")
        return 1

    os.makedirs(target_dir, exist_ok=True)

    copied = []
    for stem, source in found.items():
        name = _exe_name(stem)
        destination = os.path.join(target_dir, name)
        # اگه از قبل همون‌جاست (چون کل پوشه‌ی onedir کپی شده) دوباره
        # کپی نکن -- shutil روی فایل مقصدِ خودش خطا می‌ده.
        if os.path.abspath(source) != os.path.abspath(destination):
            shutil.copy2(source, destination)
        copied.append(name)

    # onedir: پوشه‌ی _internal هم باید کنارشون باشه، وگرنه اجرا نمی‌شن.
    # قبلاً اگه _internal از قبل بود دست نمی‌خورد -- یعنی بسته‌بندی دوباره
    # روی پوشهی قبلی، بایناری‌های **کهنه** رو نگه می‌داشت درحالی‌که تو
    # فکر می‌کردی بستهی تازه ساختی. بسته باید همیشه دقیقاً همون
    # چیزی باشه که توی dist/ است.
    internal = os.path.join(target_dir, "_internal")
    source_internal = os.path.join(DIST_DIR, EXECUTABLES[0], "_internal")
    if os.path.isdir(source_internal):
        if os.path.isdir(internal):
            shutil.rmtree(internal)
            print("   (_internal کهنه پاک شد و دوباره از dist/ کپی می‌شه)")
        shutil.copytree(source_internal, internal)
        copied.append("_internal/")
    elif not os.path.isdir(internal):
        print("⚠️  پوشه‌ی _internal پیدا نشد؛ اگه بیلد onedir بوده، بسته ناقصه.")

    # فایل لایسنس مشتری
    licensing_dir = os.path.join(target_dir, "data", "licensing")
    os.makedirs(licensing_dir, exist_ok=True)
    rental_path = os.path.join(licensing_dir, "rental.json")
    if not os.path.isfile(rental_path):
        with open(rental_path, "w", encoding="utf-8") as f:
            json.dump({"key": license_key, "username": "", "password": ""},
                      f, ensure_ascii=False, indent=2)
        copied.append("data/licensing/rental.json")

    if inspect(target_dir) != 0:
        return 1

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(target_dir) for f in fs)
    print(f"✅ بسته آماده شد: {target_dir}")
    for name in copied:
        print(f"   {name}")
    print(f"   حجم کل: {total / 1024 / 1024:.1f} MB")
    print()
    print("قبل از فرستادن، این‌ها رو چک کن:")
    print("   - کلید لایسنس روی Cloudflare آپلود شده باشه")
    print("   - مشتری یوزر/پس رو توی rental.json پر کنه")
    return 0


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 2
    if argv[0] in ("--check", "-c"):
        target = argv[1] if len(argv) > 1 else os.path.join(BASE_DIR, "goldenFriends")
        return inspect(target)
    license_key = argv[0].strip().upper()
    target = argv[1] if len(argv) > 1 else os.path.join(BASE_DIR, "goldenFriends")
    return package(license_key, target)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
