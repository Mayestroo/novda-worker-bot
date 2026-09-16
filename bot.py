#!/usr/bin/env python3
"""
Novda Hisob-Kitob — Ishchilar Uchun Alohida Telegram Boti
Papka: worker-bot/

Har bir ishchi FAQAT o'zining shaxsiy hisob-kitobini ko'ra oladi:
- Sof foyda (qo'lga tegishi)
- Olingan avans va jarimalar
- Modellar va operatsiyalar kesimidagi ishbay hisob
- Skanerlangan pattalar tarixi
Boshqa ishchilar va korxona ma'lumotlari mutlaqo ko'rinmaydi.
"""

import sys
import os
import json
import time
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import urllib.request
import urllib.parse

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CURRENT_DIR, 'config.json')
BINDINGS_FILE = os.path.join(CURRENT_DIR, 'bindings.json')

def load_config():
    cfg = {
        "bot_token": os.environ.get("WORKER_BOT_TOKEN", "").strip(),
        "company_id": os.environ.get("DEFAULT_COMPANY_ID", "comp_novda").strip(),
        "webapp_url": os.environ.get("WORKER_WEBAPP_URL", "").strip()
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    if not cfg["bot_token"] and saved.get("bot_token"):
                        cfg["bot_token"] = saved["bot_token"].strip()
                    if saved.get("company_id"):
                        cfg["company_id"] = saved["company_id"].strip()
                    if not cfg["webapp_url"] and saved.get("webapp_url"):
                        cfg["webapp_url"] = saved["webapp_url"].strip()
        except Exception as e:
            print(f"[Config Error]: {e}")
    return cfg

config = load_config()
BOT_TOKEN = config.get("bot_token", "")
DEFAULT_COMPANY_ID = config.get("company_id", "comp_novda")
PORT = int(os.environ.get("PORT", "8081"))
FIREBASE_RTDB_URL = os.environ.get(
    "FIREBASE_DATABASE_URL",
    "https://hisobchi-c930c-default-rtdb.asia-southeast1.firebasedatabase.app"
).rstrip('/')

# In-memory user states for registration flow
user_states = {}

def get_base_webapp_url():
    if config.get("webapp_url"):
        return config["webapp_url"].rstrip('/')
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return f"{render_url.rstrip('/')}/webapp"
    # Fallback to main render app if available
    return "https://hisobmonitoringbot.onrender.com/worker-app"

def get_webapp_full_url(company_id, worker_id):
    base = get_base_webapp_url()
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}worker_id={worker_id}&comp={company_id}"

# ─────────────────────────────────────────────────────────────────────────────
# BINDINGS (Telegram ID <-> Worker ID)
# ─────────────────────────────────────────────────────────────────────────────

