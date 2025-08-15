# biomasse_app.py
# Biomasse Abrechnungs-App – stabil & vereinfacht
# - Admin-Login bestätigt neue Lieferanten
# - Lieferant: Kunden + Materialien (mit Einheit kg/t/m3), Preise, Lieferscheine
# - M³ blendet Gewichtsfelder aus; kg/t zeigt Voll/Leer
# - Haftungsausschluss nur bei Neuanmeldung (mit Unterschrift)
# - PDF mit Signaturen; Mails an app.biomasse@gmail.com + Neuanmelder
# - Sicherer SMTP-Zugang: verschlüsselte Credentials + Fernet-Key in Secrets

import os
import io
import csv
import json
import hashlib
import smtplib
import base64
import traceback
import pandas as pd
import streamlit as st
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fpdf import FPDF

# Canvas für Unterschrift
try:
    from streamlit_drawable_canvas import st_canvas
except Exception:
    st.warning("Hinweis: 'streamlit-drawable-canvas' fehlt. Bitte in requirements.txt aufnehmen.")
    st.stop()

# ----------------------------- Konfiguration -----------------------------
APP_TITLE = "Biomasse Abrechnungs-App"
LOGO_PATH = "logo.png"  # optional – wenn fehlt, wird nur Titel gezeigt

DATA_ROOT = "data"
USERS_FILE = os.path.join(DATA_ROOT, "users.csv")             # email, pass_hash, status, created
SUPPLIERS_FILE = os.path.join(DATA_ROOT, "suppliers.csv")     # supplier_id, email, name, approved(0/1)
CUSTOMERS_FILE = os.path.join(DATA_ROOT, "customers.csv")     # supplier_id, customer_id, name, address
MATERIALS_FILE = os.path.join(DATA_ROOT, "materials.csv")     # supplier_id, material_id, name, unit(kg/t/m3), price
DOCS_DIR = os.path.join(DATA_ROOT, "docs")                    # PDFs & Signaturen
TMP_DIR = os.path.join(DATA_ROOT, "tmp")

ADMIN_LABEL = "Adminlogin"
SUPPLIER_LABEL = "Lieferantenlogin"

# feste Admin-Kennung: E-Mail frei, Code 8319 (wie gewünscht)
# (Admin-PIN wird im UI abgefragt)
ADMIN_PIN = "8319"

# ----------------------------- SMTP / Mail -----------------------------
# Sichere SMTP-Konfiguration über Fernet:
# 1) Erzeuge einmalig einen Key und lege ihn als Streamlit Secret "SMTP_KEY" ab.
# 2) Verschlüssele lokal User & Passwort -> Werte unten einsetzen.
# Hinweis: Falls KEY oder Encodings fehlen, senden wir keine Mails, aber die App läuft weiter.

FERNET_AVAILABLE = True
try:
    from cryptography.fernet import Fernet
except Exception:
    FERNET_AVAILABLE = False

def get_smtp_credentials():
    """Entschlüsselt SMTP_USER und SMTP_PASS aus Encodings.
       Falls Secrets/Key fehlen, return (None, None) -> Mailversand wird übersprungen."""
    if not FERNET_AVAILABLE:
        return None, None
    key = None
    # Streamlit Cloud: st.secrets; lokal: Umgebungsvariable
    if "SMTP_KEY" in st.secrets:
        try:
            key = st.secrets["SMTP_KEY"]
        except Exception:
            key = None
    if not key:
        key = os.environ.get("SMTP_KEY", None)

    if not key:
        return None, None

    try:
        f = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None, None

    # >>>>>>>>>>>> HIER DEINE VERSCHLÜSSELTEN CREDENTIALS EINFÜGEN <<<<<<<<<<<<<<
    # Anleitung im Chat unten (Schritt 1/2). Platzhalter lassen, wenn du es später setzt.
    ENC_USER = b""  # z.B.: b"gAAAAABl...."
    ENC_PASS = b""  # z.B.: b"gAAAAABl...."

    if not ENC_USER or not ENC_PASS:
        return None, None

    try:
        smtp_user = f.decrypt(ENC_USER).decode("utf-8")
        smtp_pass = f.decrypt(ENC_PASS).decode("utf-8")
        return smtp_user, smtp_pass
    except Exception:
        return None, None

