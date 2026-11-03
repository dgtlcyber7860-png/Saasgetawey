#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-User FamPay UPI + Gmail IMAP Verification API
+ Firebase Firestore
+ Admin Panel (Control API Keys & Expiry)
"""

import os, re, json, time, random, imaplib, email, base64
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlencode, quote, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from cryptography.fernet import Fernet

import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
# CONFIG
# ============================================================
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

_DEFAULT_DIR = os.path.dirname(os.path.abspath(__file__))
_STORAGE_DIR = _DEFAULT_DIR if os.access(_DEFAULT_DIR, os.W_OK) else "/tmp"

CONFIG = {
    "admin_email": "shahid2005afridi@gmail.com",
    "admin_password": "Shahid7860@",
    "encryption_key": os.environ.get("ENCRYPTION_KEY", ""),
    "expiry_minutes": int(os.environ.get("EXPIRY_MINUTES", "15")),
    "port": int(os.environ.get("PORT", "8080")),
}

def get_fernet():
    key = CONFIG["encryption_key"]
    key_file = os.path.join(_STORAGE_DIR, ".fernet.key")
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

FAMPAY_SENDER_HINTS = ["fampay", "famapp", "fam pay", "fam app", "yesfam", "yes bank", "idfc", "upi", "received", "credited", "payment", "credit alert", "ord_", "money received", "paid to you"]

# ============================================================
# FIRESTORE HELPERS
# ============================================================
def fs_save_user(api_key, data):
    if not db: return False, "Firebase DB not connected."
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
    except: return None

def fs_get_all_users():
    if not db: return []
    try:
        users = db.collection(USERS_COL).stream()
        res = []
        for u in users:
            d = u.to_dict()
            d['api_key'] = u.id
            res.append(d)
        res.sort(key=lambda x: x.get("created_ts", 0), reverse=True)
        return res
    except: return []

def fs_update_user_status(api_key, status, expires_ts):
    if not db: return False
    try:
        db.collection(USERS_COL).document(api_key).update({
            "status": status,
            "expires_ts": int(expires_ts)
        })
        return True
    except: return False

def fs_save_order(order_id, data):
    if not db: return
    try: db.collection(ORDERS_COL).document(order_id).set(data)
    except: pass

def fs_get_order(order_id):
    if not db: return None
    try:
        doc = db.collection(ORDERS_COL).document(order_id).get()
        return doc.to_dict() if doc.exists else None
    except: return None

def fs_list_user_orders(api_key, limit=100):
    if not db: return []
    try:
        q = (db.collection(ORDERS_COL).where("owner", "==", api_key).order_by("created_ts", direction=firestore.Query.DESCENDING).limit(limit))
        return [d.to_dict() for d in q.stream()]
    except:
        try:
            q = db.collection(ORDERS_COL).where("owner", "==", api_key).limit(limit)
            rows = [d.to_dict() for d in q.stream()]
            rows.sort(key=lambda r: r.get("created_ts", 0), reverse=True)
            return rows
        except: return []

def fs_user_stats(api_key):
    if not db: return {"total_orders": 0, "paid_count": 0, "pending_count": 0, "expired_count": 0, "total_received": 0}
    try:
        rows = fs_list_user_orders(api_key, limit=500)
        paid = [r for r in rows if r.get("status") == "paid"]
        return {
            "total_orders": len(rows),
            "paid_count": len(paid),
            "pending_count": len([r for r in rows if r.get("status") == "pending"]),
            "expired_count": len([r for r in rows if r.get("status") == "expired"]),
            "total_received": round(sum(float(r.get("amount", 0)) for r in paid), 2),
        }
    except: return {"total_orders": 0, "paid_count": 0, "pending_count": 0, "expired_count": 0, "total_received": 0}

# ============================================================
# ENCRYPTION & USER MANAGEMENT
# ============================================================
def encrypt_secret(val): return get_fernet().encrypt(val.encode("utf-8")).decode("utf-8")
def decrypt_secret(val):
    try: return get_fernet().decrypt(val.encode("utf-8")).decode("utf-8")
    except: return ""

def generate_api_key():
    raw = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
    return "fp_live_" + raw

def register_user(name, upi_id, gmail_email, gmail_app_password):
    api_key = generate_api_key()
    now_ts = int(time.time())
    # Default 30 days validity for new users
    default_expiry = now_ts + (30 * 24 * 60 * 60)
    
    user_doc = {
        "name": name,
        "upi_id": upi_id.strip(),
        "gmail_email": gmail_email.strip().lower(),
        "gmail_app_password_enc": encrypt_secret(re.sub(r"\s+", "", gmail_app_password)),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_ts": now_ts,
        "status": "active",
        "expires_ts": default_expiry
    }
    success, msg = fs_save_user(api_key, user_doc)
    if not success: raise Exception(msg)
    return api_key

# ============================================================
# UPI & EMAIL PARSING
# ============================================================
def build_upi_link(upi_id, amount, merchant_name, order_id, reference):
    note = order_id or reference or "Payment"
    tr = reference or order_id or ""
    return f"upi://pay?pa={quote(upi_id)}&pn={quote(merchant_name or 'Merchant')}&am={amount:.2f}&cu=INR&tn={quote(note)}&tr={quote(tr)}"

def looks_like_fampay(sender, subject, body_preview):
    h = f"{sender} {subject} {body_preview[:800]}".lower()
    return any(x in h for x in FAMPAY_SENDER_HINTS)

def extract_fampay_txn_id(text):
    m = re.search(r"\b(FMP[A-Z0-9]{8,24})\b", text or "", re.IGNORECASE)
    return m.group(1) if m else None

def extract_utr(text):
    if not text: return None
    m = re.search(r"\b(?:UTR|RRN|UPI\s*Ref(?:erence)?(?:\s*No)?|Ref(?:erence)?\s*(?:No|Id|Number|#)?|Txn\s*(?:Id|Ref|Number)?)\s*[:\s#]*([0-9]{12})\b", text, re.I)
    if m: return m.group(1)
    f = extract_fampay_txn_id(text)
    if f: return f
    b = re.search(r"(?:^|[^A-Za-z0-9])([0-9]{12})(?:[^A-Za-z0-9]|$)", text)
    return b.group(1) if b else None

def extract_purpose(text):
    if not text: return None
    m = re.search(r"\b((?:test_)?ord_?[a-zA-Z0-9]{6,32})\b", text, re.I)
    if m: return m.group(1)
    m = re.search(r"(?:Purpose|Note|Remark|Remarks|Description|Message)[:\s]+([A-Za-z0-9_\-]{6,40})", text, re.I)
    return m.group(1) if m else None

def extract_amount(text):
    if not text: return None
    pats = [r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", r"received\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)", r"credited\s*(?:with|by|for)?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)", r"paid\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)", r"amount\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{1,2})?)"]
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
            ct = (p.get_content_type() or "").lower()
            if ct in ("text/plain", "text/html"):
                pl = p.get_payload(decode=True)
                if pl: parts.append(pl.decode(p.get_content_charset() or "utf-8", errors="replace"))
    else:
        pl = msg.get_payload(decode=True)
        if pl: parts.append(pl.decode(msg.get_content_charset() or "utf-8", errors="replace"))
    t = "\n".join(parts)
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&#8377;", "₹")
    return re.sub(r"\s+", " ", t).strip()

def normalize_ref(v): return re.sub(r"[^a-z0-9]", "", str(v or "").lower())
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
    if not rt or not ct: return False
    return (ct - 300) <= rt <= (et + 300)

def matches_explicit_reference(mail, order):
    if not is_eligible_mail(mail, order): return False
    oid = normalize_ref(order.get("id"))
    ref = normalize_ref(order.get("reference") or order.get("utr"))
    mo = normalize_ref(mail.get("orderId"))
    mr = normalize_ref(mail.get("raw"))
    ms = normalize_ref(mail.get("subject"))
    if oid and (mo == oid or oid in mr or oid in ms): return True
    if ref and len(ref) >= 6 and (ref in mr or ref in ms): return True
    return False

def fetch_fampay_emails(user_cfg):
    user = user_cfg["gmail_email"].strip().lower()
    pw = decrypt_secret(user_cfg["gmail_app_password_enc"])
    debug = {"connected": False, "error": None, "gmail": user}
    results = []
    if not user or not pw:
        debug["error"] = "Missing Gmail credentials"
        return {"emails": results, "debug": debug}
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=8)
        imap.login(user, pw)
        debug["connected"] = True
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, "ALL")
        ids = data[0].split() if (typ == "OK" and data and data[0]) else []
        newest = list(reversed(ids[-15:]))
        for mid in newest:
            typ, md = imap.fetch(mid, "(BODY.PEEK[])")
            if typ != "OK" or not md or not md[0]: continue
            msg = email.message_from_bytes(md[0][1])
            subj = decode_mime_header_str(msg.get("Subject", ""))
            sender = decode_mime_header_str(msg.get("From", ""))
            try:
                dt = parsedate_to_datetime(msg.get("Date", ""))
                rt = int(dt.timestamp())
            except: rt = int(time.time())
            body = extract_message_body(msg)
            if looks_like_fampay(sender, subj, body):
                full = f"{subj}\n{body}"
                amt = extract_amount(full)
                utr = extract_utr(full)
                fmp = extract_fampay_txn_id(full)
                oid = extract_purpose(full)
                if any([amt, utr, fmp, oid]):
                    results.append({
                        "utr": utr or fmp, "fampayTxnId": fmp, "orderId": oid,
                        "amount": amt, "subject": subj, "from": sender.lower(),
                        "received_ts": rt, "raw": body[:600],
                    })
            if len(results) >= 5: break
        imap.logout()
    except Exception as e:
        debug["error"] = str(e)
    return {"emails": results, "debug": debug}

def verify_order_against_mailbox(order, user_cfg):
    scan = fetch_fampay_emails(user_cfg)
    emails = scan["emails"]
    tp = amount_in_paise(order.get("payable_amount") or order.get("amount"))
    try:
        q = (db.collection(ORDERS_COL).where("owner", "==", order.get("owner")).where("status", "==", "pending"))
        all_pending = [d.to_dict() for d in q.stream()]
    except: all_pending = []
    pending_same = [o for o in all_pending if amount_in_paise(o.get("payable_amount") or o.get("amount")) == tp]
    for mail in emails:
        matched = matches_explicit_reference(mail, order)
        if not matched and len(pending_same) == 1 and pending_same[0].get("id") == order.get("id"):
            matched = is_eligible_mail(mail, order)
        if matched:
            order["status"] = "paid"
            order["utr"] = mail.get("utr") or mail.get("fampayTxnId") or order.get("reference")
            order["paid_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            order["paid_ts"] = int(time.time())
            fs_save_order(order["id"], order)
            return {"paid": True}
    return {"paid": False}

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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
        self.end_headers()

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")

    def _handle(self, method):
        try: self._process_request(method)
        except Exception as e:
            import traceback; traceback.print_exc()
            self._json({"status": "error", "message": "Server error: " + str(e)}, 500)

    def _process_request(self, method):
        parsed = urlparse(self.path)
        q = {k.strip().lower(): v[0].strip() for k, v in parse_qs(parsed.query).items()}
        raw = int(self.headers.get("Content-Length", "0") or "0")
        body = {}
        if raw > 0:
            try: body = json.loads(self.rfile.read(raw).decode())
            except: body = {}

        action = (q.get("action") or body.get("action") or "").lower()
        if not action:
            if "/register" in parsed.path: action = "register"
            elif "/check" in parsed.path: action = "check"
            elif "/health" in parsed.path: action = "health"
            elif "/dashboard" in parsed.path: action = "dashboard"
            elif "/admin" in parsed.path: action = "admin"
            elif q.get("order_id") or body.get("order_id"): action = "check"
            else: action = "create"

        if action == "health":
            return self._json({"status": "ok"})

        # ================= ADMIN ROUTES =================
        if action == "admin":
            admin_action = q.get("admin_action") or body.get("admin_action")
            
            if admin_action == "login":
                email = body.get("email", "")
                pw = body.get("password", "")
                if email == CONFIG["admin_email"] and pw == CONFIG["admin_password"]:
                    return self._json({"status": "success", "token": "admin_master_token"})
                return self._json({"status": "error", "message": "Invalid Admin Credentials"}, 401)

            if admin_action == "get_users":
                users = fs_get_all_users()
                # Clean sensitive data
                for u in users:
                    u.pop("gmail_app_password_enc", None)
                return self._json({"status": "success", "users": users})

            if admin_action == "update_user":
                target_key = body.get("api_key")
                new_status = body.get("status")
                new_expires = body.get("expires_ts")
                if fs_update_user_status(target_key, new_status, new_expires):
                    return self._json({"status": "success", "message": "User updated"})
                return self._json({"status": "error", "message": "Update failed"}, 500)

        # ================= USER ROUTES =================
        if action == "register":
            name = (body.get("name") or q.get("name") or "").strip()
            upi = (body.get("upi_id") or q.get("upi_id") or "").strip()
            gmail = (body.get("gmail_email") or q.get("gmail_email") or "").strip()
            app_pw = (body.get("gmail_app_password") or q.get("gmail_app_password") or "").strip()
            if not name or not upi or not gmail or not app_pw:
                return self._json({"status": "error", "message": "All fields required"}, 400)
            
            test_cfg = {"gmail_email": gmail, "gmail_app_password_enc": encrypt_secret(re.sub(r"\s+", "", app_pw))}
            scan = fetch_fampay_emails(test_cfg)
            if not scan["debug"]["connected"]:
                return self._json({"status": "error", "message": "Gmail login failed. Check App Password."}, 401)
            try:
                api_key = register_user(name, upi, gmail, app_pw)
            except Exception as e:
                return self._json({"status": "error", "message": "DB Error: " + str(e)}, 500)

            return self._json({"status": "success", "api_key": api_key, "message": "Generated!"}, 201)

        api_key = (self.headers.get("X-API-Key") or q.get("api_key") or body.get("api_key") or "").strip()
        auth = self.headers.get("Authorization", "")
        if not api_key and auth.lower().startswith("bearer "): api_key = auth[7:].strip()
        
        user_cfg = fs_get_user(api_key)
        if not user_cfg:
            return self._json({"status": "error", "code": "INVALID_API_KEY", "message": "Invalid API Key"}, 401)
            
        # 🔥 EXPIRY & STATUS CHECK 🔥
        if user_cfg.get("status") == "blocked":
            return self._json({"status": "error", "code": "BLOCKED", "message": "Your account is blocked by Admin."}, 403)
            
        if user_cfg.get("expires_ts") and int(time.time()) > int(user_cfg["expires_ts"]):
            return self._json({"status": "error", "code": "EXPIRED", "message": "Your API Key has expired. Contact Admin."}, 403)

        if action == "dashboard":
            return self._json({
                "status": "success",
                "user": {
                    "name": user_cfg.get("name"),
                    "upi_id": user_cfg.get("upi_id"),
                    "gmail_email": user_cfg.get("gmail_email"),
                    "expires_ts": user_cfg.get("expires_ts")
                },
                "stats": fs_user_stats(api_key),
                "orders": [ {k:v for k,v in o.items() if k != 'owner'} for o in fs_list_user_orders(api_key) ],
            })

        if action in ("check", "verify"):
            oid = (q.get("order_id") or body.get("order_id") or "").strip()
            if not oid: return self._json({"status": "error", "message": "order_id required"}, 400)
            order = fs_get_order(oid)
            if not order: return self._json({"status": "error", "message": "Order not found"}, 404)
            if order.get("owner") != api_key: return self._json({"status": "error", "message": "Forbidden"}, 403)
            
            if order.get("status") == "pending" and int(time.time()) > int(order.get("expires_ts", 0)):
                order["status"] = "expired"
                fs_save_order(oid, order)
                
            if order.get("status") == "pending":
                verify_order_against_mailbox(order, user_cfg)
                
            return self._json({
                "status": order["status"], "order_id": order["id"],
                "amount": float(order["amount"]), "payable_amount": float(order["payable_amount"]),
                "utr": order.get("utr"), "paid_at": order.get("paid_at"),
            })

        # Create Order
        try: amount = round(float(body.get("amount") or q.get("amount") or 0), 2)
        except: amount = 0.0
        if amount < 1.0: return self._json({"status": "error", "message": "Invalid amount."}, 400)

        now = int(time.time())
        exp = now + CONFIG["expiry_minutes"] * 60
        ref = str(random.randint(100000000000, 999999999999))
        oid = f"ord_{now}_{int(amount*100)}_{ref}"
        upi_link = build_upi_link(user_cfg["upi_id"], amount, user_cfg.get("name", "Merchant"), oid, ref)
        qr = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300"

        new_order = {
            "id": oid, "owner": api_key, "amount": amount, "payable_amount": amount,
            "provider": "fampay", "upi_id": user_cfg["upi_id"],
            "upi_link": upi_link, "qr_url": qr, "reference": ref,
            "utr": None, "status": "pending",
            "created_ts": now, "expires_ts": exp,
            "created_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "paid_at": None, "paid_ts": None,
            "user_name": user_cfg.get("name"),
        }
        fs_save_order(oid, new_order)
        return self._json({
            "status": "success", "order_id": oid, "amount": amount,
            "payable_amount": amount, "upi_id": user_cfg["upi_id"],
            "upi_link": upi_link, "qr_url": qr, "expires_at": new_order["expires_at"],
        }, 201)


FamPayAPIHandler = handler

if __name__ == "__main__":
    print(f"[FamPay Multi-User API] http://0.0.0.0:{CONFIG['port']}")
    HTTPServer(("0.0.0.0", CONFIG["port"]), handler).serve_forever()