def get_local_bindings():
    if os.path.exists(BINDINGS_FILE):
        try:
            with open(BINDINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_local_binding(tg_id, binding_data):
    bindings = get_local_bindings()
    if binding_data is None:
        bindings.pop(str(tg_id), None)
    else:
        bindings[str(tg_id)] = binding_data
    try:
        with open(BINDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bindings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Binding Save Error] {e}")

def get_worker_binding(tg_id):
    """Checks Firebase RTDB, falls back to local bindings."""
    try:
        url = f"{FIREBASE_RTDB_URL}/worker_telegram_bindings/{tg_id}.json"
        req = urllib.request.Request(url, headers={'User-Agent': 'NovdaWorkerBot/1.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict) and data.get("worker_id"):
                save_local_binding(tg_id, data)
                return data
    except Exception as e:
        print(f"[Firebase Binding Check Warn]: {e}")

    local = get_local_bindings()
    return local.get(str(tg_id))

def save_worker_binding(tg_id, worker_id, worker_name, company_id=DEFAULT_COMPANY_ID, username=""):
    payload = {
        "tg_id": tg_id,
        "worker_id": int(worker_id),
        "worker_name": worker_name,
        "company_id": company_id,
        "username": username or "",
        "linked_at": datetime.now().isoformat()
    }
    save_local_binding(tg_id, payload)
    try:
        url = f"{FIREBASE_RTDB_URL}/worker_telegram_bindings/{tg_id}.json"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        with urllib.request.urlopen(req, timeout=8):
            pass
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Bog'landi: tg={tg_id} -> worker #{worker_id} ({worker_name})")
    except Exception as e:
        print(f"[Firebase Binding Save Error]: {e}")
    return payload

def remove_worker_binding(tg_id):
    save_local_binding(tg_id, None)
    try:
        url = f"{FIREBASE_RTDB_URL}/worker_telegram_bindings/{tg_id}.json"
        req = urllib.request.Request(url, headers={'Content-Type': 'application/json'}, method='DELETE')
        with urllib.request.urlopen(req, timeout=8):
            pass
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Uzildi: tg={tg_id}")
    except Exception as e:
        print(f"[Firebase Binding Delete Error]: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# FIREBASE WORKER CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_json(endpoint, timeout=12):
    try:
        url = f"{FIREBASE_RTDB_URL}/{endpoint.lstrip('/')}"
        req = urllib.request.Request(url, headers={'User-Agent': 'NovdaWorkerBot/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[Firebase Fetch Warn] {endpoint}: {e}")
        return None

def get_worker_profile_and_stats(company_id, worker_id):
    """
    Fetches worker data and calculates exact earnings, advances, fines, and net profit.
    Calculates exclusively for this worker. Returns None if worker not found.
    """
    workers = fetch_json(f"companies/{company_id}/syncData/workers.json")
    if not isinstance(workers, list):
        return None

    worker = next((w for w in workers if isinstance(w, dict) and int(w.get('id', -1)) == int(worker_id)), None)
    if not worker:
        return None

    models = fetch_json(f"companies/{company_id}/syncData/models.json")
    if not isinstance(models, list):
        models = []

    current_period = fetch_json(f"companies/{company_id}/syncData/currentPeriod.json")
    period_name = current_period.get("name") if isinstance(current_period, dict) else "Joriy Oylik Davr"

    total_gross = 0.0
    total_pieces = 0.0
    models_breakdown = {}

    wid_str = str(worker_id)
    for model in models:
        if not isinstance(model, dict):
            continue
        m_id = model.get("id")
        m_name = model.get("name") or f"Model #{m_id}"
        ops = model.get("operations") or []
        op_rates = {op.get("name"): float(op.get("rate", 0)) for op in ops if isinstance(op, dict)}
        
        hq = model.get("hisobQuantities") or {}
        w_ops = hq.get(wid_str) or {}

        m_gross = 0.0
        m_pieces = 0.0
        done_ops = []

        for op_name, qty in w_ops.items():
            try:
                num_qty = float(qty)
            except (ValueError, TypeError):
                num_qty = 0.0

            if num_qty > 0:
                rate = op_rates.get(op_name, 0.0)
                amount = num_qty * rate
                m_gross += amount
                m_pieces += num_qty
                done_ops.append({
                    "name": op_name,
                    "rate": rate,
                    "qty": num_qty,
                    "amount": amount
                })

        if m_gross > 0 or m_pieces > 0:
            models_breakdown[m_id] = {
                "name": m_name,
                "earnings": m_gross,
                "pieces": m_pieces,
                "operations": done_ops
            }
            total_gross += m_gross
            total_pieces += m_pieces

    avans = float(worker.get("avans") or 0.0)
    jarima = float(worker.get("jarima") or 0.0)
    staj = float(worker.get("staj") or 0.0)
    net_pay = total_gross - avans - jarima - staj

    return {
        "worker_id": int(worker_id),
        "worker_name": worker.get("name") or f"Ishchi #{worker_id}",
        "company_id": company_id,
        "period_name": period_name,
        "gross": total_gross,
        "avans": avans,
        "jarima": jarima,
        "staj": staj,
        "net": net_pay,
        "pieces": total_pieces,
        "models_breakdown": models_breakdown
    }

def get_worker_recent_tickets(company_id, worker_id, limit=6):
    """Fetches recently scanned tickets where this worker had an operation."""
    tickets = fetch_json(f"companies/{company_id}/syncData/submittedTickets.json", timeout=15)
    if not tickets:
        return []

    ticket_list = tickets if isinstance(tickets, list) else list(tickets.values())
    my_tickets = []
    wid_int = int(worker_id)

    for t in reversed(ticket_list):
        if not isinstance(t, dict):
            continue
        entries = t.get("entries") or []
        my_ops = [e.get("opName") for e in entries if isinstance(e, dict) and int(e.get("workerId", -1)) == wid_int]
        if my_ops:
            my_tickets.append({
                "model_id": t.get("modelId") or "Model",
                "patta_number": t.get("pattaNumber") or 1,
                "party_number": t.get("partyNumber") or "-",
                "size": t.get("size") or "-",
                "color": t.get("color") or "-",
                "qty": t.get("qty") or 0,
                "submitted_at": t.get("submittedAt") or "",
                "my_operations": ", ".join(my_ops)
            })
            if len(my_tickets) >= limit:
                break

    return my_tickets

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM BOT API HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def send_api(method, payload):
    if not BOT_TOKEN:
        print("[Warn] BOT_TOKEN sozlanmagan!")
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[Telegram API Error] {method}: {e}")
        return None

def build_main_reply_keyboard(company_id, worker_id):
    app_url = get_webapp_full_url(company_id, worker_id)
    return {
        "keyboard": [
            [
                {"text": "📱 Mening Hisobim (Web App)", "web_app": {"url": app_url}}
            ],
            [
                {"text": "💰 Sof Foyda va Oylik"},
                {"text": "📋 Bajargan Ishlarim"}
            ],
            [
                {"text": "🎫 Oxirgi Pattalarim"},
                {"text": "🔄 Yangilash"}
            ],
            [
                {"text": "ℹ️ Yordam & Qoidalar"},
                {"text": "🚪 Chiqish (Hisobdan uzish)"}
            ]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def format_money(amt):
    return f"{int(round(amt)):,}".replace(",", " ") + " so'm"

def format_number(amt):
    return f"{int(round(amt)):,}".replace(",", " ")

# ─────────────────────────────────────────────────────────────────────────────
# BOT MESSAGE & CALLBACK HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def handle_start(chat_id, user):
    tg_id = user.get("id")
    binding = get_worker_binding(tg_id)

    if binding and binding.get("worker_id"):
        wid = binding["worker_id"]
        comp = binding.get("company_id", DEFAULT_COMPANY_ID)
        name = binding.get("worker_name", f"Ishchi #{wid}")

        stats = get_worker_profile_and_stats(comp, wid)
        app_url = get_webapp_full_url(comp, wid)
        net_text = format_money(stats["net"]) if stats else "Hisoblanmoqda..."

        msg = (
            f"👋 <b>Assalomu alaykum, {name}!</b>\n\n"
            f"🆔 <b>Sizning ID:</b> #{wid}\n"
            f"💵 <b>Qo'lga tegadigan Sof Foyda:</b> <code>{net_text}</code>\n\n"
            f"🔒 <i>Ushbu botda faqat sizning shaxsiy hisob-kitobingiz ko'rinadi. "
            f"Boshqalar siznikini, siz esa birovnikini ko'ra olmaysiz.</i>\n\n"
            f"👇 Quyidagi tugmalar orqali batafsil tanishing:"
        )

        reply_markup = build_main_reply_keyboard(comp, wid)
        inline_markup = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Mening Shaxsiy Hisobim (Web App)", "web_app": {"url": app_url}}
                ]
            ]
        }
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "reply_markup": reply_markup
        })
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "📱 Web App ko'rinishida to'liq hisobotni ochish:",
            "reply_markup": inline_markup
        })
    else:
        user_states[tg_id] = {"step": "WAITING_WORKER_ID"}
        msg = (
            f"👋 <b>Assalomu alaykum!</b>\n\n"
            f"Novda xodimlarining shaxsiy hisob-kitob botiga xush kelibsiz.\n\n"
            f"Tizimdan foydalanish uchun korxonadagi <b>Ishchi ID</b> raqamingizni kiriting:\n"
            f"<i>(Masalan: <code>27</code>)</i>"
        )
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "reply_markup": {"remove_keyboard": True}
        })

