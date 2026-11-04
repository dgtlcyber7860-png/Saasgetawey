#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, json, time, random, imaplib, email, base64
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlencode, quote, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet

# ============================================================
# FIREBASE ADMIN
# ============================================================
import firebase_admin
from firebase_admin import credentials, firestore

_cred_path = os.environ.get("FIREBASE_CREDENTIALS", "")
_cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")

try:
    if _cred_json:
        cred = credentials.Certificate(json.loads(_cred_json))
    elif _cred_path and os.path.isfile(_cred_path):
        cred = credentials.Certificate(_cred_path)
    else:
        _default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serviceAccount.json")
        if os.path.isfile(_default):
            cred = credentials.Certificate(_default)
        else:
            cred = None

    if cred and not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    else:
        db = None
except Exception as e:
    print("FIREBASE INIT ERROR:", e)
    db = None

USERS_COL = "fampay_users"
ORDERS_COL = "fampay_orders"

# ============================================================
# CONFIG & ADMIN SETUP
# ============================================================
CONFIG = {
    "admin_password": os.environ.get("ADMIN_PASSWORD", "admin123"), # Admin Panel Password
    "encryption_key": os.environ.get("ENCRYPTION_KEY", ""),
    "expiry_minutes": int(os.environ.get("EXPIRY_MINUTES", "15")),
    "port": int(os.environ.get("PORT", "8080")),
}

def get_fernet():
    key = CONFIG["encryption_key"]
    key_file = os.path.join("/tmp", ".fernet.key")
    if not key:
        if os.path.isfile(key_file):
            key = open(key_file, "rb").read()
        else:
            key = Fernet.generate_key()
            try:
                with open(key_file, "wb") as f: f.write(key)
            except Exception: pass
        CONFIG["encryption_key"] = key
    return Fernet(key if isinstance(key, bytes) else key.encode())

# ============================================================
# FIRESTORE HELPERS
# ============================================================
def fs_save_user(api_key, data):
    if not db: return False, "DB not connected"
    try:
        db.collection(USERS_COL).document(api_key).set(data)
        return True, "Success"
    except Exception as e:
        return False, str(e)

def fs_get_user(api_key):
    if not db: return None
    try:
        doc = db.collection(USERS_COL).document(api_key).get()
        return doc.to_dict() if doc.exists else None
    except Exception: return None

def fs_get_all_users():
    if not db: return []
    try:
        return [d.to_dict() for d in db.collection(USERS_COL).stream()]
    except Exception: return []

def fs_update_user(api_key, update_data):
    if not db: return False
    try:
        db.collection(USERS_COL).document(api_key).update(update_data)
        return True
    except Exception: return False

def fs_save_order(order_id, data):
    if not db: return
    try: db.collection(ORDERS_COL).document(order_id).set(data)
    except Exception: pass