def safe_mail_send(to_addr, subject, body, cc=None):
    """Schickt Mail (wenn SMTP konfiguriert). Sonst noop mit Info in Logs."""
    smtp_user, smtp_pass = get_smtp_credentials()
    if not smtp_user or not smtp_pass:
        # Kein Crash – nur Info
        print("[MAIL] Übersprungen – SMTP nicht konfiguriert.")
        return False

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_pass)
            to_list = [to_addr] + ([cc] if cc else [])
            server.sendmail(smtp_user, to_list, msg.as_string())
        return True
    except Exception as e:
        print("[MAIL] Fehler beim Senden:", e)
        return False

# ----------------------------- Utilities & Storage -----------------------------
def ensure_dirs():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

def load_csv(path, headers):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
        return []
    out = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            out.append(r)
    return out

def save_csv(path, headers, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def uid(prefix):
    return f"{prefix}_{int(datetime.now().timestamp()*1000)}"

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def safe_text(txt: str) -> str:
    """FPDF 1.7.2 ist latin-1. Wir ersetzen Umlaute/sonderzeichen, um Fehler zu vermeiden."""
    if txt is None:
        return ""
    repl = {
        "ä": "ae", "ö": "oe", "ü": "ue",
        "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
        "ß": "ss", "€": "EUR"
    }
    for k,v in repl.items():
        txt = txt.replace(k,v)
    try:
        txt.encode("latin-1")
        return txt
    except Exception:
        return txt.encode("latin-1","replace").decode("latin-1")

# ----------------------------- UI Helpers -----------------------------
def app_header():
    # Logo (falls vorhanden) + Titel in schöner Card
    with st.container():
        cols = st.columns([1,3])
        with cols[0]:
            try:
                if os.path.exists(LOGO_PATH):
                    st.image(LOGO_PATH, use_container_width=True)
            except Exception:
                pass
        with cols[1]:
            st.markdown(
                f"""
                <div style="padding:16px;border-radius:16px;background:linear-gradient(135deg,#0ea5e922,#22c55e22);">
                    <h2 style="margin:0;">{APP_TITLE}</h2>
                    <p style="margin:4px 0 0 0;color:#444">Kunden, Materialien und Lieferscheine einfach verwalten.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

def section(title: str, icon: str = "📦"):
    st.markdown(f"### {icon} {title}")

def info_pill(text: str):
    st.markdown(f"<div style='display:inline-block;padding:6px 10px;border-radius:999px;background:#eef2ff;color:#1e3a8a;font-size:12px;'>{text}</div>", unsafe_allow_html=True)

# ----------------------------- Auth / Registrierung -----------------------------
DISCLAIMER_TEXT = """\
**Haftungsausschluss (EU/Österreich):**
Mit Ihrer Registrierung bestätigen Sie, dass alle von Ihnen eingegebenen Daten korrekt sind.
Sie sind für die ordnungsgemäße Erfassung von Kunden-, Material- und Lieferscheindaten selbst verantwortlich.
Der Betreiber dieser App übernimmt keinerlei Haftung für fehlerhafte Eingaben, Berechnungen oder daraus resultierende Schäden.
Die App speichert Daten lokal im Projektspeicher bzw. im Hosting-Storage und versendet E-Mails ausschließlich an die jeweiligen Beteiligten.
Mit Klick auf „Registrieren“ sowie Ihrer Unterschrift akzeptieren Sie diesen Haftungsausschluss.
"""

def render_disclaimer_and_signature(key_prefix: str):
    st.markdown(DISCLAIMER_TEXT)
    st.caption("Bitte unterschreiben Sie unten (Finger/Maus).")
    canvas = st_canvas(
        fill_color="rgba(0,0,0,0)",
        stroke_width=2,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=140,
        width=600,
        drawing_mode="freedraw",
        key=f"{key_prefix}_sig"
    )
    # Robustes Prüfen auf Signaturpixel
    has_sig = False
    png_bytes = None
    if canvas and hasattr(canvas, "image_data") and canvas.image_data is not None:
        try:
            # Sobald irgendwas gezeichnet wurde, hat das Array Pixel != 0
            import numpy as np
            has_sig = np.any(canvas.image_data[:,:,3] > 0)  # alpha-Kanal
            if has_sig:
                from PIL import Image
                image = Image.fromarray(canvas.image_data.astype("uint8"))
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                png_bytes = buf.getvalue()
        except Exception:
            has_sig = False
            png_bytes = None
    return has_sig, png_bytes

def auth_tabs():
    st.markdown(
        "<div style='margin-top:8px;margin-bottom:8px;color:#475569'>Bitte melden Sie sich an oder registrieren Sie sich neu. Neue Konten müssen vom Admin freigegeben werden.</div>",
        unsafe_allow_html=True
    )
    t_login, t_register, t_admin = st.tabs([SUPPLIER_LABEL, "Neu anmelden", ADMIN_LABEL])

    # ---------------- Lieferanten-Login
    with t_login:
        st.subheader("Lieferantenlogin")
        login_email = st.text_input("E-Mail", key="login_email")
        login_pw    = st.text_input("Passwort", type="password", key="login_pw")
        if st.button("Anmelden", type="primary", key="login_btn"):
            users = load_csv(USERS_FILE, ["email","pass_hash","status","created"])
            suppliers = load_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"])
            u = next((x for x in users if x["email"].lower()==login_email.lower()), None)
            if not u:
                st.error("Unbekannte E-Mail.")
            else:
                if u["pass_hash"] != hash_pw(login_pw):
                    st.error("Falsches Passwort.")
                else:
                    s = next((x for x in suppliers if x["email"].lower()==login_email.lower()), None)
                    if not s:
                        st.error("Kein Lieferantenkonto verknüpft. Bitte Registrierung abwarten.")
                    elif s.get("approved","0") != "1":
                        st.warning("Ihr Konto wurde noch nicht freigegeben.")
                    else:
                        st.session_state["auth_role"] = "supplier"
                        st.session_state["supplier_id"] = s["supplier_id"]
                        st.success("Erfolgreich angemeldet.")

    # ---------------- Registrierung (mit Haftungsausschluss & Signatur)
    with t_register:
        st.subheader("Neu anmelden (Lieferant)")
        r_name  = st.text_input("Firmenname / Name", key="reg_name")
        r_email = st.text_input("E-Mail (Login)", key="reg_email")
        r_pw1   = st.text_input("Passwort", type="password", key="reg_pw1")
        r_pw2   = st.text_input("Passwort wiederholen", type="password", key="reg_pw2")

        st.divider()
        st.markdown("**Haftungsausschluss akzeptieren & unterschreiben**")
        accepted = st.checkbox("Ich akzeptiere den Haftungsausschluss.")
        has_sig, sig_png = render_disclaimer_and_signature("reg")

        if st.button("Registrieren", type="primary", key="reg_btn"):
            if not r_name or not r_email or not r_pw1:
                st.error("Bitte alle Felder ausfüllen.")
            elif r_pw1 != r_pw2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accepted:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            elif not has_sig:
                st.error("Bitte unterschreiben.")
            else:
                # Benutzer anlegen (status=open), Lieferant anlegen (approved=0)
                users = load_csv(USERS_FILE, ["email","pass_hash","status","created"])
                if any(u["email"].lower()==r_email.lower() for u in users):
                    st.error("E-Mail bereits registriert.")
                else:
                    users.append({
                        "email": r_email,
                        "pass_hash": hash_pw(r_pw1),
                        "status": "open",
                        "created": datetime.now().isoformat(timespec="seconds")
                    })
                    save_csv(USERS_FILE, ["email","pass_hash","status","created"], users)

                    suppliers = load_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"])
                    sid = uid("sup")
                    suppliers.append({
                        "supplier_id": sid,
                        "email": r_email,
                        "name": r_name,
                        "approved": "0"
                    })
                    save_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"], suppliers)

                    # Signatur-PDF des Haftungsausschlusses erzeugen
                    pdf_path = os.path.join(DOCS_DIR, f"Haftung_{sid}.pdf")
                    try:
                        pdf_disclaimer(r_name, r_email, sig_png, pdf_path)
                    except Exception as e:
                        print("PDF Haftung Fehler:", e)

                    # Mails: an App + an Neuanmelder (falls SMTP konfiguriert)
                    body_app = f"Neue Registrierung:\n\nName: {r_name}\nE-Mail: {r_email}\nSupplier-ID: {sid}\nZeit: {datetime.now()}\n\nBitte im Adminbereich prüfen & freigeben."
                    body_user = f"Hallo {r_name},\n\ndanke für Ihre Registrierung in der Biomasse-App.\nIhr Konto wird nach kurzer Prüfung freigeschaltet.\n\nViele Grüße"

                    safe_mail_send("app.biomasse@gmail.com", "Neue Lieferanten-Registrierung", body_app)
                    safe_mail_send(r_email, "Ihre Registrierung", body_user)

                    st.success("Registrierung eingegangen. Sie erhalten Zugang nach Admin-Freigabe.")

    # ---------------- Admin
    with t_admin:
        st.subheader("Adminlogin")
        admin_email = st.text_input("Admin E-Mail", key="adm_email")
        admin_pin   = st.text_input("Admin-Code (PIN)", type="password", key="adm_pin")

        if st.button("Admin anmelden", type="primary", key="adm_btn"):
            if not admin_email:
                st.error("Bitte Admin E-Mail eingeben.")
            elif admin_pin != ADMIN_PIN:
                st.error("Falscher Admin-Code.")
            else:
                st.session_state["auth_role"] = "admin"
                st.session_state["admin_email"] = admin_email
                st.success("Admin angemeldet.")

# ----------------------------- PDFs -----------------------------------
def pdf_disclaimer(name, email, sig_png, out_path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, safe_text("Haftungsausschluss – Biomasse App"), ln=True, align="L")

    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 6, safe_text(DISCLAIMER_TEXT.replace("**","")))

    pdf.ln(6)
    pdf.set_font("Arial","",12)
    pdf.cell(0, 8, safe_text(f"Name/Firma: {name}"), ln=True)
    pdf.cell(0, 8, safe_text(f"E-Mail: {email}"), ln=True)
    pdf.cell(0, 8, safe_text(f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"), ln=True)

    # Signatur-Bild (falls vorhanden)
    if sig_png:
        tmp_sig = os.path.join(TMP_DIR, "sig_disclaimer.png")
        with open(tmp_sig, "wb") as f:
            f.write(sig_png)
        try:
            pdf.ln(4)
            pdf.cell(0, 8, safe_text("Unterschrift:"), ln=True)
            y = pdf.get_y()
            pdf.image(tmp_sig, x=20, y=y+2, w=80)
            pdf.ln(35)
        except Exception:
            pass

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)

def pdf_delivery(data: dict) -> bytes:
    """
    data = {
      customer_name, customer_address,
      material_name, unit (kg/t/m3), price,
      quantity (bei m3), weight_full, weight_empty (bei kg/t),
      supplier_name, supplier_email,
      sig_customer (PNG bytes), sig_supplier (PNG bytes)
    }
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial","B",16)
    pdf.cell(0,10, safe_text("Lieferschein"), ln=True)

    pdf.set_font("Arial","",12)
    pdf.cell(0,7, safe_text(f"Kunde: {data.get('customer_name','')}"), ln=True)
    pdf.cell(0,7, safe_text(f"Adresse: {data.get('customer_address','')}"), ln=True)
    pdf.ln(3)

    pdf.cell(0,7, safe_text(f"Material: {data.get('material_name','')}"), ln=True)
    pdf.cell(0,7, safe_text(f"Einheit: {data.get('unit','')}"), ln=True)
    pdf.cell(0,7, safe_text(f"Preis: {data.get('price','')}"), ln=True)

    unit = data.get("unit","")
    if unit == "m3":
        pdf.cell(0,7, safe_text(f"Menge (m3): {data.get('quantity','')}"), ln=True)
    else:
        wf = data.get("weight_full","")
        we = data.get("weight_empty","")
        net = None
        try:
            net = float(wf) - float(we)
        except Exception:
            net = None
        pdf.cell(0,7, safe_text(f"Vollgewicht: {wf}"), ln=True)
        pdf.cell(0,7, safe_text(f"Leergewicht: {we}"), ln=True)
        if net is not None:
            pdf.cell(0,7, safe_text(f"Netto: {net} {unit}"), ln=True)

    pdf.ln(5)
    pdf.cell(0,7, safe_text(f"Lieferant: {data.get('supplier_name','')}"), ln=True)
    pdf.cell(0,7, safe_text(f"E-Mail: {data.get('supplier_email','')}"), ln=True)
    pdf.ln(4)

    # Signaturen platzieren
    def put_sig(png_bytes, label):
        if not png_bytes:
            return
        tmp = os.path.join(TMP_DIR, f"sig_{label}.png")
        with open(tmp, "wb") as f:
            f.write(png_bytes)
        try:
            pdf.cell(0,7, safe_text(label+":"), ln=True)
            y = pdf.get_y()
            pdf.image(tmp, x=20, y=y+2, w=70)
            pdf.ln(35)
        except Exception:
            pass

    put_sig(data.get("sig_customer",None), "Unterschrift Kunde")
    put_sig(data.get("sig_supplier",None), "Unterschrift Lieferant")

    # Rückgabe als Bytes
    s = pdf.output(dest="S").encode("latin-1", "ignore")
    return s

# ----------------------------- Admin-Bereich -----------------------------
def admin_area():
    section("Neue Lieferanten prüfen & freigeben", "🛠️")
    suppliers = load_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"])
    pending = [s for s in suppliers if s.get("approved","0")!="1"]
    approved = [s for s in suppliers if s.get("approved","0")=="1"]

    st.markdown("#### Offene Anträge")
    if not pending:
        st.info("Keine offenen Anträge.")
    else:
        for s in pending:
            with st.container():
                cols = st.columns([3,2,2,2])
                cols[0].markdown(f"**{s['name']}**  \n{s['email']}")
                if cols[1].button("Freigeben", key=f"appr_{s['supplier_id']}"):
                    s["approved"]="1"
                    save_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"], suppliers)
                    safe_mail_send(s["email"], "Ihr Zugang ist frei", "Ihr Lieferantenkonto ist nun freigeschaltet.")
                    st.success(f"{s['name']} freigegeben.")
                if cols[2].button("Ablehnen", key=f"deny_{s['supplier_id']}"):
                    # Benutzer & Supplier löschen
                    users = load_csv(USERS_FILE, ["email","pass_hash","status","created"])
                    users = [u for u in users if u["email"].lower()!=s["email"].lower()]
                    suppliers = [x for x in suppliers if x["supplier_id"]!=s["supplier_id"]]
                    save_csv(USERS_FILE, ["email","pass_hash","status","created"], users)
                    save_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"], suppliers)
                    safe_mail_send(s["email"], "Ihr Antrag wurde abgelehnt", "Ihr Antrag wurde abgelehnt.")
                    st.warning(f"{s['name']} abgelehnt & entfernt.")

    st.divider()
    st.markdown("#### Bestehende Lieferanten")
    for s in approved:
        cols = st.columns([3,2])
        cols[0].markdown(f"**{s['name']}**  \n{s['email']}  \nID: `{s['supplier_id']}`")
        if cols[1].button("Lieferant löschen", key=f"del_{s['supplier_id']}"):
            # Sicherheitsabfrage über PIN
            pin = st.text_input("Sicherheitscode (Admin-PIN)", type="password", key=f"pin_{s['supplier_id']}")
            if pin == ADMIN_PIN:
                # Entfernen
                users = load_csv(USERS_FILE, ["email","pass_hash","status","created"])
                users = [u for u in users if u["email"].lower()!=s["email"].lower()]
                sup_all = load_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"])
                sup_all = [x for x in sup_all if x["supplier_id"]!=s["supplier_id"]]
                save_csv(USERS_FILE, ["email","pass_hash","status","created"], users)
                save_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"], sup_all)
                st.success("Lieferant gelöscht.")
            else:
                st.error("Falscher Sicherheitscode.")

# ----------------------------- Lieferanten-Bereich -----------------------------
def supplier_area(supplier_id: str):
    # Daten laden
    suppliers = load_csv(SUPPLIERS_FILE, ["supplier_id","email","name","approved"])
    me = next((x for x in suppliers if x["supplier_id"]==supplier_id), None)
    if not me:
        st.error("Konto nicht gefunden.")
        return
    supplier_email = me["email"]
    supplier_name  = me["name"]

    # Tabs: Reihenfolge – Lieferscheine, Kunden, Materialien (wie gewünscht)
    t_ls, t_cust, t_mat = st.tabs(["Lieferschein", "Kunden", "Materialien"])

    # ----- Lieferschein
    with t_ls:
        section("Neuen Lieferschein erstellen", "📄")
        # Kundenliste des Lieferanten
        customers = load_csv(CUSTOMERS_FILE, ["supplier_id","customer_id","name","address"])
        my_customers = [c for c in customers if c["supplier_id"]==supplier_id]
        cust_options = ["— bitte wählen —"] + [f"{c['name']} ({c['address']})|{c['customer_id']}" for c in my_customers]
        sel_cust = st.selectbox("Kunde", cust_options, key="ls_cust")

        # Materialien gefiltert auf Kunde: wir erlauben (einfacher) alle Materialien des Lieferanten,
        # plus Option, künftig kunde-spezifische Filter zu verwenden.
        materials = load_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"])
        my_materials = [m for m in materials if m["supplier_id"]==supplier_id]
        mat_options = ["— bitte wählen —"] + [f"{m['name']} | {m['unit']} | {m['price']}|{m['material_id']}" for m in my_materials]
        sel_mat = st.selectbox("Material", mat_options, key="ls_mat")

        unit = None
        price = None
        mat_name = ""
        if sel_mat and sel_mat != "— bitte wählen —":
            parts = sel_mat.split("|")
            if len(parts)>=4:
                mat_name = parts[0].strip()
                unit = parts[1].strip()
                price = parts[2].strip()

        # Einheit steuert Felder:
        qty_m3 = None
        weight_full = None
        weight_empty = None

        colA, colB = st.columns(2)
        with colA:
            if unit == "m3":
                qty_m3 = st.number_input("Menge (m³)", min_value=0.0, step=0.1, key="ls_m3")
            elif unit in ("kg","t"):
                weight_full = st.number_input("Vollgewicht", min_value=0.0, step=0.1, key="ls_full")
                weight_empty = st.number_input("Leergewicht", min_value=0.0, step=0.1, key="ls_empty")
            else:
                st.info("Bitte Material wählen.")

        st.caption("Unterschriften (Kunde & Lieferant)")
        colS1, colS2 = st.columns(2)
        with colS1:
            has_cust_sig, sig_cust_png = render_signature_only("sig_cust")
            st.caption("Kunde")
        with colS2:
            has_sup_sig,  sig_sup_png  = render_signature_only("sig_sup")
            st.caption("Lieferant")

        if st.button("PDF erstellen & speichern", type="primary", key="ls_pdf"):
            if sel_cust == "— bitte wählen —" or sel_mat == "— bitte wählen —":
                st.error("Bitte Kunde und Material wählen.")
            elif unit == "m3" and (qty_m3 is None or qty_m3 <= 0):
                st.error("Bitte m³ Menge eingeben.")
            elif unit in ("kg","t") and (weight_full is None or weight_empty is None or weight_full <= weight_empty):
                st.error("Bitte Voll/Leer korrekt eingeben (Voll > Leer).")
            elif not has_cust_sig or not has_sup_sig:
                st.error("Bitte beide Unterschriften erfassen.")
            else:
                cust_id = sel_cust.split("|")[-1]
                cust = next((c for c in my_customers if c["customer_id"]==cust_id), None) or {}
                data = {
                    "customer_name": cust.get("name",""),
                    "customer_address": cust.get("address",""),
                    "material_name": mat_name,
                    "unit": unit,
                    "price": price,
                    "quantity": qty_m3,
                    "weight_full": weight_full,
                    "weight_empty": weight_empty,
                    "supplier_name": supplier_name,
                    "supplier_email": supplier_email,
                    "sig_customer": sig_cust_png,
                    "sig_supplier": sig_sup_png
                }
                try:
                    pdf_bytes = pdf_delivery(data)
                    file_name = f"Lieferschein_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    out_path = os.path.join(DOCS_DIR, file_name)
                    with open(out_path, "wb") as f:
                        f.write(pdf_bytes)
                    st.success("PDF erstellt und gespeichert.")
                    st.download_button("PDF herunterladen", data=pdf_bytes, file_name=file_name, mime="application/pdf", key="dl_pdf")
                except Exception as e:
                    st.error("Fehler bei der PDF-Erstellung. Details in Logs.")
                    print("PDF Err:", traceback.format_exc())

    # ----- Kunden
    with t_cust:
        section("Kunden verwalten", "👥")
        customers = load_csv(CUSTOMERS_FILE, ["supplier_id","customer_id","name","address"])
        my_customers = [c for c in customers if c["supplier_id"]==supplier_id]

        # Suche + Liste
        q = st.text_input("Kunden suchen (Name/Adresse)", key="cust_search")
        rows = [c for c in my_customers if (q.lower() in c["name"].lower() or q.lower() in c["address"].lower())] if q else my_customers
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        st.markdown("**Neuen Kunden anlegen**")
        c_name = st.text_input("Name", key="new_c_name")
        c_addr = st.text_input("Adresse", key="new_c_addr")
        if st.button("Kunde speichern", key="save_cust"):
            if not c_name:
                st.error("Name fehlt.")
            else:
                cid = uid("cust")
                customers.append({"supplier_id":supplier_id, "customer_id":cid, "name":c_name, "address":c_addr})
                save_csv(CUSTOMERS_FILE, ["supplier_id","customer_id","name","address"], customers)
                st.success("Kunde gespeichert.")

    # ----- Material
    with t_mat:
        section("Materialien verwalten", "🧱")
        materials = load_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"])
        my_materials = [m for m in materials if m["supplier_id"]==supplier_id]
        st.dataframe(pd.DataFrame(my_materials), use_container_width=True)

        st.markdown("**Neues Material**")
        m_name = st.text_input("Materialname", key="m_name")
        m_unit = st.selectbox("Einheit", ["kg","t","m3"], key="m_unit")
        m_price = st.number_input("Preis (pro Einheit)", min_value=0.0, step=0.1, key="m_price")
        if st.button("Material speichern", key="save_mat"):
            if not m_name:
                st.error("Name fehlt.")
            else:
                mid = uid("mat")
                materials.append({"supplier_id":supplier_id, "material_id":mid, "name":m_name, "unit":m_unit, "price":str(m_price)})
                save_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"], materials)
                st.success("Material gespeichert.")

        st.markdown("**Material ändern/löschen**")
        if my_materials:
            opts = [f"{m['name']} | {m['unit']} | {m['price']}|{m['material_id']}" for m in my_materials]
            sel = st.selectbox("Material wählen", opts, key="sel_mat_edit")
            sel_id = sel.split("|")[-1]
            em = next((m for m in my_materials if m["material_id"]==sel_id), None)
            if em:
                n_name = st.text_input("Neuer Name", value=em["name"], key="edit_m_name")
                n_unit = st.selectbox("Neue Einheit", ["kg","t","m3"], index=["kg","t","m3"].index(em["unit"]), key="edit_m_unit")
                n_price= st.number_input("Neuer Preis", value=float(em["price"]), step=0.1, key="edit_m_price")
                c1, c2 = st.columns(2)
                if c1.button("Änderungen speichern", key="btn_m_upd"):
                    em["name"]=n_name; em["unit"]=n_unit; em["price"]=str(n_price)
                    # zurück in Gesamt-Liste
                    allm = load_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"])
                    for i,mm in enumerate(allm):
                        if mm["material_id"]==sel_id:
                            allm[i]=em
                            break
                    save_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"], allm)
                    st.success("Material aktualisiert.")
                if c2.button("Material löschen", key="btn_m_del"):
                    allm = load_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"])
                    allm = [x for x in allm if x["material_id"]!=sel_id]
                    save_csv(MATERIALS_FILE, ["supplier_id","material_id","name","unit","price"], allm)
                    st.success("Material gelöscht.")

# Signatur-Canvas für Lieferschein (ohne Disclaimer-Text)
def render_signature_only(key_prefix: str):
    canvas = st_canvas(
        fill_color="rgba(0,0,0,0)",
        stroke_width=2,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=120,
        width=400,
        drawing_mode="freedraw",
        key=f"{key_prefix}_canvas"
    )
    has_sig = False
    png_bytes = None
    if canvas and hasattr(canvas, "image_data") and canvas.image_data is not None:
        try:
            import numpy as np
            has_sig = np.any(canvas.image_data[:,:,3] > 0)
            if has_sig:
                from PIL import Image
                img = Image.fromarray(canvas.image_data.astype("uint8"))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
        except Exception:
            has_sig = False
            png_bytes = None
    return has_sig, png_bytes

# ----------------------------- Einstieg / Routing -----------------------------
def topbar():
    with st.sidebar:
        st.markdown("## Navigation")
        role = st.session_state.get("auth_role", None)
        if role == "admin":
            st.success("Admin eingeloggt")
            if st.button("Abmelden", key="logout_admin"):
                for k in ["auth_role","admin_email"]:
                    st.session_state.pop(k, None)
                st.rerun()
        elif role == "supplier":
            st.info("Lieferant eingeloggt")
            if st.button("Abmelden", key="logout_sup"):
                for k in ["auth_role","supplier_id"]:
                    st.session_state.pop(k, None)
                st.rerun()
        else:
            st.write("Bitte einloggen oder registrieren.")

def main():
    ensure_dirs()
    st.set_page_config(page_title=APP_TITLE, page_icon="🌿", layout="wide")
    app_header()
    topbar()

    role = st.session_state.get("auth_role", None)
    if role == "admin":
        admin_area()
    elif role == "supplier":
        supplier_area(st.session_state.get("supplier_id"))
    else:
        st.markdown("Willkommen! Bitte nutzen Sie die Tabs unten.")
        auth_tabs()

if __name__ == "__main__":
    main()
