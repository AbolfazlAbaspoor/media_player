"""
ابزار خط فرمان مدیریت سرور — همون کارهای ربات تلگرام، ولی از ترمینال.

برای وقتی که تلگرام در دسترس نیست، یا داری دیباگ می‌کنی، یا می‌خوای یه
کار رو توی یه اسکریپت/کران بذاری.

    python manage.py devices                 دستگاه‌های صدای این سیستم
    python manage.py lines                    لاین‌های صدا
    python manage.py line-add <slug>          ساخت لاین
    python manage.py line-del <slug>          حذف لاین
    python manage.py line-ensure              بازسازی لاین‌های از بین رفته
    python manage.py licenses                 لیست لایسنس‌ها
    python manage.py license <کلید>           جزئیات یه لایسنس
    python manage.py instances                لیست ربات‌ها
    python manage.py grant <tg_id> <ماه> [ربات] [امکانات...]
    python manage.py extend <کلید> <ماه>
    python manage.py suspend <کلید> [دلیل]
    python manage.py revoke <کلید> [دلیل]
    python manage.py sweep                    چک انقضا (همون چک شبانه)
    python manage.py gc [--apply] [--categories a,b] [--retention-days N]
                                              پاکسازی پسماند (پیش‌فرض فقط گزارش)
    python manage.py catalog                  قیمت‌ها و امکانات
    python manage.py quote <ماه> <ربات> [امکانات...]
    python manage.py rate [عدد|auto]          نرخ دلار
    python manage.py pubkey                   کلید عمومی برای core/license_key.py
    python manage.py worker-key               کلید امضا برای Cloudflare Worker (راز!)
    python manage.py rental <روز>             ساخت لایسنس اجاره‌ای
    python manage.py rental-extend <کلید> <روز> [--unrevoke]   تمدید/جبران، بدونِ دست‌زدن به بایند
    python manage.py rental-reset <کلید>   بعد از تست: بایند بردار + ۳۰ روز نو
    python manage.py build-check              قبل از تحویل: قفل‌ها بسته‌ست؟
    python manage.py deploy-worker            راه‌اندازی کامل Cloudflare
    python manage.py cf-token [توکن]          توکن API کلادفلر (برای صدور از تلگرام)
    python manage.py error-keys               جفت‌کلید رمزنگاری لاگ خطا
    python manage.py read-errors <فایل>       بازکردن لاگ رمزشده‌ی مشتری
    python manage.py doctor                   بررسی سلامت نصب پلتفرم
    python manage.py selftest                 تست سلامت ربات (صدا، دستگاه‌ها، سرویس‌ها)
    python manage.py self-license <tg_id> [bot_dir]
                                              لایسنس دائمی مالک (برای اجرای خودت)
    python manage.py promos                   لیست کدهای تخفیف/هدیه
    python manage.py promo-add <کد> <نوع> <مقدار> <روز اعتبار> [گزینه‌ها]
    python manage.py promo-off <کد>           غیرفعال کردن یک کد
    python manage.py gift <tg_id> <ساعت>      ساعت جایزه به یک کاربر
"""

import json
import sys
import time


from core import paths
from core import audio_lines
from core import platform_paths

paths.force_utf8_console()


def _db():
    from licensing.db import get_db
    return get_db()


def _fmt_time(value):
    if not value:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))


# ---------------------------------------------------------------- دستگاه‌ها

def cmd_devices(args):
    print(f"سیستم: {platform_paths.describe_runtime()}")
    print(f"backend لاین صدا: {audio_lines.backend()} "
          f"(ساخت لاین جدید: {'بله' if audio_lines.backend_is_manageable() else 'نه'})")
    print()

    print("--- خروجی (mpv) ---")
    outputs = audio_lines.list_output_devices()
    if not outputs:
        print("  (پیدا نشد — libmpv نصب هست؟)")
    for name, description in outputs:
        cable = audio_lines._windows_cable_key(description) or audio_lines._windows_cable_key(name)
        tag = f"   [کابل مجازی: {cable}]" if cable else ""
        print(f"  {description}{tag}")
        print(f"      name={name}")

    print()
    print("--- ورودی (TeamTalk) ---")
    preferred = audio_lines.preferred_sound_system()
    inputs = audio_lines.list_input_devices()
    if not inputs:
        print("  (پیدا نشد — TeamTalk SDK سر جاشه؟)")
    for dev_id, name, sound_system, dev_id_str in inputs:
        star = " *" if preferred is not None and sound_system == preferred else ""
        cable = audio_lines._windows_cable_key(name)
        tag = f"   [کابل مجازی: {cable}]" if cable else ""
        print(f"  [{dev_id}] {name}{star}{tag}")
        if dev_id_str:
            print(f"      id={dev_id_str}")
    if preferred is not None:
        print()
        print("  * = سیستم صوتی پیشنهادی این OS (همون که resolve اول امتحان می‌کنه)")
    return 0


def cmd_lines(args):
    lines = audio_lines.list_lines()
    if not lines:
        print("هیچ لاین صدایی ثبت نشده.")
        return 0
    for line in lines:
        mark = "🟢" if line.get("alive") else "🔴"
        print(f"{mark} {line['slug']}  ({line.get('backend')})")
        print(f"    out: {line.get('output_device')}")
        print(f"    in : {line.get('input_device')}")
        if line.get("owner"):
            print(f"    مالک: {line['owner']}")
    return 0


def cmd_line_add(args):
    if not args:
        print("استفاده: python manage.py line-add <slug> [توضیح]")
        return 2
    slug = args[0]
    description = " ".join(args[1:]) or None
    try:
        line = audio_lines.create_line(slug, description=description, owner="manage.py")
    except audio_lines.AudioLineError as e:
        print(f"نشد: {e}")
        return 1
    print(f"لاین '{line['slug']}' آماده شد:")
    print(f"  خروجی (mpv):      {line['output_device']}")
    print(f"  ورودی (TeamTalk): {line['input_device']}")
    print()
    print("توی identity.json ربات این دو مقدار رو بذار:")
    print(f'  "audio": {{"input_device": "line:{line["slug"]}", '
          f'"output_device": "line:{line["slug"]}"}}')
    return 0


def cmd_line_del(args):
    if not args:
        print("استفاده: python manage.py line-del <slug>")
        return 2
    if audio_lines.destroy_line(args[0]):
        print(f"لاین '{args[0]}' حذف شد.")
        return 0
    print(f"لاین '{args[0]}' ثبت نشده بود.")
    return 1


def cmd_line_ensure(args):
    restored = audio_lines.ensure_all_lines()
    print(f"{restored} لاین بازسازی شد.")
    return 0


# ----------------------------------------------------------------- لایسنس

def cmd_licenses(args):
    from licensing import licenses
    db = _db()
    rows = db.query("SELECT * FROM licenses ORDER BY id DESC")
    if not rows:
        print("هیچ لایسنسی نیست.")
        return 0
    for row in rows:
        _code, status_text = licenses.describe_status(row)
        instances = db.instances_by_license(int(row["id"]))
        print(f"{row['key']}  user={row['user_id']}  {status_text}")
        print(f"    پایان: {_fmt_time(row['expires_at'])}  "
              f"سهمیه: {len(instances)}/{row['max_bots']} ربات")
        features = json.loads(row["features"] or "[]")
        print(f"    امکانات: {', '.join(features) or '(فقط یوتیوب)'}")
    return 0


