import os, re, json, time, imaplib, email, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import jwt

# Vercel Environment Variables se aayega
CONFIG = {
    "port": int(os.environ.get("PORT", "8080")),
    "project_id": os.environ.get("FIREBASE_PROJECT_ID", "fampygateway"),
    "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL", ""),
    "private_key": os.environ.get("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n"),
}

def get_access_token():
    if not CONFIG["client_email"]: return None
    try:
        now = int(time.time())
        payload = {"iss": CONFIG["client_email"], "scope": "https://www.googleapis.com/auth/datastore", "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}
        signed = jwt.encode(payload, CONFIG["private_key"], algorithm="RS256")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": signed}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())["access_token"]
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

# Ye function user ki API Key verify karega aur uski settings layega
def get_user_data(api_key):
    token = get_access_token()
    if not token: return None
    try:
        url = f"https://firestore.googleapis.com/v1/projects/{CONFIG['project_id']}/databases/(default)/documents:runQuery"
        body = {"structuredQuery": {"from": [{"collectionId": "merchants"}], "where": {"fieldFilter": {"field": {"fieldPath": "apiKey"}, "op": "EQUAL", "value": {"stringValue": api_key}}}, "limit": 1}}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            if data and "document" in data[0]:
                fields = data[0]["document"]["fields"]
                return {
                    "email": fields.get("email", {}).get("stringValue", ""),
                    "upiId": fields.get("upiId", {}).get("stringValue", ""),
                    "gmailEmail": fields.get("gmailEmail", {}).get("stringValue", ""),
                    "gmailPassword": fields.get("gmailPassword", {}).get("stringValue", ""),
                }
    except Exception as e: print(f"DB Query Error: {e}")
    return None

def verify_payment(gmail_user, gmail_pass, expected_amount):
    if not gmail_user or not gmail_pass: return False
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=10)
        imap.login(gmail_user, gmail_pass)
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, 'ALL') 
        msg_ids = data[0].split() if data[0] else []
        for mid in reversed(msg_ids[-10:]): 
            typ, msg_data = imap.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = str(msg.get("Subject", "")).lower()
            if "fampay" not in subject and "credited" not in subject: continue
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain": body += str(part.get_payload(decode=True))
            else: body = str(msg.get_payload(decode=True))
            amount_match = re.search(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", body)
            if amount_match and float(amount_match.group(1).replace(",", "")) == expected_amount:
                return True 
        imap.logout()
    except Exception: pass
    return False

class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        api_key = query.get("api_key") or self.headers.get("X-API-Key")
        
        if not api_key: return self._send_json({"status": "error", "message": "API Key is required"}, 401)
        
        user = get_user_data(api_key)
        if not user: return self._send_json({"status": "error", "message": "Invalid API Key"}, 401)
        if not user["upiId"]: return self._send_json({"status": "error", "message": "Merchant has not configured UPI ID"}, 400)

        action = query.get("action", "create")
        amount = float(query.get("amount", 0))

        if action == "create":
            order_id = f"ord_{int(time.time())}"
            # Yahan User ki UPI ID use ho rahi hai
            upi_link = f"upi://pay?pa={quote(user['upiId'])}&am={amount:.2f}&cu=INR&tn={order_id}"
            qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300"
            return self._send_json({"status": "success", "order_id": order_id, "amount": amount, "upi_link": upi_link, "qr_url": qr_url})
            
        elif action == "check":
            is_paid = verify_payment(user['gmailEmail'], user['gmailPassword'], amount)
            return self._send_json({"status": "paid" if is_paid else "pending"})

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", CONFIG["port"]), handler)
    server.serve_forever()