def handle_text_input(chat_id, user, text):
    tg_id = user.get("id")
    state = user_states.get(tg_id, {})
    step = state.get("step")

    if text in ("💰 Sof Foyda va Oylik", "/hisob"):
        handle_finances(chat_id, tg_id)
        return

    if text in ("📋 Bajargan Ishlarim", "/operatsiyalar"):
        handle_operations(chat_id, tg_id)
        return

    if text in ("🎫 Oxirgi Pattalarim", "/pattalar"):
        handle_tickets(chat_id, tg_id)
        return

    if text in ("🔄 Yangilash", "/refresh"):
        handle_start(chat_id, user)
        return

    if text in ("ℹ️ Yordam & Qoidalar", "/help"):
        handle_help(chat_id, tg_id)
        return

    if text in ("🚪 Chiqish (Hisobdan uzish)", "/unbind"):
        handle_unbind_request(chat_id, tg_id)
        return

    if step == "WAITING_WORKER_ID" or not get_worker_binding(tg_id):
        digits = re.findall(r'\d+', text)
        if not digits:
            send_api("sendMessage", {
                "chat_id": chat_id,
                "text": "⚠️ Iltimos, faqat ID raqamingizni kiriting (Masalan: <code>27</code>):",
                "parse_mode": "HTML"
            })
            return

        candidate_id = int(digits[0])
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": f"🔍 ID #{candidate_id} tekshirilmoqda, iltimos kuting..."
        })

        workers = fetch_json(f"companies/{DEFAULT_COMPANY_ID}/syncData/workers.json")
        if not isinstance(workers, list):
            send_api("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Baza bilan ulanishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
            })
            return

        worker = next((w for w in workers if isinstance(w, dict) and int(w.get('id', -1)) == candidate_id), None)
        if not worker:
            send_api("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    f"❌ <b>ID #{candidate_id}</b> raqamli ishchi topilmadi.\n"
                    f"Iltimos, ID raqamingizni to'g'ri kiriting yoki ustangizdan aniqlang:"
                ),
                "parse_mode": "HTML"
            })
            return

        w_name = worker.get("name", f"Ishchi #{candidate_id}")
        user_states[tg_id] = {
            "step": "CONFIRMING",
            "candidate_id": candidate_id,
            "candidate_name": w_name
        }

        msg = (
            f"👤 <b>Xodim topildi:</b>\n\n"
            f"🆔 <b>Ishchi ID:</b> #{candidate_id}\n"
            f"📝 <b>F.I.O:</b> {w_name}\n\n"
            f"Ushbu hisob-kitob <b>sizga tegishlimi?</b>"
        )
        inline_kb = {
            "inline_keyboard": [
                [
                    {"text": "✅ Ha, bu men", "callback_data": f"confirm_worker:{candidate_id}"},
                    {"text": "❌ Boshqa raqam", "callback_data": "cancel_worker"}
                ]
            ]
        }
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "reply_markup": inline_kb
        })
        return

    send_api("sendMessage", {
        "chat_id": chat_id,
        "text": "Kerakli bo'limni pastdagi menyudan tanlang 👇"
    })