def _license_from_args(args):
    """(db, ردیفِ لایسنسِ args[0]) -- اگه پیدا نشد پیام می‌ده و row=None برمی‌گردونه."""
    db = _db()
    row = db.get_license_by_key(args[0].strip().upper())
    if row is None:
        print("پیدا نشد.")
    return db, row


def cmd_license(args):
    from licensing import licenses
    if not args:
        print("استفاده: python manage.py license <کلید>")
        return 2
    db, row = _license_from_args(args)
    if row is None:
        return 1
    _code, status_text = licenses.describe_status(row)
    print(f"کلید: {row['key']}")
    print(f"کاربر تلگرام: {row['user_id']}")
    print(f"وضعیت: {status_text}  (status={row['status']})")
    print(f"شروع: {_fmt_time(row['starts_at'])}")
    print(f"پایان: {_fmt_time(row['expires_at'])}")
    print(f"مهلت تا: {_fmt_time(row['grace_until'])}")
    print(f"سهمیه: {row['max_bots']} ربات")
    print(f"امکانات: {', '.join(json.loads(row['features'] or '[]')) or '(فقط یوتیوب)'}")
    print("ربات‌ها:")
    for instance in db.instances_by_license(int(row["id"]), include_removed=True):
        print(f"  - {instance['slug']}  {instance['tt_host']}:{instance['tt_port']}  "
              f"[{instance['status']}]  line={instance['audio_line']}")
    return 0


def cmd_instances(args):
    db = _db()
    rows = db.query("SELECT * FROM instances ORDER BY id ASC")
    if not rows:
        print("هیچ رباتی ثبت نشده.")
        return 0
    for row in rows:
        license_row = db.get_license(int(row["license_id"]))
        print(f"{row['slug']}  [{row['status']}]  "
              f"{row['tt_host']}:{row['tt_port']}  nick={row['tt_nickname']}")
        print(f"    لاین: {row['audio_line']}  پوشه: {row['group_name']}/{row['bot_name']}")
        print(f"    لایسنس: {license_row['key'] if license_row else '؟'}  "
              f"pid={row['pid']}  آخرین خروج={row['last_exit_code']}")
    return 0


def cmd_grant(args):
    from licensing import catalog, licenses
    if len(args) < 2:
        print("استفاده: python manage.py grant <telegram_id> <ماه> [ربات] [امکانات...]")
        print(f"امکانات موجود: {', '.join(catalog.features())}")
        return 2
    db = _db()
    try:
        user_id = int(args[0])
        months = int(args[1])
        bots = int(args[2]) if len(args) > 2 else 1
    except ValueError:
        print("آرگومان‌های عددی نامعتبر.")
        return 2

    # سازگاری با فرم قدیمی: grant <telegram_id> <ماه> <ربات> <کاربر> [امکانات...]
    # اگه آرگومان بعدی هم عددی باشه، «تعداد کاربر» قدیمیه -- نادیده گرفته
    # می‌شه (کاربر مدیر دیگه سهمیه/قیمت نداره).
    feature_args = args[3:]
    legacy_users = bool(feature_args) and feature_args[0].lstrip("-").isdigit()
    if legacy_users:
        feature_args = feature_args[1:]
    features = catalog.expand_features(feature_args) if feature_args else []

    db.upsert_user(user_id)
    order = db.create_order(user_id=user_id, months=months, users=1, bots=bots,
                            features=features, amount_usd=0.0, status="approved")
    db.update_order(int(order["id"]), admin_note="granted via manage.py",
                    decided_at=int(time.time()))
    row = licenses.create_from_order(db, db.get_order(int(order["id"])))
    print(f"لایسنس {row['key']} صادر شد (تا {_fmt_time(row['expires_at'])}).")
    if legacy_users:
        print("(آرگومان قدیمیِ «کاربر» نادیده گرفته شد — کاربر مدیر دیگه قیمت/سهمیه نداره.)")
    print("کاربر باید توی ربات تلگرام «راه‌اندازی ربات» رو بزنه تا نمونه ساخته بشه.")
    return 0


def cmd_extend(args):
    from licensing import licenses, provisioning
    if len(args) < 2:
        print("استفاده: python manage.py extend <کلید> <ماه>")
        return 2
    db, row = _license_from_args(args)
    if row is None:
        return 1
    updated = licenses.renew(db, int(row["id"]), int(args[1]))
    refreshed = provisioning.refresh_license_files(db, updated)
    print(f"{updated['key']} تا {_fmt_time(updated['expires_at'])} تمدید شد.")
    if refreshed:
        print(f"فایل لایسنس این ربات‌ها به‌روز شد: {', '.join(refreshed)}")
        print("برای اعمال فوری، ربات‌ها رو ری‌استارت کن (یا سوپروایزر خودش می‌کنه).")
    return 0


def _license_action(args, action, purge):
    from licensing import licenses, provisioning
    if not args:
        print(f"استفاده: python manage.py {action} <کلید> [دلیل]")
        return 2
    db, row = _license_from_args(args)
    if row is None:
        return 1
    reason = " ".join(args[1:])
    if action == "suspend":
        licenses.suspend(db, int(row["id"]), reason)
    else:
        licenses.revoke(db, int(row["id"]), reason)
    results = provisioning.deactivate_license(db, int(row["id"]), purge_data=purge,
                                              supervisor=None, reason=reason)
    print(f"{row['key']} {'معلق' if action == 'suspend' else 'لغو'} شد.")
    for result in results:
        print(f"  {result['slug']}: لاین حذف={result['line_removed']}  "
              f"دیتا حذف={result['data_removed']}"
              + (f"  خطاها={result['errors']}" if result["errors"] else ""))
    if not purge:
        print("دیتا نگه داشته شد (برای حذف کامل از revoke استفاده کن).")
    print("⚠️ اگه license_server در حال اجراست، پروسه‌های ربات توسط همون بسته می‌شن؛")
    print("   این دستور از بیرون فقط لاین و دیتا رو دست می‌زنه.")
    return 0


def cmd_suspend(args):
    return _license_action(args, "suspend", purge=False)


def cmd_revoke(args):
    return _license_action(args, "revoke", purge=True)


def cmd_sweep(args):
    from licensing import expiry
    db = _db()
    messages = []
    result = expiry.run_sweep(db, supervisor=None,
                              notify=lambda uid, text: messages.append((uid, text)))
    print(result.summary_fa())
    for row in result.expired:
        print(f"  منقضی: {row['key']}")
    for row in result.purged:
        print(f"  پاک شد: {row['key']}")
    for error in result.errors:
        print(f"  خطا: {error}")
    if messages:
        print(f"\n{len(messages)} پیام برای کاربرها آماده شد ولی از اینجا فرستاده نمی‌شه")
        print("(ارسال پیام کار ربات تلگرامه؛ همین جارو موقع اجرای license_server خودکار انجام می‌شه).")
    return 0