def fs_get_order(order_id):
    if not db: return None
    try:
        doc = db.collection(ORDERS_COL).document(order_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception: return None

def fs_list_user_orders(api_key, limit=100):
    if not db: return []
    try:
        q = db.collection(ORDERS_COL).where("owner", "==", api_key).limit(limit)
        rows = [d.to_dict() for d in q.stream()]
        rows.sort(key=lambda r: r.get("created_ts", 0), reverse=True)
        return rows
    except Exception: return []

def fs_user_stats(api_key):
    if not db: return {"total_orders": 0, "paid_count": 0, "pending_count": 0, "expired_count": 0, "total_received": 0}
    try:
        rows = fs_list_user_orders(api_key, limit=500)
        paid = [r for r in rows if r.get("status") == "paid"]
        pending = [r for r in rows if r.get("status") == "pending"]
        expired = [r for r in rows if r.get("status") == "expired"]
        total_paid_amount = sum(float(r.get("amount", 0)) for r in paid)
        return {
            "total_orders": len(rows),
            "paid_count": len(paid),
            "pending_count": len(pending),
            "expired_count": len(expired),
            "total_received": round(total_paid_amount, 2),
        }
    except Exception: return {"total_orders": 0, "paid_count": 0, "pending_count": 0, "expired_count": 0, "total_received": 0}

# ============================================================
# ENCRYPTION & AUTH
# ============================================================
def encrypt_secret(val): return get_fernet().encrypt(val.encode("utf-8")).decode("utf-8")
def decrypt_secret(val):
    try: return get_fernet().decrypt(val.encode("utf-8")).decode("utf-8")
    except Exception: return ""

def generate_api_key():
    raw = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
    return "fp_live_" + raw

def register_user(name, upi_id, gmail_email, gmail_app_password):
    api_key = generate_api_key()
    user_doc = {
        "name": name,
        "upi_id": upi_id.strip(),
        "gmail_email": gmail_email.strip().lower(),
        "gmail_app_password_enc": encrypt_secret(re.sub(r"\s+", "", gmail_app_password)),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_ts": int(time.time()),
        "expiry_date": None, # Admin sets this later
    }
    success, msg = fs_save_user(api_key, user_doc)
    if not success: raise Exception(msg)
    return api_key

def get_user_by_api_key(api_key):
    if not api_key: return None
    user = fs_get_user(api_key)
    if not user: return None
    
    # Check Expiry
    expiry_date = user.get("expiry_date")
    if expiry_date:
        try:
            # Format: YYYY-MM-DD
            exp_ts = datetime.strptime(expiry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            if time.time() > exp_ts:
                return None # Expired
        except Exception: pass
    return user

# ============================================================
# FAMPAY EMAIL PARSING (Same as before)
# ============================================================
FAMPAY_SENDER_HINTS = ["fampay", "famapp", "fam pay", "yesfam", "idfc", "upi", "credited", "payment", "ord_"]

def looks_like_fampay(sender, subject, body_preview):
    h = f"{sender} {subject} {body_preview[:800]}".lower()
    return any(x in h for x in FAMPAY_SENDER_HINTS)

def extract_utr(text):
    if not text: return None
    m = re.search(r"\b(?:UTR|RRN|Ref|Txn)\s*[:\s#]*([0-9]{12})\b", text, re.I)
    if m: return m.group(1)
    f = re.search(r"\b(FMP[A-Z0-9]{8,24})\b", text, re.IGNORECASE)
    if f: return f.group(1)
    b = re.search(r"(?:^|[^A-Za-z0-9])([0-9]{12})(?:[^A-Za-z0-9]|$)", text)
    return b.group(1) if b else None

def extract_amount(text):
    if not text: return None
    pats = [r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", r"amount\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)"]
    for p in pats:
        m = re.search(p, text, re.I)
        if m and m.group(1):
            try:
                v = float(m.group(1).replace(",", ""))
                if v > 0: return v
            except: pass
    return None

def decode_mime_header_str(v):
    if not v: return ""
    out = []
    for c, e in decode_header(v):
        out.append(c.decode(e or "utf-8", errors="replace") if isinstance(c, bytes) else str(c))
    return "".join(out)

def extract_message_body(msg):
    parts = []
    if msg.is_multipart():
        for p in msg.walk():
            if (p.get_content_type() or "").lower() in ("text/plain", "text/html"):
                pl = p.get_payload(decode=True)
                if pl: parts.append(pl.decode(p.get_content_charset() or "utf-8", errors="replace"))
    else:
        pl = msg.get_payload(decode=True)
        if pl: parts.append(pl.decode(msg.get_content_charset() or "utf-8", errors="replace"))
    t = "\n".join(parts)
    t = re.sub(r"<[^>]+>", " ", t).replace("&#8377;", "₹")
    return re.sub(r"\s+", " ", t).strip()

def amount_in_paise(v):
    try: return int(round(float(v) * 100))
    except: return None

def is_eligible_mail(mail, order):
    ep = amount_in_paise(mail.get("amount"))
    op = amount_in_paise(order.get("payable_amount") or order.get("amount"))
    if ep is None or op is None or ep != op: return False
    rt = int(mail.get("received_ts") or 0)
    ct = int(order.get("created_ts") or 0)
    et = int(order.get("expires_ts") or (ct + 900))
    return rt and (ct - 300) <= rt <= (et + 300)

def fetch_fampay_emails(user_cfg):
    user = user_cfg["gmail_email"].strip().lower()
    pw = decrypt_secret(user_cfg["gmail_app_password_enc"])
    debug = {"connected": False, "error": None}
    results = []
    if not user or not pw: return {"emails": results, "debug": debug}
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=8)
        imap.login(user, pw)
        debug["connected"] = True
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, "ALL")
        ids = data[0].split() if (typ == "OK" and data and data[0]) else []
        newest = list(reversed(ids[-10:]))
        for mid in newest:
            typ, md = imap.fetch(mid, "(BODY.PEEK[])")
            if typ != "OK" or not md or not md[0]: continue
            msg = email.message_from_bytes(md[0][1])
            subj = decode_mime_header_str(msg.get("Subject", ""))
            sender = decode_mime_header_str(msg.get("From", ""))
            try: rt = int(parsedate_to_datetime(msg.get("Date", "")).timestamp())
            except: rt = int(time.time())
            body = extract_message_body(msg)
            if looks_like_fampay(sender, subj, body):
                full = f"{subj}\n{body}"
                amt = extract_amount(full)
                utr = extract_utr(full)
                if amt or utr:
                    results.append({"utr": utr, "amount": amt, "received_ts": rt, "raw": body[:500]})
        imap.logout()
    except Exception as e: debug["error"] = str(e)
    return {"emails": results, "debug": debug}

