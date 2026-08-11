import os
import time
import requests
import sqlite3
import re
import gradio as gr
from PIL import Image
import numpy as np
import cv2
import easyocr

# ================= 1. CONFIGURATION =================
NOWPAYMENTS_API_KEY = "QQTA7DP-MWDMQVM-HS23YZ4-A9A83MB"
DB_FILE = "users_studio.db"

# Bank details to display to customer for Local Transfer
BANK_DETAILS = """
🏦 **Sri Lanka Local Bank Transfer Details:**
- **Bank Name:** Commercial Bank / Sampath Bank
- **Account Name:** Sri Lanka AI Studio
- **Account Number:** 8009123456
- **Branch:** Colombo Fort
- **Amounts:** $2.00 = LKR 600.00 | $5.00 = LKR 1,500.00
*Note: Transfer කිරීමෙන් පසු පහළ ඇති Slip Scan එකට Slip එක Upload කරන්න.*
"""

# ================= 2. DATABASE SETUP =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            video_count INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'FREE',
            max_videos INTEGER DEFAULT 2
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            payment_id TEXT PRIMARY KEY,
            username TEXT,
            plan_type TEXT,
            status TEXT DEFAULT 'waiting'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# OCR Reader Loader (Lazy Load)
reader = None
def get_ocr_reader():
    global reader
    if reader is None:
        reader = easyocr.Reader(['en'], gpu=False)
    return reader

# ================= 3. AUTHENTICATION =================
def register_user(username, password):
    if not username.strip() or not password.strip():
        return "❌ Username සහ Password දෙකම ඇතුළත් කරන්න."
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return "❌ මෙම Username එක දැනටමත් පවතී. වෙනත් එකක් තෝරන්න."
    
    c.execute("INSERT INTO users (username, password, video_count, plan, max_videos) VALUES (?, ?, 0, 'FREE', 2)", 
              (username, password))
    conn.commit()
    conn.close()
    return "✅ Account එක සාර්ථකව සෑදුවා! දැන් Sign In වන්න."

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password, video_count, plan, max_videos FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row and row[0] == password:
        return True, f"✅ Login සාර්ථකයි! (User: {username} | Plan: {row[2]} | Videos Used: {row[1]}/{row[3]})"
    return False, "❌ Username හෝ Password වැරදියි!"

# ================= 4. PAYMENT & VERIFICATION =================
def create_visa_crypto_invoice(username, plan_type, pay_method):
    if not username:
        return "❌ කරුණාකර ප්‍රථමයෙන් Login වන්න!"
        
    amount = 2.0 if plan_type == "PLAN_20_VIDEOS" else 5.0
    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"}
    
    payload = {
        "price_amount": amount,
        "price_currency": "usd",
        "pay_currency": "usdttrc20" if pay_method == "Crypto (USDT)" else "usd",
        "order_id": f"ORD_{username}_{int(time.time())}",
        "order_description": f"AI Studio {plan_type} Upgrade ({pay_method})"
    }
    
    try:
        res = requests.post("https://api.nowpayments.io/v1/payment", json=payload, headers=headers)
        data = res.json()
        
        if "payment_id" in data:
            payment_id = str(data["payment_id"])
            pay_url = data.get("invoice_url", f"https://nowpayments.io/payment/?iid={payment_id}")
            
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT INTO orders (payment_id, username, plan_type, status) VALUES (?, ?, ?, 'waiting')",
                      (payment_id, username, plan_type))
            conn.commit()
            conn.close()
            
            return f"### 💳 Payment Invoice Ready ({pay_method})\n" \
                   f"**Amount:** ${amount:.2f} USD\n\n" \
                   f"👉 **[ගෙවීම සිදුකිරීමට මෙතන Click කරන්න ({pay_method})]({pay_url})**\n\n" \
                   f"*ගෙවා අවසන් වූ පසු 'Check & Verify Payment' බටන් එක ඔබන්න.*"
        else:
            return f"❌ Payment Gateway Error: {data.get('message', 'Please try again')}"
    except Exception as e:
        return f"❌ Connection Error: {str(e)}"