def handle_finances(chat_id, tg_id):
    binding = get_worker_binding(tg_id)
    if not binding:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Avval /start buyrug'i orqali tizimga kiring."})
        return

    wid = binding["worker_id"]
    comp = binding.get("company_id", DEFAULT_COMPANY_ID)
    stats = get_worker_profile_and_stats(comp, wid)
    if not stats:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Hisob-kitob ma'lumotlarini yuklab bo'lmadi."})
        return

    app_url = get_webapp_full_url(comp, wid)
    msg = (
        f"📊 <b>SHAXSIY HISOB-KITOB</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Xodim:</b> {stats['worker_name']} (ID: #{wid})\n"
        f"📅 <b>Davr:</b> {stats['period_name']}\n\n"
        f"💵 <b>Jami ishlangan:</b> {format_money(stats['gross'])}\n"
        f"➖ <b>Olingan avans:</b> {format_money(stats['avans'])}\n"
        f"➖ <b>Jarima / Ushlanma:</b> {format_money(stats['jarima'])}\n"
        f"➖ <b>Staj / Chegirma:</b> {format_money(stats['staj'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>SOF FOYDA (Qo'lga tegishi):</b> <code>{format_money(stats['net'])}</code>\n"
        f"🏷 <b>Bajarilgan ish soni:</b> {format_number(stats['pieces'])} dona\n\n"
        f"🔒 <i>Faqat sizning shaxsiy statistikangiz.</i>"
    )
    inline_kb = {
        "inline_keyboard": [
            [
                {"text": "📱 Web App orqali ko'rish", "web_app": {"url": app_url}}
            ]
        ]
    }
    send_api("sendMessage", {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": inline_kb
    })