def cmd_gc(args):
    """پاکسازی پسماند؛ همون licensing/gc.py که ربات فروش استفاده می‌کنه."""
    from licensing import gc
    from licensing.provisioning import DATA_DIR
    apply_now = "--apply" in args
    options = gc.default_options()
    for i, arg in enumerate(args):
        if arg == "--categories" and i + 1 < len(args):
            options.categories = tuple(c for c in args[i + 1].split(",") if c)
        elif arg == "--retention-days" and i + 1 < len(args):
            if not args[i + 1].isdigit():
                print("--retention-days باید عدد باشه.")
                return 2
            options.retention_days = int(args[i + 1])
    if options.categories and set(options.categories) - set(gc.CATEGORIES):
        print("دسته‌ی ناشناس. مجاز: " + ", ".join(gc.CATEGORIES))
        return 2
    db = _db()
    report = gc.scan(db, DATA_DIR, options=options)
    for cat in gc.CATEGORIES:
        for c in report.items.get(cat, []):
            flag = "" if c.deletable else " (فقط گزارش)"
            print(f"  [{cat}] {c.label}  {gc.fmt_size(c.size)}  {c.reason}{flag}")
    for c in report.attention:
        print(f"  [نیازمند توجه] {c.label}: لایسنس فعال ولی پوشه نیست (پاک نمی‌شه)")
    picked = report.deletable()
    print(f"\n{len(picked)} مورد قابل پاک‌کردن، {gc.fmt_size(report.total_size())}")
    if not apply_now:
        print("(فقط گزارش؛ برای پاک‌کردن --apply بزن)")
        return 0
    if not picked:
        return 0
    if input("برگشت‌ناپذیره. برای ادامه yes تایپ کن: ").strip() != "yes":
        print("لغو شد.")
        return 1
    result = gc.apply(db, DATA_DIR, [c.id for c in picked], options=options)
    print(f"پاک شد: {result['deleted']}  آزاد: {gc.fmt_size(result['freed'])}  خطا: {result['errors']}")
    return 0


# ------------------------------------------------------------- قیمت‌گذاری

def cmd_catalog(args):
    from licensing import catalog, pricing
    config = catalog.pricing()
    print("--- قیمت پایه (دلار، ماهانه) ---")
    print(f"  پایه (۱ ربات، یوتیوب): {config['base_monthly_usd']}")
    print(f"  هر ربات اضافه: {config['extra_bot_usd']}")
    print(f"  سقف: {config['max_bots']} ربات")
    print("  (کاربر مدیر/اپراتور دیگه قیمت یا سهمیه نداره -- فقط سقفِ فنیِ ۵۰ تایی ویزارد)")
    print()
    print("--- ضریب مدت ---")
    for months, multiplier in sorted(config["duration_multipliers"].items(), key=lambda kv: int(kv[0])):
        discount = (int(months) - float(multiplier)) / int(months) * 100 if int(months) else 0
        print(f"  {months} ماه: ×{multiplier}" + (f"  ({discount:.0f}٪ تخفیف)" if discount > 0.5 else ""))
    print()
    print("--- امکانات ---")
    for code, feature in catalog.features().items():
        print(f"  {code}: {feature['title_fa']} — {pricing.format_usd(feature['price_usd'])}/ماه")
        print(f"      سرویس‌ها: {feature['services'] or '—'}")
        print(f"      دستورها: {', '.join(feature['commands']) or '—'}")
    print()
    print("--- بسته‌ها ---")
    for code, bundle in catalog.bundles().items():
        print(f"  {code}: {bundle['title_fa']} — {pricing.format_usd(bundle['price_usd'])}/ماه")
    print()
    print("--- پنل‌ها ---")
    db = _db()
    for panel in catalog.panels():
        quote = pricing.quote(panel["months"], panel["bots"],
                              panel.get("features", []), db=db)
        irr = f" = {pricing.format_irr(quote['total_irr'])} تومان" if quote["total_irr"] else ""
        print(f"  {panel['code']}: {panel['title_fa']} -> "
              f"{pricing.format_usd(quote['total_usd'])}{irr}")
    print()
    print(f"برای تغییر قیمت‌ها این فایل رو ویرایش کن: {catalog.OVERRIDE_FILE}")
    print("(اگه نیست، با «python license_server.py --init» ساخته می‌شه)")
    return 0


def cmd_quote(args):
    from licensing import catalog, pricing
    if len(args) < 2:
        print("استفاده: python manage.py quote <ماه> <ربات> [امکانات...]")
        return 2
    try:
        months = int(args[0])
    except ValueError:
        print("آرگومان‌های عددی نامعتبر.")
        return 2

    # سازگاری با فرم قدیمی: quote <ماه> <کاربر> <ربات> [امکانات...]. کدهای
    # امکان هیچ‌وقت کاملاً عددی نیستن، پس اگه دوتا آرگومان عددیِ پشت‌سرهم
    # بعد از ماه بیاد، دومی «ربات» قدیمیه و اولی (کاربر) نادیده گرفته می‌شه.
    rest = args[1:]
    legacy_users = (len(rest) >= 2 and rest[0].lstrip("-").isdigit()
                    and rest[1].lstrip("-").isdigit())
    if legacy_users:
        rest = rest[1:]

    try:
        bots = int(rest[0]) if rest else 1
    except ValueError:
        print("آرگومان‌های عددی نامعتبر.")
        return 2
    features = rest[1:]

    db = _db()
    quote = pricing.quote(months, bots, features, db=db)
    if legacy_users:
        print("(آرگومان قدیمیِ «کاربر» نادیده گرفته شد — کاربر مدیر دیگه قیمت نداره.)")
    print(f"مدت: {quote['months']} ماه، ربات: {quote['bots']}")
    print(f"امکانات: {', '.join(quote['features']) or '(فقط یوتیوب)'}")
    print()
    for line in quote["lines"]:
        print(f"  {line['title']}: {pricing.format_usd(line['usd'])}")
    print()
    print(f"ماهانه: {pricing.format_usd(quote['monthly_usd'])}")
    print(f"ضریب مدت: ×{quote['duration_multiplier']}")
    print(f"مجموع: {pricing.format_usd(quote['total_usd'])}")
    if quote["total_irr"]:
        print(f"تومان: {pricing.format_irr(quote['total_irr'])} "
              f"(نرخ {pricing.format_irr(quote['usd_rate'])}، منبع {quote['rate_source']}"
              + (", قدیمی" if quote["rate_stale"] else "") + ")")
    else:
        print("تومان: نرخ دلار در دسترس نیست")
    return 0


def cmd_rate(args):
    from licensing import pricing
    db = _db()
    if args:
        if args[0].lower() == "auto":
            db.set_setting("usd_rate_manual", None)
            print("نرخ دستی برداشته شد.")
        else:
            try:
                value = int(float(args[0].replace(",", "")))
            except ValueError:
                print("عدد نامعتبر.")
                return 2
            if not pricing.RATE_SANITY_MIN <= value <= pricing.RATE_SANITY_MAX:
                print(f"خارج از بازه‌ی منطقی "
                      f"({pricing.RATE_SANITY_MIN:,} تا {pricing.RATE_SANITY_MAX:,}).")
                return 2
            db.set_setting("usd_rate_manual", str(value))
            print(f"نرخ دستی روی {value:,} تومان تنظیم شد.")

    state = pricing.current_rate(db)
    if not state["rate"]:
        print("هیچ نرخی در دسترس نیست؛ دارم از اینترنت می‌گیرم...")
        state = pricing.refresh_rate(db)
    print(f"نرخ فعلی: {state['rate'] and format(state['rate'], ',') or '—'} تومان "
          f"(منبع {state['source']}"
          + (", قدیمی" if state["stale"] else "") + ")")
    if state.get("error"):
        print(f"خطای گرفتن نرخ: {state['error']}")
    return 0


