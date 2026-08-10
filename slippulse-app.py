"""
=============================================================================
 SLIPPULSE / SOVERINIX ENTERPRISE SUITE (Cloud-Ready & Fixed)
 Features Included:
  - Dynamic Database Support (SQLite with WAL Mode for Concurrency)
  - EasyOCR Slip / Receipt Verification
  - NowPayments Crypto Gateway with API Key
  - Environment Variables for API Keys & Secrets
  - Session Management & User Security
=============================================================================
"""

import os
import re
import uuid
import tempfile
import requests
import pandas as pd
from datetime import datetime
import streamlit as st
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# ===================== 1. CONFIGURATION & ENVIRONMENT =====================
st.set_page_config(
    page_title="SlipPulse - AI Payment & Invoicing",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Keys සහ Secrets (Streamlit Cloud Secrets හෝ Direct Key භාවිතය)
NOWPAYMENTS_API_KEY = st.secrets.get("NOWPAYMENTS_API_KEY", os.environ.get("NOWPAYMENTS_API_KEY", "QQTA7DP-MWDMQVM-HS23YZ4-A9A83MB"))
NOWPAYMENTS_BASE_URL = "https://api.nowpayments.io/v1"
DATABASE_URL = os.environ.get("DATABASE_URL", "slippulse_cloud.db")

SL_BANKS = [
    "commercial bank", "hnb", "hatton national", "sampath bank",
    "peoples bank", "boc", "bank of ceylon", "dfcc", "nations trust",
    "seylan", "union bank", "pan asia", "cargills bank", "nsb"
]

# ===================== 2. OPTIMIZED DATABASE ENGINE =====================
@contextmanager
def get_db():
    """Converts connection timeout and WAL mode to reduce database lock issues."""
    conn = sqlite3.connect(DATABASE_URL, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")  # Concurrency (Locks) අඩු කිරීමට WAL Mode එක
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                txn_id TEXT UNIQUE NOT NULL,
                date TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                method TEXT NOT NULL,
                status TEXT NOT NULL,
                bank TEXT,
                reference TEXT,
                nowpayments_url TEXT,
                nowpayments_payment_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        conn.commit()

# ===================== 3. EASYOCR INTEGRATION =====================
@st.cache_resource
def get_ocr_reader():
    """EasyOCR Engine එක Memory එකේ Cache කර තැබීම."""
    try:
        import easyocr
        return easyocr.Reader(['en'], gpu=False)
    except Exception as e:
        return None

def process_slip_ocr(image_bytes):
    reader = get_ocr_reader()
    if not reader:
        return {"error": "OCR Engine නොමැත. 'requirements.txt' එකේ easyocr තියෙනවාදැයි බලන්න."}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        results = reader.readtext(tmp_path, detail=0)
        extracted_text = " ".join(results).lower()
        
        # Bank Identification
        found_bank = "Unknown / Other"
        for bank in SL_BANKS:
            if bank in extracted_text:
                found_bank = bank.title()
                break
                
        # Amount Identification
        amt_match = re.search(r"(?:rs\.?|lkr|amount|total)[\s:]*([\d,]+\.?\d*)", extracted_text)
        amount = float(amt_match.group(1).replace(',', '')) if amt_match else 0.0

        # Ref / Txn ID Identification
        ref_match = re.search(r"(?:ref|txn|transaction|id)[\s#:]*([a-zA-Z0-9\-]+)", extracted_text)
        reference = ref_match.group(1).upper() if ref_match else "N/A"

        os.remove(tmp_path)
        return {
            "success": True,
            "bank": found_bank,
            "amount": amount,
            "reference": reference,
            "raw_text": extracted_text
        }
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return {"error": str(e)}

# ===================== 4. NOWPAYMENTS API & AUTOMATION =====================
class CryptoGateway:
    def __init__(self):
        self.headers = {
            "x-api-key": NOWPAYMENTS_API_KEY,
            "Content-Type": "application/json"
        }

    def create_invoice(self, amount, currency="usd", desc=""):
        payload = {
            "price_amount": amount,
            "price_currency": currency,
            "order_description": desc
        }
        try:
            res = requests.post(f"{NOWPAYMENTS_BASE_URL}/invoice", headers=self.headers, json=payload, timeout=20)
            if res.status_code in [200, 201]:
                return res.json()
            return {"error": f"API Error: {res.status_code}", "details": res.text}
        except Exception as e:
            return {"error": str(e)}

crypto = CryptoGateway()

# ===================== 5. USER INTERFACE (STREAMLIT) =====================
init_db()

if "user" not in st.session_state:
    st.session_state.user = None

# AUTHENTICATION SCREEN
if st.session_state.user is None:
    st.title("💰 SlipPulse - Business Suite")
    st.subheader("Login or Register")
    
    t1, t2 = st.tabs(["Sign In", "Create Account"])
    
    with t1:
        email = st.text_input("Email")
        pwd = st.text_input("Password", type="password")
        if st.button("Log In", use_container_width=True):
            import hashlib
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE email = ?", (email,))
                user = c.fetchone()
                if user and user['password_hash'] == hashlib.sha256(pwd.encode()).hexdigest():
                    st.session_state.user = dict(user)
                    st.rerun()
                else:
                    st.error("විස්තර වැරදියි. නැවත පරීක්ෂා කරන්න.")

    with t2:
        biz_name = st.text_input("Business Name")
        reg_email = st.text_input("Business Email")
        reg_pwd = st.text_input("Create Password", type="password")
        if st.button("Register", use_container_width=True):
            if biz_name and reg_email and reg_pwd:
                import hashlib
                pwd_hash = hashlib.sha256(reg_pwd.encode()).hexdigest()
                try:
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute("INSERT INTO users (business_name, email, phone, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                                  (biz_name, reg_email, "", pwd_hash, ""))
                        conn.commit()
                    st.success("ගිණුම සාර්ථකව සෑදුවා! දැන් Sign In වන්න.")
                except:
                    st.error("මේ Email එක දැනටමත් භාවිතා වේ.")

# MAIN DASHBOARD SCREEN
else:
    user = st.session_state.user
    st.sidebar.title("💰 SlipPulse")
    st.sidebar.write(f"🏢 **{user['business_name']}**")
    
    menu = st.sidebar.radio("Navigation", ["Dashboard", "Create Invoice / Crypto", "Scan Slip (OCR)", "Settings"])
    
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    # DASHBOARD
    if menu == "Dashboard":
        st.title("📊 Dashboard")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC", (user['id'],))
            txns = [dict(r) for r in c.fetchall()]

        if txns:
            df = pd.DataFrame(txns)
            st.metric("Total Transactions", len(df))
            st.dataframe(df[["txn_id", "date", "customer_name", "amount", "currency", "method", "status"]], use_container_width=True)
        else:
            st.info("තවම Transactions කිසිවක් නැත.")

    # INVOICE / CRYPTO
    elif menu == "Create Invoice / Crypto":
        st.title("📄 Generate Invoice & Crypto Link")
        c_name = st.text_input("Customer Name")
        amt = st.number_input("Amount (USD)", min_value=1.0, value=10.0)
        
        if st.button("Create Payment Link"):
            res = crypto.create_invoice(amount=amt, currency="usd", desc=f"Invoice for {c_name}")
            if "invoice_url" in res:
                txn_id = f"TXN-{uuid.uuid4().hex[:6].upper()}"
                pay_url = res["invoice_url"]
                
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO transactions (user_id, txn_id, date, customer_name, amount, currency, method, status, nowpayments_url)
                        VALUES (?, ?, ?, ?, ?, 'USD', 'Crypto', 'Pending', ?)
                    """, (user['id'], txn_id, datetime.now().strftime("%Y-%m-%d"), c_name, amt, pay_url))
                    conn.commit()
                    
                st.success("Payment Link එක සෑදුවා!")
                st.markdown(f"[👉 Click Here to Pay (${amt})]({pay_url})")
            else:
                st.error(f"Error: {res.get('error')}")

    # OCR SLIP SCANNER
    elif menu == "Scan Slip (OCR)":
        st.title("📸 Bank Deposit Slip Verification")
        uploaded_file = st.file_uploader("Upload Deposit Slip / Receipt", type=["jpg", "png", "jpeg"])
        
        if uploaded_file:
            st.image(uploaded_file, caption="Uploaded Slip", width=300)
            if st.button("Verify Slip with AI"):
                res = process_slip_ocr(uploaded_file.getvalue())
                if "success" in res:
                    st.success("✅ Slip Processed Successfully!")
                    st.write(f"**Bank:** {res['bank']}")
                    st.write(f"**Amount:** Rs. {res['amount']}")
                    st.write(f"**Ref No:** {res['reference']}")
                else:
                    st.error(f"Error: {res.get('error')}")