def handle_operations(chat_id, tg_id):
    binding = get_worker_binding(tg_id)
    if not binding:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Avval /start buyrug'i orqali tizimga kiring."})
        return

    wid = binding["worker_id"]
    comp = binding.get("company_id", DEFAULT_COMPANY_ID)
    stats = get_worker_profile_and_stats(comp, wid)
    if not stats:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Ma'lumot topilmadi."})
        return

    mb = stats.get("models_breakdown") or {}
    if not mb:
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "🧵 Sizga joriy davrda hali operatsiyalar yoki tikilgan choklar kiritilmagan."
        })
        return

    text_parts = [
        f"📋 <b>BAJARILGAN ISHLAR TAFSILOTI</b>\n"
        f"👤 {stats['worker_name']} (ID: #{wid})\n"
        f"━━━━━━━━━━━━━━━━━━"
    ]

    for m_id, m in mb.items():
        text_parts.append(f"\n👗 <b>{m['name']}</b>: <code>{format_money(m['earnings'])}</code>")
        for op in m["operations"]:
            text_parts.append(
                f"  • {op['name']}: {format_number(op['qty'])} dona × {format_number(op['rate'])} so'm = <b>{format_money(op['amount'])}</b>"
            )

    text_parts.append("\n━━━━━━━━━━━━━━━━━━")
    text_parts.append(f"💵 <b>Jami hisoblangan:</b> <code>{format_money(stats['gross'])}</code>")

    app_url = get_webapp_full_url(comp, wid)
    inline_kb = {
        "inline_keyboard": [
            [
                {"text": "📱 To'liq ko'rinish (Web App)", "web_app": {"url": app_url}}
            ]
        ]
    }
    send_api("sendMessage", {
        "chat_id": chat_id,
        "text": "\n".join(text_parts),
        "parse_mode": "HTML",
        "reply_markup": inline_kb
    })