def cmd_pubkey(args):
    """کلید عمومی Ed25519 که باید توی core/license_key.py (PUBLIC_KEY_B64) بشینه."""
    from licensing import keys
    try:
        print(keys.public_key_b64())
    except keys.SigningUnavailable as e:
        print(f"نشد: {e}")
        return 1
    return 0


def cmd_worker_key(args):
    """
    کلید خصوصی به فرمتی که Cloudflare Worker می‌خواد (PKCS#8, base64url).

    خروجی این دستور **راز**ه. با `wrangler secret put SIGNING_KEY` بذارش
    و هیچ‌وقت توی wrangler.toml یا گیت ننویسش.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from licensing import keys

    try:
        private = keys.load_private_key()
    except Exception as e:
        print(f"کلید خصوصی خونده نشد: {e}")
        return 1

    der = private.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    print("⚠️  این خروجی راز است. فقط توی wrangler secret بذارش.\n")
    print(base64.urlsafe_b64encode(der).decode("ascii").rstrip("="))
    print("\nدستور:  wrangler secret put SIGNING_KEY")
    return 0


def cmd_rental(args):
    """
    یه لایسنس اجاره‌ای می‌سازه و رکورد آماده‌ی KV رو چاپ می‌کنه.

        python manage.py rental <روز> [--note "برای علی"]

    خودِ لایسنس روی Cloudflare نوشته می‌شه، نه اینجا -- این دستور فقط
    کلید و رکوردش رو تولید می‌کنه تا کپی/پیست کنی (یا ربات فروش خودکار
    آپلودش کنه).
    """
    import json as json_module
    import secrets
    import time as time_module

    days = 30
    if args and str(args[0]).isdigit():
        days = int(args[0])

    note = ""
    if "--note" in args:
        index = args.index("--note")
        if index + 1 < len(args):
            note = args[index + 1]

    # لیست امکانات. بدون این، لایسنس همه‌ی امکانات رو می‌گیره -- که برای
    # اجاره معمولاً درست نیست: اگه طرف فقط مستند خواسته، فقط همون رو بده.
    # یوتیوب همیشه پایه‌ست و لازم نیست اینجا بیاد.
    features = None
    if "--features" in args:
        index = args.index("--features")
        if index + 1 < len(args):
            features = [f.strip() for f in args[index + 1].split(",") if f.strip()]

    if features is not None:
        from licensing import catalog
        unknown = [f for f in features if f not in catalog.features()]
        if unknown:
            print(f"این کدهای امکانات وجود ندارن: {', '.join(unknown)}")
            print(f"موجود: {', '.join(sorted(catalog.features()))}")
            return 2

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # بدون I/O/0/1 که اشتباه خونده می‌شن
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    key = "TT-" + "-".join(groups)

    expires_at = int(time_module.time()) + days * 86400
    record = {
        # خالی یعنی «به اولین دستگاهی که فعالش کنه بایند شو».
        "fingerprint": None,
        "expires_at": expires_at,
        "features": features,      # None = همه‌ی امکانات
        "max_bots": 1,
        "revoked": False,
        "note": note,
    }

    print(f"کلید لایسنس:  {key}")
    print(f"اعتبار:        {days} روز (تا {time_module.strftime('%Y-%m-%d %H:%M', time_module.localtime(expires_at))})")
    if features is None:
        print("امکانات:       همه")
    else:
        from licensing import catalog
        services = catalog.allowed_services(features)
        commands = catalog.allowed_commands(features)
        print(f"امکانات:       {', '.join(features) or '(فقط پایه)'}")
        print(f"سرویس‌ها:      {', '.join(services)}")
        print(f"دستورها:       {len(commands)} تا")
    print()
    print("رکورد KV -- با این دستور آپلودش کن:")
    print(f'  wrangler kv key put --binding=LICENSES "license:{key}" \'{json_module.dumps(record, ensure_ascii=False)}\'')
    print()
    print("برای لغو فوری:")
    print(f'  wrangler kv key delete --binding=LICENSES "license:{key}"')
    return 0


def licence_is_protected(key):
    """
    آیا این کلید دست مشتریه و نباید دستکاری بشه؟

    منطق واقعی توی licensing/config.py هست (is_protected_licence) تا هم
    این CLI هم پنل ادمینِ تلگرام از همون یه تصمیم استفاده کنن. این تابع
    فقط برای سازگاری با فراخوانی‌های قدیمی (و تست‌ها) نگه داشته شده.
    """
    from licensing import config
    return config.is_protected_licence(key)


def cmd_rental_extend(args):
    """
    یه لایسنسِ اجاره‌ای رو `days` روز جلو می‌بره -- بدونِ دست‌زدن به
    fingerprint یا تاریخچه (برخلافِ rental-reset). برای تمدیدِ عادی یا
    عذرخواهی/جبران به یه مشتریِ فعلی -- دستگاهش همون‌جوری که بود می‌مونه.
    روی لایسنسِ محافظت‌شده هم کار می‌کنه (برخلافِ rental-reset)، چون
    چیزی رو ریست/باز نمی‌کنه.

        python manage.py rental-extend <کلید> <روز> [--unrevoke]
    """
    from licensing import cloudflare

    if len(args) < 2:
        print("استفاده: python manage.py rental-extend <کلید> <روز> [--unrevoke]")
        return 2

    unrevoke = "--unrevoke" in args
    args = [a for a in args if a != "--unrevoke"]
    key = args[0].strip().upper()
    try:
        days = int(args[1])
    except ValueError:
        print("تعداد روز باید عدد باشه.")
        return 2
    if days < 1:
        print("تعداد روز باید حداقل ۱ باشه.")
        return 2

    if not cloudflare.available():
        print("کلادفلر تنظیم نیست: " + ", ".join(cloudflare.missing_settings()))
        print("ببین:  python manage.py cf-token")
        return 1

    before = cloudflare.read_licence(key)
    if before is None:
        print(f"لایسنس {key} روی KV نیست.")
        return 1

    was_revoked = bool(before.get("revoked"))
    updated = cloudflare.extend_licence(key, days, unrevoke=unrevoke)
    stamp = _fmt_time(updated["expires_at"])
    print(f"✅ {key}: {days} روز اضافه شد. اعتبار تا {stamp}.")
    if was_revoked:
        print(f"   قبلش لغو شده بود -- {'برداشته شد (--unrevoke)' if unrevoke else 'هنوز لغو است؛ برای برداشتنش --unrevoke بزن'}.")
    print("   fingerprint و تاریخچه‌ی دستگاه دست‌نخورده موند.")
    return 0


def cmd_rental_reset(args):
    """
    یه لایسنس اجاره‌ای رو به حالت دست‌نخورده برمی‌گردونه.

        python manage.py rental-reset <کلید> [روز]

    بعد از تست‌کردن با یه لایسنس لازمه: اولین دستگاهی که چک
    کنه لایسنس رو به خودش **قفل** می‌کنه. پس لایسنسی که روی
    سیستم خودت تست شده، به دستگاه تو بایند شده و مشتری
    پیام «this licence belongs to another machine» می‌گیره.

    این دستور fingerprint رو خالی می‌کنه (دوباره منتظر اولین
    دستگاه)، اعتبار رو تازه می‌کنه، و تاریخچه‌ی دستگاه‌های
    دیده‌شده رو پاک می‌کنه -- وگرنه fingerprint های تستِ خودت
    مثل «اشتراک‌گذاری» به چشم می‌خورن.

    امکانات، max_bots و یادداشت دست‌نخورده می‌مونن.
    """
    import time as time_module

    from licensing import cloudflare

    if not args:
        print("استفاده: python manage.py rental-reset <کلید> [روز]")
        return 2

    force = "--force" in args
    args = [a for a in args if a != "--force"]
    key = args[0].strip().upper()
    days = 30
    if len(args) > 1 and str(args[1]).isdigit():
        days = int(args[1])

    # لایسنسِ فروخته‌شده هیچ‌وقت ریست نمی‌شه -- حتی با --force. ریستیعنی
    # بایندِ دستگاه مشتری پاک می‌شه و رباتِ پولیش می‌خوابه.
    if licence_is_protected(key):
        print(f"⛔ {key} توی protected_licences هست (فروخته‌شده) و بازنشانی نمی‌شه.")
        print("   برای تست یه لایسنس تازه بساز:  python manage.py rental 30")
        return 1
    if days < 1:
        print("تعداد روز باید حداقل ۱ باشه.")
        return 2

    if not cloudflare.available():
        print("کلادفلر تنظیم نیست: " + ", ".join(cloudflare.missing_settings()))
        print("ببین:  python manage.py cf-token")
        return 1

    try:
        result = cloudflare.reset_rental(key, days=days, force=force)
    except cloudflare.RentalResetRefused:
        # بایندشده یعنی یه دستگاه واقعی همین الان صاحبشه -- شاید مشتری.
        print(f"⚠️  {key} به یه دستگاه متصل شده. بازنشانی‌ش اون دستگاه رو از کار می‌ندازه.")
        print("   اگه مطمئنی مالِ تستِ خودته:  --force")
        return 1
    except cloudflare.CloudflareError as e:
        if str(e) == "not_found":
            print(f"لایسنس {key} روی KV نیست.")
        else:
            print(f"خطا: {e}")
        return 1

    stamp = time_module.strftime("%Y-%m-%d %H:%M", time_module.localtime(result["expires_at"]))
    print(f"✅ {key} بازنشانی شد.")
    print(f"   اعتبار: {days} روز (تا {stamp})")
    if result["was_bound"]:
        print("   اتصال به دستگاه برداشته شد — اولین دستگاهی که چک کنه صاحبش می‌شه.")
    print("   تاریخچه‌ی دستگاه‌های دیده‌شده پاک شد.")
    return 0


def cmd_deploy_worker(args):
    """
    کل راه‌اندازی Cloudflare رو انجام می‌ده -- به‌جز خودِ ورود به حساب.

        wrangler login              <- این یکی رو خودت بزن (مرورگر باز می‌شه)
        python manage.py deploy-worker

    کارهایی که می‌کنه: ساخت KV، نوشتن شناسه‌ش توی wrangler.toml، گذاشتن
    کلید امضا به‌عنوان secret، دیپلوی، و برداشتن آدرس نهایی و نشوندنش
    توی core/license_key.py.
    """
    import base64
    import os as os_module
    import re
    import subprocess

    from cryptography.hazmat.primitives import serialization
    from core.paths import get_base_dir
    from licensing import keys

    deploy_dir = os_module.path.join(get_base_dir(), "deploy")
    if not os_module.path.isdir(deploy_dir):
        print(f"پوشه‌ی {deploy_dir} نیست.")
        return 1

    def run(command, **kwargs):
        return subprocess.run(command, cwd=deploy_dir, capture_output=True,
                              text=True, shell=True, **kwargs)

    check = run("wrangler whoami")
    if "not authenticated" in (check.stdout + check.stderr).lower():
        print("اول وارد حساب کلادفلر شو (مرورگر باز می‌شه):")
        print("    wrangler login")
        print("بعد دوباره همین دستور رو بزن.")
        return 1

    # ۱) KV
    print("[1/5] ساخت KV namespace...")
    result = run("wrangler kv namespace create LICENSES")
    output = result.stdout + result.stderr
    match = re.search(r'id\s*=\s*"([0-9a-f]{32})"', output) or \
        re.search(r'"id":\s*"([0-9a-f]{32})"', output)
    if match:
        namespace_id = match.group(1)
        print(f"      ساخته شد: {namespace_id}")
    elif "already" in output.lower():
        listed = run("wrangler kv namespace list")
        found = re.search(r'"id":\s*"([0-9a-f]{32})"[^}]*"title":\s*"[^"]*LICENSES',
                          listed.stdout + listed.stderr)
        if not found:
            print("      KV از قبل هست ولی شناسه‌ش پیدا نشد. دستی از داشبورد بردار.")
            return 1
        namespace_id = found.group(1)
        print(f"      از قبل وجود داشت: {namespace_id}")
    else:
        print("      نشد:")
        print(output[:400])
        return 1

    # ۲) wrangler.toml
    print("[2/5] نوشتن شناسه توی wrangler.toml...")
    toml_path = os_module.path.join(deploy_dir, "wrangler.toml")
    with open(toml_path, "r", encoding="utf-8") as f:
        toml = f.read()
    toml = re.sub(r'id = "[^"]*"', f'id = "{namespace_id}"', toml, count=1)
    with open(toml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(toml)

    # ۳) کلید امضا به‌عنوان secret
    print("[3/5] گذاشتن کلید امضا...")
    private = keys.load_private_key()
    der = private.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    secret = base64.urlsafe_b64encode(der).decode("ascii").rstrip("=")
    result = subprocess.run("wrangler secret put SIGNING_KEY", cwd=deploy_dir,
                            input=secret, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print("      نشد:")
        print((result.stdout + result.stderr)[:400])
        return 1

    # ۴) دیپلوی
    #
    # wrangler اگه حساب هنوز ساب‌دامین workers.dev نداشته باشه، وسط دیپلوی
    # یه سؤال تعاملی می‌پرسه. توی این اسکریپت (که ورودی تعاملی نداره) اون
    # سؤال بی‌جواب می‌مونه و دیپلوی نصفه‌کاره تموم می‌شه. پس صراحتاً
    # تشخیصش می‌دیم و یه دستور دقیق می‌دیم، به‌جای یه خطای گنگ.
    print("[4/5] دیپلوی...")
    result = run("wrangler deploy")
    output = result.stdout + result.stderr

    url_match = re.search(r"https://[^\s]+\.workers\.dev", output)
    if not url_match:
        needs_subdomain = ("subdomain" in output.lower()
                           or "workers.dev" not in output.lower())
        print()
        if needs_subdomain:
            print("      ⚠️  حساب کلادفلرت هنوز ساب‌دامین workers.dev نداره.")
            print("      این یه انتخاب یک‌باره‌ست و اسمش توی آدرس عمومیت میاد،")
            print("      پس باید خودت انتخابش کنی. یکی از این دو راه:")
            print()
            print("        cd deploy && wrangler deploy")
            print("        (به سؤال «register a workers.dev subdomain» جواب y بده)")
            print()
            print("      یا از داشبورد: Workers & Pages -> Subdomain")
            print()
            print("      بعدش همین دستور رو دوباره بزن؛ از همین‌جا ادامه می‌ده.")
        else:
            print("      دیپلوی شد ولی آدرسش پیدا نشد:")
            print(output[-500:])
        return 1

    worker_url = url_match.group(0).rstrip("/") + "/check"
    print(f"      آدرس: {worker_url}")

    # ۵) نشوندن آدرس توی کد کلاینت
    print("[5/5] نوشتن آدرس توی core/license_key.py...")
    key_path = os_module.path.join(get_base_dir(), "core", "license_key.py")
    with open(key_path, "r", encoding="utf-8") as f:
        source = f.read()
    source = re.sub(r'LICENSE_API_URL = "[^"]*"',
                    f'LICENSE_API_URL = "{worker_url}"', source, count=1)
    with open(key_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(source)

    print()
    print("✅ تموم شد. حالا:")
    print("    python manage.py build-check     <- باید ✅ بده")
    print("    python manage.py rental 30 --features cap_documentary")
    return 0


def cmd_cf_token(args):
    """
    توکن API کلادفلر رو ذخیره و **همون‌جا تست** می‌کنه.

        python manage.py cf-token <توکن>

    بدون آرگومان، فقط وضعیت فعلی رو می‌گه.

    چرا دستی: توکن OAuth رنگلر اجازه‌ی ساخت توکن API نداره (۴۰۳)، پس
    این یه قدم یک‌باره‌ست که فقط از داشبورد انجام می‌شه.
    """
    import os as os_module

    from licensing import cloudflare, config

    if not args:
        account, namespace, token = cloudflare.settings()
        print(f"account_id : {account or '—'}")
        print(f"namespace  : {namespace or '—'}")
        print(f"api_token  : {'تنظیم شده' if token else '—'}")
        print()
        ok, detail = cloudflare.check_connection()
        print(("✅ " if ok else "❌ ") + detail)
        if not ok and not token:
            print()
            print("ساختن توکن (یک‌بار):")
            print("  ۱. dash.cloudflare.com → My Profile → API Tokens")
            print("  ۲. Create Token → Create Custom Token")
            print("  ۳. دسترسی: Account → Workers KV Storage → Edit")
            print("  ۴. Account Resources: همون حسابی که Worker روشه")
            print()
            print("  بعد:  python manage.py cf-token <توکن>")
        return 0 if ok else 1

    token = args[0].strip()
    if len(token) < 20:
        print("این به توکن نمی‌خوره.")
        return 2

    # اول تست، بعد ذخیره. توکنِ غلطِ ذخیره‌شده کانفیگ رو توی حالت
    # «تنظیم‌شده ولی خراب» می‌ذاره که از «تنظیم‌نشده» بدتره: ربات فروش
    # فکر می‌کنه صدور روشنه و سرِ اولین لایسنس مشتری خطا می‌خوره.
    #
    # _setting اول محیط رو می‌خونه، پس بدون دست‌زدن به کانفیگ
    # می‌شه تستش کرد.
    previous = os_module.environ.get("CF_API_TOKEN")
    os_module.environ["CF_API_TOKEN"] = token
    try:
        ok, detail = cloudflare.check_connection()
    finally:
        if previous is None:
            os_module.environ.pop("CF_API_TOKEN", None)
        else:
            os_module.environ["CF_API_TOKEN"] = previous

    if not ok:
        print("❌ " + detail)
        print("توکن ذخیره نشد — کانفیگ دست‌نخورده موند.")
        return 1

    # نوشتن از همون نویسنده‌ی مشترکِ کانفیگ (اتمیک، chmod 600، و فایلِ
    # خراب رو بازنویسی نمی‌کنه).
    try:
        config.save_values({"cloudflare_api_token": token})
    except config.ConfigWriteError as e:
        print("❌ " + str(e))
        return 1

    config.reload()
    print("✅ " + detail)
    print("حالا ربات فروش می‌تونه لایسنس اجاره‌ای صادر و لغو کنه.")
    return 0


def cmd_error_keys(args):
    """
    جفت‌کلید رمزنگاری لاگ خطا می‌سازه.

        python manage.py error-keys

    کلید *عمومی* رو توی core/error_crypt.py می‌ذاری (می‌ره داخل بیلد
    مشتری)، کلید *خصوصی* رو فقط پیش خودت نگه می‌داری.
    """
    import os as os_module

    from core import error_crypt
    from core.paths import get_base_dir

    try:
        private_b64, public_b64 = error_crypt.generate_keypair()
    except Exception as e:
        print(f"ساخت کلید نشد ({e}).")
        print("PyNaCl لازمه:  pip install PyNaCl")
        return 1

    key_dir = os_module.path.join(get_base_dir(), "data", "licensing", "keys")
    os_module.makedirs(key_dir, exist_ok=True)
    private_path = os_module.path.join(key_dir, "errors_private.key")

    if os_module.path.isfile(private_path):
        print(f"⚠️  {private_path} از قبل هست.")
        print("   عوض‌کردنش یعنی لاگ‌های قدیمی دیگه باز نمی‌شن.")
        print("   اگه مطمئنی، اول دستی پاکش کن.")
        return 1

    with open(private_path, "w", encoding="ascii") as f:
        f.write(private_b64)
    try:
        os_module.chmod(private_path, 0o600)
    except OSError:
        pass

    print(f"کلید خصوصی ذخیره شد: {private_path}")
    print("  ⚠️  این فایل هیچ‌وقت نباید توی بیلد مشتری بره.")
    print()
    print("کلید عمومی — این رو توی core/error_crypt.py بذار:")
    print()
    print(f'    PUBLIC_KEY_B64 = "{public_b64}"')
    return 0


def cmd_read_errors(args):
    """
    لاگ خطای رمزشده‌ی مشتری رو باز می‌کنه.

        python manage.py read-errors <فایل> [خروجی]

    خط‌های خام (از بیلدهای توسعه) همون‌طور رد می‌شن، پس یه فایل
    نیمه‌رمز هم کامل خونده می‌شه.
    """
    import os as os_module

    from core import error_crypt
    from core.paths import get_base_dir

    if not args:
        print("استفاده: python manage.py read-errors <فایل> [خروجی]")
        return 2

    source = args[0]
    if not os_module.path.isfile(source):
        print(f"فایل {source} نیست.")
        return 1

    private_path = os_module.path.join(get_base_dir(), "data", "licensing",
                                       "keys", "errors_private.key")
    try:
        with open(private_path, "r", encoding="ascii") as f:
            private_b64 = f.read().strip()
    except OSError:
        print(f"کلید خصوصی پیدا نشد: {private_path}")
        print("اول بساز:  python manage.py error-keys")
        return 1

    with open(source, "r", encoding="utf-8", errors="replace") as f:
        raw_text = f.read()
    # حلقه‌ی «خط به خط رمزگشایی کن» توی core/error_crypt.py هست، همونی که
    # دکمه‌ی ادمینِ تلگرام هم صدا می‌زنه -- یه رکورد خراب جلوی بقیه رو نمی‌گیره.
    output_text, decrypted, plain, failed = error_crypt.decrypt_log_text(raw_text, private_b64)

    destination = args[1] if len(args) > 1 else None
    if destination:
        with open(destination, "w", encoding="utf-8") as f:
            f.write(output_text + ("\n" if output_text else ""))
    elif output_text:
        print(output_text)

    summary = f"\n{decrypted} رکورد رمزگشایی شد"
    if plain:
        summary += f"، {plain} خط خام"
    if failed:
        summary += f"، {failed} رکورد خراب"
    print(summary)
    if destination:
        print(f"نوشته شد: {destination}")
    return 0


def cmd_build_check(args):
    """
    قبل از تحویل بیلد به مشتری، بررسی کن قفل‌ها واقعاً بسته‌ان.

    این دستور عمداً بدبینانه‌ست: هر چیزی که *ممکنه* راه فرار باشه رو
    گزارش می‌ده، حتی اگه توی این نصب خاص بی‌ضرر باشه.
    """
    import os as os_module

    from core import error_crypt, license_key
    from core.paths import get_base_dir

    problems = []
    notes = []

    if not license_key.embedded_public_key():
        problems.append("کلید عمومی داخل core/license_key.py خالیه — "
                        "هر لایسنس جعلی‌ای پذیرفته می‌شه.")
    else:
        notes.append("کلید عمومی داخل کد: ✅")

    if not license_key.embedded_api_url():
        problems.append("LICENSE_API_URL هنوز مقدار نمونه‌ست — "
                        "بیلد به هیچ سرویسی وصل نمی‌شه و همه‌چیز رد می‌شه.")
    else:
        notes.append(f"آدرس سرویس: {license_key.embedded_api_url()}")

    # لاگ خطای خام روی سیستم مشتری یعنی مسیرهای داخلی و اسم سرویس‌ها
    # لو می‌ره. بدتر از اون: کلید تنظیم‌شده ولی PyNaCl نصب‌نشده — اون‌وقت
    # بیلد بی‌صدا خام می‌نویسه درحالی‌که فکر می‌کنی رمز شده.
    if not (error_crypt.PUBLIC_KEY_B64 or "").strip():
        problems.append("کلید رمزنگاری لاگ خطا توی core/error_crypt.py خالیه — "
                        "لاگ مشتری خام نوشته می‌شه. بساز با:  "
                        "python manage.py error-keys")
    else:
        try:
            import nacl.public  # noqa: F401
            notes.append(f"رمزنگاری لاگ خطا: {error_crypt.describe()}")
        except Exception as e:
            # فقط نبودن نیست: libsodium خراب هم همین‌جا می‌افته، و باید
            # گزارش بشه نه اینکه build-check رو بندازه.
            problems.append("کلید رمزنگاری لاگ خطا هست ولی PyNaCl بالا نمیاد "
                            f"({e}) — بیلد بی‌صدا لاگ خام می‌نویسه.  "
                            "pip install PyNaCl")

    # فایل کلید عمومیِ کنار برنامه دیگه خونده نمی‌شه، ولی وجودش گمراه‌کننده‌ست.
    stray = os_module.path.join(get_base_dir(), "license_public.key")
    if os_module.path.isfile(stray):
        notes.append(f"هشدار: {stray} هنوز هست. الان نادیده گرفته می‌شه، "
                     "ولی بهتره از بسته‌ی مشتری حذفش کنی.")

    # کلید خصوصی هیچ‌وقت نباید توی بسته‌ی مشتری باشه.
    private = os_module.path.join(get_base_dir(), "data", "licensing", "keys", "private.key")
    if os_module.path.isfile(private):
        notes.append(f"یادآوری: {private} کلید امضاته. "
                     "مطمئن شو توی بیلدی که می‌فرستی نیست.")

    for note in notes:
        print(f"  {note}")
    print()
    if problems:
        print(f"❌ {len(problems)} مشکل — این بیلد آماده‌ی تحویل نیست:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("✅ بیلد قفل‌شده‌ست و آماده‌ی تحویل.")
    return 0


def cmd_doctor(args):
    import license_server
    return license_server.cmd_check()


def cmd_self_license(args):
    """
    لایسنس دائمیِ مالک.

    چرا این لازمه: از وقتی اجرا بدون لایسنس ممنوع شد، خودِ مالک هم برای
    توسعه و تست به یه لایسنس نیاز داره. راهش یه استثنا توی کد *نیست* --
    چون هر استثنایی که ما بتونیم استفاده کنیم، یکی دیگه هم می‌تونه پیداش
    کنه. در عوض یه لایسنس واقعی صادر می‌شه که از همون مسیر همیشگی عبور
    می‌کنه.

    اگه bot_dir داده بشه، license.json هم همون‌جا نوشته می‌شه تا ربات
    بلافاصله قابل اجرا باشه.
    """
    from licensing import catalog, licenses

    if not args:
        print("استفاده: python manage.py self-license <telegram_id> [مسیر پوشه‌ی ربات]")
        print("مثال:   python manage.py self-license 123456789 data/127.0.0.1_10333/bot1")
        return 2

    try:
        owner_id = int(args[0])
    except ValueError:
        print("آیدی تلگرام باید عدد باشه.")
        return 2

    db = _db()
    db.upsert_user(owner_id, first_name="owner")

    # ۱۰۰ سال = عملاً دائمی، ولی همون مسیر انقضای همیشگی رو طی می‌کنه و
    # هیچ حالت ویژه‌ای توی کد لازم نداره.
    months = 12 * 100
    pricing_cfg = catalog.pricing()
    features = list(catalog.features())

    existing = [row for row in db.licenses_by_user(owner_id)
                if (row["notes"] or "").startswith("owner")]
    if existing:
        row = licenses.renew(db, int(existing[0]["id"]), months,
                             extra_features=features,
                             max_bots=int(pricing_cfg.get("max_bots", 10)))
        print(f"لایسنس مالک تمدید شد: {row['key']}")
    else:
        order = db.create_order(
            user_id=owner_id, months=months,
            # users=1: ستونِ قدیمیه، کاربر مدیر دیگه سهمیه/قیمت نداره.
            users=1,
            bots=int(pricing_cfg.get("max_bots", 10)),
            features=features, amount_usd=0.0, status="approved")
        db.update_order(int(order["id"]), admin_note="owner self-licence")
        row = licenses.create_from_order(db, db.get_order(int(order["id"])))
        db.update_license(int(row["id"]), notes="owner self-licence")
        row = db.get_license(int(row["id"]))
        print(f"لایسنس مالک صادر شد: {row['key']}")

    print(f"  اعتبار تا: {_fmt_time(row['expires_at'])}")
    print(f"  سهمیه: {row['max_bots']} ربات (کاربر مدیر بدون محدودیت)")
    print(f"  امکانات: همه ({len(features)} تا)")

    if len(args) > 1:
        import os
        bot_dir = args[1]
        if not os.path.isdir(bot_dir):
            print(f"\nپوشه‌ی '{bot_dir}' وجود نداره؛ license.json نوشته نشد.")
            return 1
        path = licenses.write_license_file(bot_dir, row)
        print(f"\nlicense.json نوشته شد: {path}")
        print("حالا ربات از همون پوشه قابل اجراست.")
    else:
        print("\nبرای نوشتن license.json کنار یه ربات، مسیر پوشه‌ش رو هم بده:")
        print(f"  python manage.py self-license {owner_id} data/<host>_<port>/<bot>")
    return 0


def cmd_promos(args):
    from licensing import promos
    db = _db()
    rows = db.list_promos()
    if not rows:
        print("هیچ کدی ساخته نشده.")
        print("مثال ساخت: python manage.py promo-add norooz free_trial 1 13")
        return 0
    for row in rows:
        print(promos.summary_line(row))
    return 0


def cmd_promo_add(args):
    """
    promo-add <کد> <نوع> <مقدار> <روز اعتبار> [per_user=1] [period=ever]
              [total=0] [bots=1] [features=a,b,c]
    """
    from licensing import catalog, promos
    if len(args) < 4:
        print("استفاده: python manage.py promo-add <کد> <نوع> <مقدار> <روز اعتبار> [گزینه‌ها]")
        print()
        print("نوع‌ها:")
        print("  free_trial   ربات رایگان برای <مقدار> ساعت")
        print("  bonus_time   <مقدار> ساعت به لایسنس فعال اضافه کن")
        print("  percent_off  <مقدار> درصد تخفیف")
        print("  amount_off   <مقدار> دلار تخفیف")
        print()
        print("گزینه‌ها (key=value):")
        print("  per_user=1        هر نفر چند بار")
        print("  period=ever       بازه‌ی شمارش: ever | day | week | month")
        print("  total=0           سقف کل استفاده (۰ = بی‌نهایت)")
        print("  bots=1            سهمیه‌ی لایسنسِ آزمایشی")
        print("  features=svc_tiktok,cap_download   (خالی = همه)")
        print()
        print("مثال دقیقِ «نوروز» (۱ ساعت رایگان، ۱۳ روز، هر نفر یک بار):")
        print("  python manage.py promo-add norooz free_trial 1 13")
        print("همون ولی هر روز یک بار:")
        print("  python manage.py promo-add norooz free_trial 1 13 period=day")
        print(f"امکانات موجود: {', '.join(catalog.features())}")
        return 2

    options = {}
    for item in args[4:]:
        if "=" in item:
            key, value = item.split("=", 1)
            options[key.strip()] = value.strip()

    features = [f.strip() for f in options.get("features", "").split(",") if f.strip()]
    try:
        promo = promos.create(
            _db(), args[0], args[1], args[2], args[3],
            features=features,
            # options.get("users", ...) عمداً خونده نمی‌شه -- یه users=
            # قدیمی فقط بی‌صدا نادیده گرفته می‌شه.
            max_bots=int(options.get("bots", 1)),
            per_user_limit=int(options.get("per_user", 1)),
            per_user_period=options.get("period", "ever"),
            total_limit=int(options.get("total", 0)),
            note=options.get("note"),
        )
    except promos.PromoError as e:
        print(f"نشد: {e}")
        return 1
    except ValueError as e:
        print(f"مقدار نامعتبر: {e}")
        return 2

    print("کد ساخته شد:")
    print(promos.summary_line(promo))
    return 0


def cmd_promo_off(args):
    from licensing import promos
    if not args:
        print("استفاده: python manage.py promo-off <کد>")
        return 2
    try:
        promo = promos.deactivate(_db(), args[0])
    except promos.PromoError as e:
        print(f"نشد: {e}")
        return 1
    print(f"کد «{promo['code']}» غیرفعال شد (تاریخچه‌ی استفاده‌ش می‌مونه).")
    return 0


def cmd_gift(args):
    from licensing import promos
    if len(args) < 2:
        print("استفاده: python manage.py gift <telegram_id> <ساعت> [features=a,b]")
        print("مثال:   python manage.py gift 123456789 30")
        return 2
    options = {}
    for item in args[2:]:
        if "=" in item:
            key, value = item.split("=", 1)
            options[key.strip()] = value.strip()
    features = [f.strip() for f in options.get("features", "").split(",") if f.strip()]
    try:
        row, mode = promos.grant_hours(_db(), int(args[0]), float(args[1]), features=features)
    except (promos.PromoError, ValueError) as e:
        print(f"نشد: {e}")
        return 1
    verb = "تمدید شد" if mode == "extended" else "ساخته شد"
    print(f"لایسنس {row['key']} {verb} — تا {_fmt_time(row['expires_at'])}")
    print("(کاربر رو خودت خبر کن، یا از ربات تلگرام با /gift همین کار رو بکن تا پیام هم بره.)")
    return 0


def cmd_selftest(args):
    """
    همون تستی که ربات موقع استارت اجرا می‌کنه، ولی بدون اتصال به تیم‌تاک.

    اینجا player و tt پاس داده نمی‌شن، پس تُن تست پخش نمی‌شه و دستگاه ورودی
    initialize نمی‌شه -- چون باز کردن دستگاه‌ها از بیرون می‌تونه با ربات در
    حال اجرا تعارض پیدا کنه. برای تست کامل صدا، توی خود تیم‌تاک «dg» رو بزن.
    """
    from core import bot_context, command_manager, manager, selftest

    bot = bot_context.bot
    if bot.cfg is None:
        # بدون کانفیگ ربات، چک‌های وابسته به کانفیگ رد می‌شن؛ بقیه کار می‌کنن.
        bot.cfg = {}

    # سرویس‌ها و دستورها رو خودمون لود می‌کنیم: بیرون از پروسه‌ی ربات این‌ها
    # خالی‌ان و بدون این، تست بی‌دلیل «هیچ سرویسی لود نشد» گزارش می‌کرد.
    if not bot.services:
        bot.services = manager.ServiceManager().load_services()
    if not bot.commands:
        bot.commands = command_manager.CommandManager().load_commands()

    show_all = not args or args[0] not in ("problems", "short")
    report = selftest.run(bot=bot, player=None, tt=None, play_tone=False)
    selftest.print_report(report, only_problems=not show_all)
    return 0 if report.ok() else 1


_COMMANDS = {
    "devices": cmd_devices,
    "lines": cmd_lines,
    "line-add": cmd_line_add,
    "line-del": cmd_line_del,
    "line-ensure": cmd_line_ensure,
    "licenses": cmd_licenses,
    "license": cmd_license,
    "instances": cmd_instances,
    "grant": cmd_grant,
    "extend": cmd_extend,
    "suspend": cmd_suspend,
    "revoke": cmd_revoke,
    "sweep": cmd_sweep,
    "gc": cmd_gc,
    "catalog": cmd_catalog,
    "quote": cmd_quote,
    "rate": cmd_rate,
    "pubkey": cmd_pubkey,
    "worker-key": cmd_worker_key,
    "build-check": cmd_build_check,
    "cf-token": cmd_cf_token,
    "error-keys": cmd_error_keys,
    "read-errors": cmd_read_errors,
    "deploy-worker": cmd_deploy_worker,
    "rental": cmd_rental,
    "rental-extend": cmd_rental_extend,
    "rental-reset": cmd_rental_reset,
    "doctor": cmd_doctor,
    "selftest": cmd_selftest,
    "self-license": cmd_self_license,
    "promos": cmd_promos,
    "promo-add": cmd_promo_add,
    "promo-off": cmd_promo_off,
    "gift": cmd_gift,
}


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    handler = _COMMANDS.get(argv[0])
    if handler is None:
        print(f"دستور ناشناس: {argv[0]}")
        print("برای لیست دستورها: python manage.py --help")
        return 2
    return handler(argv[1:]) or 0


if __name__ == "__main__":
    sys.exit(main())
