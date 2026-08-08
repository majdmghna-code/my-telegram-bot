import os
import secrets as secrets_lib
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, request, redirect, url_for, session, render_template_string

DB_PATH = "students.db"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "SvoFrXYXkflQ")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or secrets_lib.token_hex(16)

app = Flask(__name__)
app.secret_key = SECRET_KEY

BASE_CSS = """
<style>
  body { font-family: Tahoma, Arial, sans-serif; direction: rtl; background:#f4f6f8; margin:0; padding:24px; color:#222; }
  .card { background:#fff; border-radius:10px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
  h1 { font-size:20px; } h2 { font-size:17px; margin-top:0; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { padding:8px; border-bottom:1px solid #eee; text-align:right; }
  .badge-active { color:#0a7d32; font-weight:bold; }
  .badge-expired { color:#c0392b; font-weight:bold; }
  input[type=text], input[type=number], input[type=password] {
    padding:6px 8px; border:1px solid #ccc; border-radius:6px; font-size:14px;
  }
  button { padding:6px 14px; border:none; border-radius:6px; background:#2563eb; color:#fff; cursor:pointer; font-size:13px; }
  button.danger { background:#c0392b; }
  form.inline { display:inline-flex; gap:6px; align-items:center; }
  .top-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }
  a.logout { color:#c0392b; text-decoration:none; font-size:13px; }
</style>
"""

LOGIN_HTML = BASE_CSS + """
<div class="card" style="max-width:340px; margin:60px auto;">
  <h1>تسجيل دخول لوحة التحكم</h1>
  {% if error %}<p style="color:#c0392b;">{{ error }}</p>{% endif %}
  <form method="post">
    <input type="password" name="password" placeholder="كلمة السر" style="width:100%; box-sizing:border-box; margin-bottom:10px;">
    <button type="submit" style="width:100%;">دخول</button>
  </form>
</div>
"""

DASHBOARD_HTML = BASE_CSS + """
<div class="top-bar">
  <h1>لوحة تحكم بوت الدروس</h1>
  <a class="logout" href="{{ url_for('logout') }}">تسجيل خروج</a>
</div>

<div class="card">
  <h2>أسعار الاشتراك</h2>
  <form method="post" action="{{ url_for('update_prices') }}" class="inline">
    شهر: <input type="text" name="price_month" value="{{ prices['شهر'] }}" style="width:110px;">
    6 أشهر: <input type="text" name="price_6months" value="{{ prices['6 أشهر'] }}" style="width:110px;">
    سنة: <input type="text" name="price_year" value="{{ prices['سنة'] }}" style="width:110px;">
    <button type="submit">حفظ الأسعار</button>
  </form>
</div>

<div class="card">
  <h2>توليد كود اشتراك جديد</h2>
  <form method="post" action="{{ url_for('generate_code') }}" class="inline">
    عدد الأيام: <input type="number" name="days" value="30" style="width:80px;">
    <button type="submit">توليد كود</button>
  </form>
  {% if new_code %}
    <p style="margin-top:10px;">الكود الجديد: <b>{{ new_code }}</b> ({{ new_code_days }} يوم)</p>
  {% endif %}
</div>

<div class="card">
  <h2>الطلاب ({{ students|length }})</h2>
  <table>
    <tr><th>آيدي</th><th>الصف</th><th>المادة</th><th>الحالة</th><th>الأيام المتبقية</th><th>ينتهي بتاريخ</th><th>تعديل</th></tr>
    {% for s in students %}
    <tr>
      <td>{{ s.chat_id }}</td>
      <td>{{ s.grade }}</td>
      <td>{{ s.subject }}</td>
      <td>{% if s.active %}<span class="badge-active">فعّال</span>{% else %}<span class="badge-expired">منتهي</span>{% endif %}</td>
      <td>{{ s.days_left }}</td>
      <td>{{ s.end_date }}</td>
      <td>
        <form method="post" action="{{ url_for('extend', chat_id=s.chat_id) }}" class="inline">
          <input type="number" name="days" value="30" style="width:60px;">
          <button type="submit">تمديد</button>
        </form>
        <form method="post" action="{{ url_for('revoke', chat_id=s.chat_id) }}" class="inline" onsubmit="return confirm('متأكد بدك توقف اشتراك هالطالب؟');">
          <button type="submit" class="danger">إيقاف</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h2>آخر الأكواد</h2>
  <table>
    <tr><th>الكود</th><th>المدة (يوم)</th><th>استُخدم من</th><th>تاريخ الإنشاء</th></tr>
    {% for c in codes %}
    <tr>
      <td>{{ c[0] }}</td>
      <td>{{ c[1] }}</td>
      <td>{{ c[2] if c[2] else '— غير مستخدم —' }}</td>
      <td>{{ c[3][:19] }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
"""


