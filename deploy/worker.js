/**
 * سرویس بررسی لایسنس -- Cloudflare Worker (پلن رایگان کافیه).
 *
 * ## کاری که می‌کنه
 *
 *   POST /check   {key, fingerprint, machine}
 *     -> 200 {payload, signature}   لایسنس معتبره
 *     -> 403                        نیست / لغو شده / مال این دستگاه نیست
 *
 * payload با کلید خصوصی Ed25519 امضا می‌شه و کلاینت با کلید عمومیِ
 * داخل کدش راستی‌آزمایی می‌کنه. یعنی حتی اگه کسی جای این Worker یه
 * سرور جعلی بذاره، جوابش رد می‌شه.
 *
 * ## چرا Worker و نه یه فایل ساکن
 *
 * چون اینجا *منطق* داریم:
 *
 *   - لغو فوری (یه مقدار توی KV عوض می‌شه، تمام)
 *   - دیدنِ اشتراک‌گذاری: هر fingerprint جدید برای یه کلید ثبت می‌شه، پس
 *     می‌فهمی یه لایسنس داره روی چند دستگاه می‌چرخه
 *   - محدودیت نرخ، بدون این‌که چیزی روی کلاینت لازم باشه
 *
 * ## راه‌اندازی
 *
 *   1. npm i -g wrangler && wrangler login
 *   2. wrangler kv namespace create LICENSES
 *      (شناسه‌ای که می‌ده رو توی wrangler.toml بذار)
 *   3. wrangler secret put SIGNING_KEY
 *      (خروجی «python manage.py license-keys --worker» رو پیست کن)
 *   4. wrangler deploy
 *   5. آدرسی که می‌ده رو توی core/license_key.py -> LICENSE_API_URL بذار
 *
 * ## شکل رکورد توی KV
 *
 *   کلید:   license:TT-XXXX-XXXX-XXXX
 *   مقدار:  {"fingerprint":"...","expires_at":1760000000,
 *            "features":["svc_youtube"],"revoked":false,"note":"..."}
 */

const encoder = new TextEncoder();

function b64url(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(text) {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

async function signingKey(secret) {
  // کلید خصوصی خام Ed25519 (۳۲ بایت) به base64url.
  return crypto.subtle.importKey(
    "pkcs8", b64urlDecode(secret), { name: "Ed25519" }, false, ["sign"],
  );
}

/**
 * ثبت این‌که یه کلید از چه دستگاه‌هایی چک شده.
 *
 * برای لغو نیست، برای *دیدن* است: اگه یه لایسنس از پنج تا fingerprint
 * مختلف چک بشه، یعنی داره پخش می‌شه. تصمیمش با آدمه، نه با کد -- پس
 * اینجا فقط ثبت می‌شه و چیزی مسدود نمی‌شه.
 */
async function recordSeen(env, key, fingerprint, machine) {
  const id = `seen:${key}`;
  let seen = {};
  try {
    seen = (await env.LICENSES.get(id, "json")) || {};
  } catch (err) {
    seen = {};
  }
  const entry = seen[fingerprint] || { first: Date.now(), machine };
  entry.last = Date.now();
  entry.count = (entry.count || 0) + 1;
  seen[fingerprint] = entry;
  // بی‌صدا شکست بخوره بهتر از اینه که بررسی لایسنس رو بخوابونه.
  try {
    await env.LICENSES.put(id, JSON.stringify(seen));
  } catch (err) {
    /* ignore */
  }
}

function deny(reason) {
  return new Response(JSON.stringify({ ok: false, error: reason }), {
    status: 403,
    headers: { "Content-Type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("license service", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch (err) {
      return deny("bad request");
    }

    const key = String(body.key || "").trim().toUpperCase();
    const fingerprint = String(body.fingerprint || "").trim();
    const machine = String(body.machine || "").slice(0, 64);

    if (!key || !fingerprint) return deny("missing fields");

    const record = await env.LICENSES.get(`license:${key}`, "json");
    if (!record) return deny("unknown license");
    if (record.revoked) return deny("revoked");

    const now = Math.floor(Date.now() / 1000);
    if (record.expires_at && now > record.expires_at) return deny("expired");

    // اولین بررسی، این دستگاه رو قفل می‌کنه. یعنی لازم نیست fingerprint
    // رو از قبل بدونی -- لایسنس رو صادر می‌کنی و به اولین دستگاهی که
    // فعالش کنه بایند می‌شه.
    if (!record.fingerprint) {
      record.fingerprint = fingerprint;
      await env.LICENSES.put(`license:${key}`, JSON.stringify(record));
    } else if (record.fingerprint !== fingerprint) {
      await recordSeen(env, key, fingerprint, machine);
      return deny("this licence belongs to another machine");
    }

    await recordSeen(env, key, fingerprint, machine);

    const payload = {
      key,
      fingerprint,
      expires_at: record.expires_at || null,
      features: record.features || null,
      max_bots: record.max_bots || 1,
      revoked: false,
      issued_at: now,
    };

    const payloadBytes = encoder.encode(JSON.stringify(payload));
    const signature = await crypto.subtle.sign(
      "Ed25519", await signingKey(env.SIGNING_KEY), payloadBytes,
    );

    return new Response(
      JSON.stringify({ payload: b64url(payloadBytes), signature: b64url(signature) }),
      { headers: { "Content-Type": "application/json" } },
    );
  },
};