def verify_order_against_mailbox(order, user_cfg):
    scan = fetch_fampay_emails(user_cfg)
    tp = amount_in_paise(order.get("payable_amount") or order.get("amount"))
    for mail in scan["emails"]:
        if is_eligible_mail(mail, order):
            order["status"] = "paid"
            order["utr"] = mail.get("utr") or order.get("reference")
            order["paid_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            order["paid_ts"] = int(time.time())
            fs_save_order(order["id"], order)
            return True
    return False

# ============================================================
# HTTP SERVER
# ============================================================
class handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        b = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
        self.end_headers()

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")

    def _handle(self, method):
        try: self._process_request(method)
        except Exception as e: self._json({"status": "error", "message": str(e)}, 500)

    def _process_request(self, method):
        parsed = urlparse(self.path)
        q = {k.strip().lower(): v[0].strip() for k, v in parse_qs(parsed.query).items()}
        raw = int(self.headers.get("Content-Length", "0") or "0")
        body = {}
        if raw > 0:
            try: body = json.loads(self.rfile.read(raw).decode())
            except: pass

        action = (q.get("action") or body.get("action") or "").lower()
        if not action:
            if "/register" in parsed.path: action = "register"
            elif "/check" in parsed.path: action = "check"
            elif "/dashboard" in parsed.path: action = "dashboard"
            elif "/admin" in parsed.path: action = "admin"
            else: action = "create"

        # --- ADMIN ACTIONS ---
        if action.startswith("admin_"):
            admin_pass = self.headers.get("X-Admin-Pass") or q.get("pass") or body.get("pass")
            if admin_pass != CONFIG["admin_password"]:
                return self._json({"status": "error", "message": "Invalid Admin Password"}, 401)

            if action == "admin_get_users":
                users = fs_get_all_users()
                # Remove sensitive info before sending
                for u in users: u.pop("gmail_app_password_enc", None)
                return self._json({"status": "success", "users": users})
            
            if action == "admin_update_expiry":
                target_key = body.get("api_key") or q.get("api_key")
                new_expiry = body.get("expiry_date") or q.get("expiry_date") # YYYY-MM-DD or null
                if not target_key: return self._json({"status": "error", "message": "api_key required"}, 400)
                fs_update_user(target_key, {"expiry_date": new_expiry})
                return self._json({"status": "success", "message": "Expiry updated"})

        # --- REGISTER ---
        if action == "register":
            name = (body.get("name") or q.get("name") or "").strip()
            upi = (body.get("upi_id") or q.get("upi_id") or "").strip()
            gmail = (body.get("gmail_email") or q.get("gmail_email") or "").strip()
            app_pw = (body.get("gmail_app_password") or q.get("gmail_app_password") or "").strip()
            if not all([name, upi, gmail, app_pw]):
                return self._json({"status": "error", "message": "All fields required"}, 400)
            
            test_cfg = {"gmail_email": gmail, "gmail_app_password_enc": encrypt_secret(re.sub(r"\s+", "", app_pw))}
            scan = fetch_fampay_emails(test_cfg)
            if not scan["debug"]["connected"]:
                return self._json({"status": "error", "message": "Gmail login failed"}, 401)
            
            api_key = register_user(name, upi, gmail, app_pw)
            return self._json({"status": "success", "api_key": api_key, "name": name}, 201)

        # --- AUTH FOR USERS ---
        api_key = self.headers.get("X-API-Key") or q.get("api_key") or body.get("api_key") or ""
        user_cfg = get_user_by_api_key(api_key)
        if not user_cfg:
            return self._json({"status": "error", "message": "Invalid or Expired API Key"}, 401)

        if action == "dashboard":
            return self._json({
                "status": "success",
                "user": {"name": user_cfg.get("name"), "upi_id": user_cfg.get("upi_id"), "gmail_email": user_cfg.get("gmail_email"), "expiry_date": user_cfg.get("expiry_date")},
                "stats": fs_user_stats(api_key),
                "orders": fs_list_user_orders(api_key, 100)
            })

        if action == "check":
            oid = q.get("order_id") or body.get("order_id")
            order = fs_get_order(oid)
            if not order or order.get("owner") != api_key: return self._json({"status": "error", "message": "Not found"}, 404)
            
            if order["status"] == "pending":
                if int(time.time()) > int(order.get("expires_ts", 0)):
                    order["status"] = "expired"
                    fs_save_order(oid, order)
                else:
                    verify_order_against_mailbox(order, user_cfg)
            
            return self._json({"status": order["status"], "order_id": oid, "amount": order["amount"], "utr": order.get("utr")})

        # --- CREATE ORDER ---
        try: amount = round(float(body.get("amount") or q.get("amount") or 0), 2)
        except: amount = 0.0
        if amount < 1.0: return self._json({"status": "error", "message": "Min ₹1.00"}, 400)

        now = int(time.time())
        exp = now + CONFIG["expiry_minutes"] * 60
        ref = str(random.randint(100000000000, 999999999999))
        oid = f"ord_{now}_{int(amount*100)}_{ref}"
        
        upi_link = f"upi://pay?pa={quote(user_cfg['upi_id'])}&pn={quote(user_cfg.get('name', 'Merchant'))}&am={amount:.2f}&cu=INR&tn={quote(oid)}&tr={quote(ref)}"
        
        new_order = {
            "id": oid, "owner": api_key, "amount": amount, "payable_amount": amount,
            "provider": "fampay", "upi_id": user_cfg["upi_id"], "upi_link": upi_link,
            "qr_url": f"https://quickchart.io/qr?text={quote(upi_link)}&size=300",
            "reference": ref, "status": "pending", "created_ts": now, "expires_ts": exp,
            "created_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        fs_save_order(oid, new_order)
        return self._json({
            "status": "success", "order_id": oid, "amount": amount, "upi_id": user_cfg["upi_id"],
            "upi_link": upi_link, "qr_url": new_order["qr_url"], "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }, 201)

FamPayAPIHandler = handler