def verify_card_crypto_payment(username):
    if not username:
        return "❌ කරුණාකර Sign In වන්න!"
        
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT payment_id, plan_type FROM orders WHERE username=? AND status='waiting'", (username,))
    pending = c.fetchall()
    
    if not pending:
        conn.close()
        return "ℹ️ ඔබගේ බලාපොරොත්තුවෙන් පවතින (Pending) Payment එකක් නැත."
    
    headers = {"x-api-key": NOWPAYMENTS_API_KEY}
    updated = False
    
    for payment_id, plan_type in pending:
        try:
            res = requests.get(f"https://api.nowpayments.io/v1/payment/{payment_id}", headers=headers)
            status_data = res.json()
            p_status = status_data.get("payment_status", "")
            
            if p_status in ["finished", "confirmed", "sending"]:
                max_v = 20 if plan_type == "PLAN_20_VIDEOS" else 999999
                c.execute("UPDATE users SET plan=?, max_videos=? WHERE username=?", (plan_type, max_v, username))
                c.execute("UPDATE orders SET status='finished' WHERE payment_id=?", (payment_id,))
                conn.commit()
                updated = True
        except Exception as e:
            print("Verify error:", e)
            
    conn.close()
    if updated:
        return "🎉 **තහවුරු විය! ඔබගේ Account එක Pro Version එකට Upgrade විය.**"
    else:
        return "⏳ **තවමත් Payment එක Confirm වී නැත.** (විනාඩි 1-2ක් රැඳී සිට නැවත 'Verify' ඔබන්න)."

def verify_bank_slip(username, slip_image, selected_plan):
    if not username:
        return "❌ කරුණාකර ප්‍රථමයෙන් Login වන්න!"
    if slip_image is None:
        return "❌ කරුණාකර Bank Deposit Slip එකේ Photo එකක් Upload කරන්න."
        
    try:
        ocr = get_ocr_reader()
        img_np = np.array(slip_image.convert("RGB"))
        results = ocr.readtext(img_np, detail=0)
        full_text = " ".join(results).lower()
        
        target_amount = 600.0 if selected_plan == "PLAN_20_VIDEOS" else 1500.0
        
        # Check amount or keywords in receipt text
        has_amount = any(str(int(target_amount)) in full_text for _ in [1]) or ("600" in full_text or "1500" in full_text or "2" in full_text or "5" in full_text)
        has_bank = any(b in full_text for b in ["commercial", "boc", "sampath", "hnb", "peoples", "transfer", "paid", "deposit"])
        
        if has_amount or has_bank:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            max_v = 20 if selected_plan == "PLAN_20_VIDEOS" else 999999
            c.execute("UPDATE users SET plan=?, max_videos=? WHERE username=?", (selected_plan, max_v, username))
            conn.commit()
            conn.close()
            return f"🎉 **AI Verification Successful!** Slip එක සාර්ථකව Scan විය. ඔබගේ Plan එක ({selected_plan}) Activate විය!"
        else:
            return "⚠️ Slip එක පැහැදිලි නැත හෝ Amount එක ගැලපෙන්නේ නැත. කරුණාකර පැහැදිලි Photo එකක් දමන්න."
            
    except Exception as e:
        return f"❌ OCR Error: {str(e)}"

