import streamlit as st
import sqlite3
import pandas as pd
import requests
import easyocr
import cv2
import numpy as np
from PIL import Image
import io
import re

# 1. Page Configuration (අලුත් Logo Link එක සහ App Title එක)
st.set_page_config(
    page_title="SlipPulse - AI Payment & Verification",
    page_icon="https://i.imgur.com/wKa9RmE.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Dark theme & Professional UI)
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stButton>button {
        width: 100%;
        background-color: #00D4FF;
        color: #000000;
        font-weight: bold;
        border-radius: 8px;
        border: none;
        padding: 10px;
    }
    .stButton>button:hover {
        background-color: #00B3D6;
        color: #ffffff;
    }
    .card {
        background-color: #1e222d;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #2e3440;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# 2. Database Setup
def init_db():
    conn = sqlite3.connect("slippulse.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT UNIQUE,
            email TEXT,
            password TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_name TEXT,
            amount REAL,
            status TEXT,
            payment_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_slips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bank_name TEXT,
            amount REAL,
            ref_number TEXT,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# 3. Session State
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "business_name" not in st.session_state:
    st.session_state.business_name = ""

# EasyOCR Loader
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['en'], gpu=False)

# Header Section
st.title("💳 SlipPulse")
st.caption("AI-Powered Crypto Payment Gateway & Slip Verification System")

# 4. Authentication System
if not st.session_state.authenticated:
    tab1, tab2 = st.tabs(["🔒 Sign In", "📝 Create Account"])
    
    with tab1:
        st.subheader("Sign In to Your Dashboard")
        email = st.text_input("Email Address", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")
        
        if st.button("Sign In"):
            conn = sqlite3.connect("slippulse.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, business_name FROM users WHERE email=? AND password=?", (email, password))
            user = cursor.fetchone()
            conn.close()
            
            if user:
                st.session_state.authenticated = True
                st.session_state.user_id = user[0]
                st.session_state.business_name = user[1]
                st.success(f"Welcome back, {user[1]}!")
                st.rerun()
            else:
                st.error("Invalid email or password.")
                
    with tab2:
        st.subheader("Create a New Account")
        biz_name = st.text_input("Business Name")
        reg_email = st.text_input("Email Address")
        reg_pass = st.text_input("Password", type="password")
        
        if st.button("Register"):
            if biz_name and reg_email and reg_pass:
                try:
                    conn = sqlite3.connect("slippulse.db")
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO users (business_name, email, password) VALUES (?, ?, ?)", (biz_name, reg_email, reg_pass))
                    conn.commit()
                    conn.close()
                    st.success("Account created successfully! Please sign in.")
                except sqlite3.IntegrityError:
                    st.error("Business name already exists.")
            else:
                st.warning("Please fill in all fields.")

else:
    # Sidebar with Logo
    st.sidebar.image("https://i.imgur.com/wKa9RmE.png", width=110)
    st.sidebar.title(f"🏢 {st.session_state.business_name}")
    menu = st.sidebar.radio("Navigation", ["📊 Dashboard", "📄 Create Invoice (Crypto)", "📸 Scan Slip (AI OCR)", "⚙️ Account"])
    
    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.user_id = None
        st.session_state.business_name = ""
        st.rerun()

    # 1. Dashboard Tab
    if menu == "📊 Dashboard":
        st.header("📊 Business Overview")
        
        conn = sqlite3.connect("slippulse.db")
        tx_df = pd.read_sql_query("SELECT * FROM transactions WHERE user_id=?", conn, params=(st.session_state.user_id,))
        slips_df = pd.read_sql_query("SELECT * FROM verified_slips WHERE user_id=?", conn, params=(st.session_state.user_id,))
        conn.close()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Crypto Invoices", len(tx_df))
        col2.metric("Verified Bank Slips", len(slips_df))
        total_crypto_val = tx_df['amount'].sum() if not tx_df.empty else 0.0
        col3.metric("Total Crypto Volume ($)", f"${total_crypto_val:.2f}")
        
        st.subheader("Recent Invoices")
        if not tx_df.empty:
            st.dataframe(tx_df[['customer_name', 'amount', 'status', 'created_at']], use_container_width=True)
        else:
            st.info("No invoices created yet.")
            
        st.subheader("Verified Slips History")
        if not slips_df.empty:
            st.dataframe(slips_df[['bank_name', 'amount', 'ref_number', 'verified_at']], use_container_width=True)
        else:
            st.info("No bank slips verified yet.")

    # 2. Create Invoice Tab
    elif menu == "📄 Create Invoice (Crypto)":
        st.header("📄 Create Crypto Payment Invoice")
        
        cust_name = st.text_input("Customer Name")
        amount = st.number_input("Amount (USD)", min_value=1.0, step=0.5)
        api_key = st.text_input("NOWPayments API Key", value="QQTA7DP-MWDMQVM-HS23YZ4-A9A83MB", type="password")
        
        if st.button("Generate Payment Link"):
            if cust_name and amount > 0:
                headers = {"x-api-key": api_key, "Content-Type": "application/json"}
                payload = {
                    "price_amount": amount,
                    "price_currency": "usd",
                    "pay_currency": "usdttrc20",
                    "order_description": f"Invoice for {cust_name}"
                }
                
                try:
                    res = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers)
                    data = res.json()
                    
                    if "invoice_url" in data:
                        pay_url = data["invoice_url"]
                        conn = sqlite3.connect("slippulse.db")
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO transactions (user_id, customer_name, amount, status, payment_url) VALUES (?, ?, ?, ?, ?)",
                                       (st.session_state.user_id, cust_name, amount, "Pending", pay_url))
                        conn.commit()
                        conn.close()
                        
                        st.success("Payment Invoice Created!")
                        st.code(pay_url)
                        st.markdown(f"[👉 Open Payment Link]({pay_url})")
                    else:
                        st.error("Failed to generate payment link. Check API key.")
                except Exception as e:
                    st.error(f"Error connecting to payment provider: {e}")

    # 3. AI Slip Verification Tab
    elif menu == "📸 Scan Slip (AI OCR)":
        st.header("📸 AI Bank Deposit Slip Verification")
        st.write("Upload a bank deposit slip photo to scan and extract payment details.")
        
        uploaded_file = st.file_uploader("Choose a slip image...", type=["jpg", "jpeg", "png"])
        
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            st.image(image, caption="Uploaded Deposit Slip", use_column_width=True)
            
            if st.button("Verify Slip with AI"):
                with st.spinner("Scanning slip details..."):
                    reader = load_ocr()
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='PNG')
                    results = reader.readtext(img_bytes.getvalue(), detail=0)
                    
                    full_text = " ".join(results)
                    
                    # Extract Amount
                    amount_matches = re.findall(r'Rs\.?\s*([\d,]+\.?\d*)', full_text, re.IGNORECASE) or re.findall(r'([\d,]+\.\d{2})', full_text)
                    extracted_amount = float(amount_matches[0].replace(',', '')) if amount_matches else 0.0
                    
                    # Extract Ref/Tx ID
                    ref_matches = re.findall(r'(?:Ref|Txn|Reference|No|ID)[:\.\s]*([A-Za-z0-9]+)', full_text, re.IGNORECASE)
                    extracted_ref = ref_matches[0] if ref_matches else "N/A"
                    
                    # Detect Bank
                    banks = ["Commercial", "BOC", "Sampath", "HNB", "NSB", "Peoples", "NTB", "Seylan", "DFCC"]
                    detected_bank = "Unknown Bank"
                    for b in banks:
                        if b.lower() in full_text.lower():
                            detected_bank = b
                            break
                    
                    st.success("Slip Scanned Successfully!")
                    st.json({
                        "Detected Bank": detected_bank,
                        "Extracted Amount": extracted_amount,
                        "Reference Number": extracted_ref,
                        "Raw Extracted Text": full_text[:200] + "..."
                    })
                    
                    # Save to DB
                    conn = sqlite3.connect("slippulse.db")
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO verified_slips (user_id, bank_name, amount, ref_number) VALUES (?, ?, ?, ?)",
                                   (st.session_state.user_id, detected_bank, extracted_amount, extracted_ref))
                    conn.commit()
                    conn.close()
                    st.info("Record saved to database.")

    # 4. Account Settings Tab
    elif menu == "⚙️ Account":
        st.header("⚙️ Account Settings")
        st.write(f"**Business Name:** {st.session_state.business_name}")
        st.write(f"**User ID:** {st.session_state.user_id}")