def get_db():
    return sqlite3.connect(DB_PATH)


def init_settings_table():
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


@app.before_request
def check_auth():
    if request.endpoint == "login" or request.endpoint is None:
        return
    if not session.get("logged_in"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "كلمة سر غلط"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def dashboard():
    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id, grade, subject, subscription_end FROM students "
        "ORDER BY subscription_end DESC"
    ).fetchall()
    codes = conn.execute(
        "SELECT code, duration_days, used_by, created_at FROM codes "
        "ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()

    now = datetime.utcnow()
    students = []
    for chat_id, grade, subject, sub_end in rows:
        end_dt = datetime.fromisoformat(sub_end) if sub_end else None
        active = end_dt is not None and end_dt >= now
        students.append(
            dict(
                chat_id=chat_id,
                grade=grade or "-",
                subject=subject or "-",
                active=active,
                days_left=(end_dt - now).days if active else 0,
                end_date=end_dt.date().isoformat() if end_dt else "-",
            )
        )

    prices = {
        "شهر": get_setting("price_month", "غير محدد بعد"),
        "6 أشهر": get_setting("price_6months", "غير محدد بعد"),
        "سنة": get_setting("price_year", "غير محدد بعد"),
    }
    return render_template_string(
        DASHBOARD_HTML, students=students, codes=codes, prices=prices,
        new_code=None, new_code_days=None,
    )


@app.route("/update_prices", methods=["POST"])
def update_prices():
    set_setting("price_month", request.form.get("price_month", ""))
    set_setting("price_6months", request.form.get("price_6months", ""))
    set_setting("price_year", request.form.get("price_year", ""))
    return redirect(url_for("dashboard"))


@app.route("/extend/<int:chat_id>", methods=["POST"])
def extend(chat_id):
    days = int(request.form.get("days", 0) or 0)
    conn = get_db()
    row = conn.execute(
        "SELECT subscription_end FROM students WHERE chat_id=?", (chat_id,)
    ).fetchone()
    now = datetime.utcnow()
    current_end = datetime.fromisoformat(row[0]) if row and row[0] else now
    new_end = max(current_end, now) + timedelta(days=days)
    conn.execute(
        "UPDATE students SET subscription_end=? WHERE chat_id=?",
        (new_end.isoformat(), chat_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/revoke/<int:chat_id>", methods=["POST"])
def revoke(chat_id):
    conn = get_db()
    conn.execute(
        "UPDATE students SET subscription_end=? WHERE chat_id=?",
        (datetime.utcnow().isoformat(), chat_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/generate_code", methods=["POST"])
def generate_code():
    days = int(request.form.get("days", 30) or 30)
    code = "-".join(secrets_lib.token_hex(2).upper() for _ in range(3))
    conn = get_db()
    conn.execute(
        "INSERT INTO codes (code, duration_days, used_by, created_at) VALUES (?, ?, NULL, ?)",
        (code, days, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


def run_dashboard():
    init_settings_table()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