# ================= 5. VIDEO GENERATION ENGINE =================
def generate_video_proc(username, image, effect, duration, fps):
    if not username:
        return None, "❌ පළමුව Login වන්න!"
    if image is None:
        return None, "❌ Photo එකක් Upload කරන්න."
        
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT video_count, plan, max_videos FROM users WHERE username=?", (username,))
    user_data = c.fetchone()
    
    if not user_data:
        conn.close()
        return None, "❌ Account එක සොයාගත නොහැක."
        
    v_count, plan, max_v = user_data[0], user_data[1], user_data[2]
    
    if v_count >= max_v and plan != "UNLIMITED":
        conn.close()
        return None, f"⚠️ Video Limits අවසන්! ({v_count}/{max_v} Videos). කරුණාකර Upgrade කරගන්න."
    
    try:
        img_rgb = image.convert('RGB')
        img_array = np.array(img_rgb)
        h, w = img_array.shape[:2]
        total_frames = int(duration * fps)
        
        frames = []
        for i in range(total_frames):
            progress = i / max(total_frames - 1, 1)
            scale = 1.0 + (progress * 0.15)
            nh, nw = int(h * scale), int(w * scale)
            resized = cv2.resize(img_array, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
            sy, sx = (nh - h) // 2, (nw - w) // 2
            frames.append(cv2.cvtColor(resized[sy:sy+h, sx:sx+w], cv2.COLOR_RGB2BGR))
        
        video_path = f"video_{int(time.time())}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(video_path, fourcc, fps, (w, h))
        for f in frames:
            out.write(f)
        out.release()
        
        c.execute("UPDATE users SET video_count = video_count + 1 WHERE username=?", (username,))
        conn.commit()
        conn.close()
        
        return video_path, f"✅ Video හදා අවසන්! (Used: {v_count + 1}/{max_v})"
    except Exception as e:
        conn.close()
        return None, f"❌ Error: {str(e)}"

# ================= 6. GRADIO USER INTERFACE =================
with gr.Blocks(title="Sri Lanka AI Studio Pro") as demo:
    gr.Markdown("""
    # 🇱🇰 Sri Lanka AI Studio - Ultimate Cloud Version
    ### 🖼️ Photos = UNLIMITED & FREE | 🎥 First 2 Videos = FREE
    """)
    
    session_user = gr.State("")
    
    # Sign In / Sign Up Section
    with gr.Accordion("🔒 Account Access (Sign In / Sign Up)", open=True):
        with gr.Row():
            user_input = gr.Textbox(label="Username")
            pass_input = gr.Textbox(label="Password", type="password")
        
        with gr.Row():
            btn_login = gr.Button("🔑 Sign In", variant="primary")
            btn_signup = gr.Button("📝 Register New Account")
        
        auth_status = gr.Textbox(label="Account Status", interactive=False)

    # Main Tabs
    with gr.Tabs():
        # Tab 1: Video Generator
        with gr.Tab("🎬 Image to Video Generator"):
            img_in = gr.Image(label="Upload Photo", type="pil")
            eff_in = gr.Dropdown(["zoom"], value="zoom", label="Animation Effect")
            dur_in = gr.Slider(1, 10, value=3, label="Duration (Seconds)")
            fps_in = gr.Slider(12, 30, value=24, label="FPS")
            
            btn_gen = gr.Button("🎥 Generate AI Video", variant="primary")
            vid_out = gr.Video(label="Output Video")
            gen_status = gr.Textbox(label="Status", interactive=False)

        # Tab 2: Pricing & Payment
        with gr.Tab("💳 Upgrade Packages & Payment"):
            gr.Markdown("""
            ### 🚀 Subscription Packages
            * **Starter Plan:** $2.00 (LKR 600) -> **20 Videos**
            * **Pro Plan:** $5.00 (LKR 1,500) -> **UNLIMITED Videos**
            """)
            
            plan_selection = gr.Radio(
                choices=[("Starter ($2.00 / 20 Videos)", "PLAN_20_VIDEOS"), ("Pro ($5.00 / Unlimited)", "UNLIMITED")],
                value="PLAN_20_VIDEOS",
                label="Choose Plan"
            )
            
            with gr.Tabs():
                # Method 1: Visa/MasterCard & Crypto
                with gr.Tab("💳 Option 1: Visa / MasterCard / Crypto"):
                    pay_method_choice = gr.Radio(["Visa / MasterCard", "Crypto (USDT)"], value="Visa / MasterCard", label="Payment Method")
                    btn_get_pay_link = gr.Button("🔗 Generate Payment Link", variant="primary")
                    pay_link_out = gr.Markdown()
                    btn_verify_online = gr.Button("🔄 Check & Verify Payment Status")
                    online_verify_out = gr.Markdown()

                # Method 2: Local Bank Deposit (Slip Scan)
                with gr.Tab("🏦 Option 2: Local Bank Transfer (Sri Lanka)"):
                    gr.Markdown(BANK_DETAILS)
                    slip_file = gr.Image(label="Upload Deposit Slip Photo", type="pil")
                    btn_verify_slip = gr.Button("📸 Verify Bank Slip with AI", variant="primary")
                    slip_out = gr.Markdown()

    # Handlers & Events
    def handle_login(u, p):
        success, msg = login_user(u, p)
        return (u if success else ""), msg

    btn_signup.click(fn=register_user, inputs=[user_input, pass_input], outputs=auth_status)
    btn_login.click(fn=handle_login, inputs=[user_input, pass_input], outputs=[session_user, auth_status])
    
    btn_gen.click(fn=generate_video_proc, inputs=[session_user, img_in, eff_in, dur_in, fps_in], outputs=[vid_out, gen_status])
    
    btn_get_pay_link.click(
        fn=create_visa_crypto_invoice,
        inputs=[session_user, plan_selection, pay_method_choice],
        outputs=pay_link_out
    )
    btn_verify_online.click(fn=verify_card_crypto_payment, inputs=session_user, outputs=online_verify_out)
    
    btn_verify_slip.click(
        fn=verify_bank_slip,
        inputs=[session_user, slip_file, plan_selection],
        outputs=slip_out
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)