def handle_tickets(chat_id, tg_id):
    binding = get_worker_binding(tg_id)
    if not binding:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Avval /start orqali kiring."})
        return

    wid = binding["worker_id"]
    comp = binding.get("company_id", DEFAULT_COMPANY_ID)
    send_api("sendMessage", {"chat_id": chat_id, "text": "⏳ Pattalar yuklanmoqda..."})

    tickets = get_worker_recent_tickets(comp, wid, limit=8)
    if not tickets:
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "🎫 Hozircha sizning ID raqamingiz bilan skanerlangan chiptalar (pattalar) topilmadi."
        })
        return

    lines = [
        f"🎫 <b>OXIRGI TOPSHIRILGAN PATTALAR:</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    ]
    for t in tickets:
        lines.append(
            f"🏷 <b>{t['model_id']}</b> (Patta #{t['patta_number']})\n"
            f"Partiya: {t['party_number']} | Razmer: {t['size']} | Rang: {t['color']}\n"
            f"🧵 Chok: <b>{t['my_operations']}</b>\n"
            f"📦 Soni: <b>{t['qty']} dona</b> | ⏱️ {t['submitted_at']}\n"
        )

    app_url = get_webapp_full_url(comp, wid)
    inline_kb = {
        "inline_keyboard": [
            [
                {"text": "📱 Barcha pattalarni ko'rish", "web_app": {"url": app_url}}
            ]
        ]
    }
    send_api("sendMessage", {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "reply_markup": inline_kb
    })

def handle_help(chat_id, tg_id):
    binding = get_worker_binding(tg_id)
    wid_text = f"#{binding['worker_id']}" if binding else "Bog'lanmagan"
    msg = (
        f"ℹ️ <b>YORDAM VA FOYDALANISH QOIDALARI</b>\n\n"
        f"• <b>Shaxsiy ID:</b> {wid_text}\n"
        f"• <b>Sof Foyda formulasi:</b>\n"
        f"  <code>Sof Foyda = Jami tikilgan summa - Avans - Jarima</code>\n\n"
        f"🔒 <b>Xavfsizlik:</b> Siz faqat o'zingizga tegishli raqamlar va pattalarni ko'rasiz.\n\n"
        f"❓ Agar biror patta chiqmay qolgan bo'lsa yoki avans miqdorida savol bo'lsa, korxona ustasiga murojaat qiling."
    )
    send_api("sendMessage", {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})

def handle_unbind_request(chat_id, tg_id):
    binding = get_worker_binding(tg_id)
    if not binding:
        send_api("sendMessage", {"chat_id": chat_id, "text": "Siz hali biror hisobga bog'lanmagansiz."})
        return

    msg = (
        f"⚠️ <b>Hisobdan chiqishni tasdiqlaysizmi?</b>\n\n"
        f"Hozir siz ID #{binding['worker_id']} ({binding.get('worker_name', '')}) hisobiga ulangansiz.\n"
        f"Chiqsangiz, qayta kirish uchun ID raqamni qayta kiritishingiz kerak bo'ladi."
    )
    inline_kb = {
        "inline_keyboard": [
            [
                {"text": "🚪 Ha, hisobdan uzish", "callback_data": "confirm_unbind"},
                {"text": "❌ Bekor qilish", "callback_data": "cancel_unbind"}
            ]
        ]
    }
    send_api("sendMessage", {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": inline_kb
    })

def handle_callback_query(callback):
    cb_id = callback.get("id")
    data = callback.get("data", "")
    from_user = callback.get("from", {})
    tg_id = from_user.get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")

    send_api("answerCallbackQuery", {"callback_query_id": cb_id})

    if data.startswith("confirm_worker:"):
        wid = int(data.split(":")[1])
        st = user_states.get(tg_id, {})
        w_name = st.get("candidate_name")

        if not w_name:
            workers = fetch_json(f"companies/{DEFAULT_COMPANY_ID}/syncData/workers.json") or []
            w_obj = next((w for w in workers if isinstance(w, dict) and int(w.get('id', -1)) == wid), None)
            w_name = w_obj.get('name') if w_obj else f"Ishchi #{wid}"

        save_worker_binding(tg_id, wid, w_name, DEFAULT_COMPANY_ID, from_user.get("username", ""))
        user_states.pop(tg_id, None)

        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"🎉 <b>Tabriklaymiz!</b> Siz muvaffaqiyatli bog'landingiz.\n\n"
                f"👤 <b>Xodim:</b> {w_name}\n"
                f"🆔 <b>ID:</b> #{wid}\n\n"
                f"Endi pastdagi menyu orqali oyligingiz va ishlaringizni ko'rishingiz mumkin 👇"
            ),
            "parse_mode": "HTML",
            "reply_markup": build_main_reply_keyboard(DEFAULT_COMPANY_ID, wid)
        })

    elif data == "cancel_worker":
        user_states[tg_id] = {"step": "WAITING_WORKER_ID"}
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "Iltimos, o'zingizning to'g'ri Ishchi ID raqamingizni kiriting:"
        })

    elif data == "confirm_unbind":
        remove_worker_binding(tg_id)
        user_states.pop(tg_id, None)
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "✅ Hisob muvaffaqiyatli uzildi. Qayta kirish uchun /start buyrug'ini bosing.",
            "reply_markup": {"remove_keyboard": True}
        })

    elif data == "cancel_unbind":
        send_api("sendMessage", {
            "chat_id": chat_id,
            "text": "Amal bekor qilindi. O'z hisobingizdasiz."
        })

# ─────────────────────────────────────────────────────────────────────────────
# HTTP SERVER (Health & Standalone Worker Web App)
# ─────────────────────────────────────────────────────────────────────────────

class WorkerHttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        req_path = parsed.path

        if req_path in ('/webapp', '/webapp/', '/worker-app', '/worker-app/', '/worker', '/'):
            html_candidates = [
                os.path.join(CURRENT_DIR, 'webapp', 'index.html'),
                os.path.join(CURRENT_DIR, 'webapp', 'worker.html'),
                os.path.join(CURRENT_DIR, 'index.html'),
            ]
            content = None
            for p in html_candidates:
                if os.path.exists(p):
                    try:
                        with open(p, 'rb') as f:
                            content = f.read()
                        break
                    except Exception:
                        pass

            if content:
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
                return

        if req_path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "Novda Worker Bot"}')
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def log_message(self, format, *args):
        pass

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), WorkerHttpHandler)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Worker Bot HTTP server: http://0.0.0.0:{PORT}")
    server.serve_forever()

def keep_alive_ping():
    while True:
        try:
            time.sleep(480)
            render_url = os.environ.get("RENDER_EXTERNAL_URL")
            if render_url:
                url = render_url.rstrip('/') + '/health'
                req = urllib.request.Request(url, headers={'User-Agent': 'NovdaWorkerPing/1.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Worker Keep-alive: {resp.status}")
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# POLLING LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run_polling():
    global BOT_TOKEN
    if not BOT_TOKEN:
        print("\n=======================================================")
        print("⚠️  DIQQAT: Bot Token kiritilmagan!")
        print("worker-bot/config.json fayliga bot_token ni yozing yoki")
        print("WORKER_BOT_TOKEN muhit o'zgaruvchisini o'rnating.")
        print("=======================================================\n")
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Ishchilar Telegram Boti ishga tushirildi (Polling)...")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=25"
            req = urllib.request.Request(url, headers={'User-Agent': 'NovdaWorkerBot/1.0'})
            with urllib.request.urlopen(req, timeout=35) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get("ok"):
                    for update in res.get("result", []):
                        offset = update["update_id"] + 1
                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg.get("chat", {}).get("id")
                            user = msg.get("from", {})
                            text = msg.get("text", "").strip()
                            if text == "/start":
                                handle_start(chat_id, user)
                            elif text:
                                handle_text_input(chat_id, user, text)
                        elif "callback_query" in update:
                            handle_callback_query(update["callback_query"])
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()
    t_ping = threading.Thread(target=keep_alive_ping, daemon=True)
    t_ping.start()
    run_polling()
