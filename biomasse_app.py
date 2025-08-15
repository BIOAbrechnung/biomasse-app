import os
import io
import hashlib
import smtplib
from email.message import EmailMessage
from datetime import datetime

import numpy as np
import pandas as pd
from PIL import Image
from fpdf import FPDF

import streamlit as st
from streamlit_drawable_canvas import st_canvas

# ===================== Basis-Pfade & Dateien =====================
DATA_ROOT = "data"
USERS_FILE = os.path.join(DATA_ROOT, "users.csv")
CUSTOMERS_FILE = os.path.join(DATA_ROOT, "customers.csv")
MATERIALS_FILE = os.path.join(DATA_ROOT, "materials.csv")
DOCS_DIR = os.path.join(DATA_ROOT, "docs")

def ensure_dirs():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

# ===================== CSV I/O =====================
def load_csv(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(path)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def save_csv(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

# ===================== Sicherheit =====================
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

ADMIN_PIN = st.secrets.get("admin_pin", "8319")  # globaler Admin-PIN, per Secrets überschreibbar

# ===================== E-Mail Versand =====================
def send_email_with_pdf(subject, body, to_addrs, pdf_bytes, pdf_filename):
    """
    SMTP via st.secrets["smtp"]:
      host, port, user, password, from
    Wenn Secrets fehlen → nur Hinweis, kein Abbruch.
    """
    smtp_cfg = st.secrets.get("smtp", None)
    if not smtp_cfg:
        st.info("Hinweis: SMTP ist nicht konfiguriert (st.secrets['smtp']). E-Mail wird übersprungen.")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_cfg.get("from", smtp_cfg.get("user"))
        msg["To"] = ", ".join(to_addrs if isinstance(to_addrs, list) else [to_addrs])
        msg.set_content(body)
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=pdf_filename)

        with smtplib.SMTP(smtp_cfg["host"], smtp_cfg.get("port", 587)) as s:
            s.starttls()
            s.login(smtp_cfg["user"], smtp_cfg["password"])
            s.send_message(msg)
        return True
    except Exception as e:
        st.warning(f"E-Mail konnte nicht gesendet werden: {e}")
        return False

# ===================== Haftung + PDF =====================
DISCLAIMER_TEXT = """\
Haftungsausschluss / Einverständniserklärung

Ich bestätige, dass ich die Biomasse-Abrechnungs-App in eigener Verantwortung nutze.
Es erfolgt keine Rechts- oder Steuerberatung. Für Vollständigkeit, Richtigkeit,
Verfügbarkeit und Eignung der App wird keine Haftung übernommen. Die Datenverarbeitung
erfolgt gemäß den geltenden Datenschutzbestimmungen (EU/Österreich).

Ich stimme zu, dass meine Registrierungsdaten (E-Mail) und diese Zustimmung
zwecks Prüfung, Freischaltung und Nachweis verarbeitet und gespeichert werden.
Die Zustimmung kann ich jederzeit mit Wirkung für die Zukunft widerrufen.
"""

def disclaimer_pdf_bytes(name_or_email: str, signature_img: Image.Image) -> bytes:
    """Erzeugt PDF mit Haftungstext + Unterschrift als Bytes."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Haftungsausschluss / Einverständnis", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 6, DISCLAIMER_TEXT)
    pdf.ln(6)
    pdf.cell(0, 8, f"Registriert von: {name_or_email}", ln=True)
    pdf.cell(0, 8, f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", ln=True)
    pdf.ln(4)
    pdf.cell(0, 8, "Unterschrift:", ln=True)

    # Signatur als PNG temporär speichern und in PDF einbetten
    bio = io.BytesIO()
    signature_img.save(bio, format="PNG")
    bio.seek(0)
    tmp_path = os.path.join(DATA_ROOT, "sig_tmp.png")
    with open(tmp_path, "wb") as f:
        f.write(bio.read())
    try:
        y = pdf.get_y() + 2
        pdf.image(tmp_path, x=20, y=y, w=70)
        pdf.ln(40)
    except Exception:
        pass

    out = io.BytesIO()
    pdf.output(out)
    return out.getvalue()

# ===================== Canvas / Signatur =====================
def is_canvas_drawn(canvas_result) -> bool:
    """True, wenn auf dem Canvas Pixel mit Alpha > 0 vorhanden sind."""
    if not canvas_result or not hasattr(canvas_result, "image_data") or canvas_result.image_data is None:
        return False
    arr = canvas_result.image_data
    if not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] < 4:
        return False
    return bool(np.any(arr[:, :, 3] > 0))

def canvas_to_pil(canvas_result) -> Image.Image:
    """Konvertiert RGBA-Array vom Canvas zu PIL RGB-Image."""
    arr = canvas_result.image_data.astype("uint8")
    img_rgba = Image.fromarray(arr, mode="RGBA")
    return img_rgba.convert("RGB")

# ===================== Session Helpers =====================
def get_session_user():
    return st.session_state.get("user", None)

def set_session_user(user_dict):
    st.session_state["user"] = user_dict

def logout():
    if "user" in st.session_state:
        del st.session_state["user"]

# ===================== UI Styling =====================
def inject_css():
    st.markdown("""
    <style>
      .hero {
        padding: 18px 22px;
        border-radius: 12px;
        background: linear-gradient(135deg,#054b2e 0%, #0b8f57 70%, #16c172 100%);
        color: #fff;
        margin-bottom: 16px;
      }
      .hero h1 { margin: 0 0 6px 0; font-size: 28px; }
      .hero p  { margin: 0; opacity: .95; }
      .card {
        border: 1px solid #e6e6e6;
        border-radius: 10px;
        padding: 14px 16px;
        background: #ffffffcc;
        margin: 6px 0 10px 0;
      }
      .muted { color:#5c6b6b; font-size: 13px; }
      .stButton>button {
        border-radius: 8px;
        padding: 0.4rem 0.9rem;
        font-weight: 600;
      }
      .ok { background:#0ea765 !important; color:white !important; border:none; }
      .warn { background:#ef4444 !important; color:white !important; border:none; }
    </style>
    """, unsafe_allow_html=True)

def hero_header(subtitle=""):
    st.markdown('<div class="hero"><h1>🌿 Biomasse Abrechnungs-App</h1>'
                f'<p>{subtitle}</p></div>', unsafe_allow_html=True)

# ===================== Auth Tabs =====================
def auth_tabs():
    hero_header("Login, Neu-Anmeldung & Admin-Freigabe")
    tabs = st.tabs(["🔑 Login", "📝 Neu anmelden", "🛡️ Admin-Login"])

    # ------- Login -------
    with tabs[0]:
        st.markdown('<div class="card"><b>Lieferanten-Login</b><div class="muted">Bitte E-Mail und Passwort eingeben.</div></div>', unsafe_allow_html=True)
        email = st.text_input("E-Mail")
        pw = st.text_input("Passwort", type="password")
        colA, colB = st.columns([1,3])
        with colA:
            if st.button("Einloggen"):
                users = load_csv(USERS_FILE, ["email","pass_hash","status","role"])
                row = users[users["email"] == email]
                if row.empty:
                    st.error("E-Mail nicht gefunden.")
                else:
                    if row.iloc[0]["status"] != "active":
                        st.warning("Konto noch nicht freigeschaltet. Bitte auf Admin-Freigabe warten.")
                    elif row.iloc[0]["pass_hash"] != hash_pw(pw):
                        st.error("Passwort falsch.")
                    else:
                        set_session_user({"email": email, "role": row.iloc[0].get("role", "supplier")})
                        st.success("Login erfolgreich!")
                        st.rerun()

    # ------- Neu anmelden -------
    with tabs[1]:
        st.markdown('<div class="card"><b>Neu-Anmeldung (Lieferant)</b><div class="muted">Nach dem Einreichen erfolgt Freigabe durch Admin.</div></div>', unsafe_allow_html=True)
        reg_email = st.text_input("E-Mail (Login-Adresse)")
        reg_pw1 = st.text_input("Passwort", type="password")
        reg_pw2 = st.text_input("Passwort wiederholen", type="password")

        st.markdown("**Haftungsausschluss** (bitte lesen und unterschreiben):")
        with st.expander("Text anzeigen"):
            st.write(DISCLAIMER_TEXT)

        accepted = st.checkbox("Ich habe gelesen und akzeptiere den Haftungsausschluss.")
        st.write("Unterschrift (Finger/Maus zeichnen):")
        can = st_canvas(
            fill_color="rgba(255, 255, 255, 0)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=160,
            width=560,
            drawing_mode="freedraw",
            key="reg_canvas",
        )

        if st.button("Registrieren"):
            if not reg_email or not reg_pw1 or not reg_pw2:
                st.error("Bitte E-Mail und Passwort eingeben.")
            elif reg_pw1 != reg_pw2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accepted:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            elif not is_canvas_drawn(can):
                st.error("Bitte Unterschrift zeichnen.")
            else:
                users = load_csv(USERS_FILE, ["email","pass_hash","status","role"])
                if (users["email"] == reg_email).any():
                    st.error("Diese E-Mail ist bereits registriert.")
                else:
                    new = pd.DataFrame([{
                        "email": reg_email,
                        "pass_hash": hash_pw(reg_pw1),
                        "status": "pending",
                        "role": "supplier"
                    }])
                    users = pd.concat([users, new], ignore_index=True)
                    save_csv(users, USERS_FILE)

                    sig_img = canvas_to_pil(can)
                    pdf_bytes = disclaimer_pdf_bytes(reg_email, sig_img)
                    pdf_name = f"Haftung_{reg_email.replace('@','_at_')}.pdf"
                    out_path = os.path.join(DOCS_DIR, pdf_name)
                    with open(out_path, "wb") as f:
                        f.write(pdf_bytes)

                    send_email_with_pdf(
                        subject="Neu-Anmeldung Biomasse-App – Bestätigungseingang",
                        body=(
                            "Danke für Ihre Registrierung.\n\n"
                            "Ihre Daten wurden erhalten und werden geprüft.\n"
                            "Nach Freischaltung durch den Admin können Sie sich einloggen.\n"
                        ),
                        to_addrs=[reg_email, "app.biomasse@gmail.com"],
                        pdf_bytes=pdf_bytes,
                        pdf_filename=pdf_name
                    )

                    st.success("Registrierung eingereicht. Bitte auf Freischaltung warten.")
                    st.info("Hinweis: Für E-Mail-Versand SMTP-Secrets setzen.")

    # ------- Admin-Login -------
    with tabs[2]:
        st.markdown('<div class="card"><b>Admin-Zugang</b><div class="muted">Mit PIN geschützt.</div></div>', unsafe_allow_html=True)
        admin_email = st.text_input("Admin-E-Mail")
        admin_pin = st.text_input("Admin-PIN", type="password")
        if st.button("Als Admin anmelden"):
            if admin_pin == ADMIN_PIN:
                set_session_user({"email": admin_email, "role": "admin"})
                st.success("Admin-Login erfolgreich!")
                st.rerun()
            else:
                st.error("Admin-PIN falsch.")

# ===================== Admin-Bereich =====================
def admin_dashboard():
    hero_header("Admin-Dashboard")
    users = load_csv(USERS_FILE, ["email","pass_hash","status","role"])

    # Offene Anmeldungen
    st.subheader("🕒 Offene Neuanmeldungen")
    pending = users[users["status"] == "pending"].copy()
    if pending.empty:
        st.info("Keine offenen Neuanmeldungen.")
    else:
        for _, row in pending.iterrows():
            c1, c2, c3 = st.columns([3,1,1])
            with c1:
                st.write(f"**{row['email']}** – Status: {row['status']}")
            with c2:
                if st.button("Freischalten ✅", key=f"approve_{row['email']}"):
                    users.loc[users["email"] == row["email"], "status"] = "active"
                    save_csv(users, USERS_FILE)
                    st.success(f"{row['email']} freigeschaltet.")
                    st.rerun()
            with c3:
                if st.button("Ablehnen ❌", key=f"reject_{row['email']}"):
                    users = users[users["email"] != row["email"]].copy()
                    save_csv(users, USERS_FILE)
                    st.warning(f"{row['email']} abgelehnt & entfernt.")
                    st.rerun()

    st.divider()
    st.subheader("👥 Lieferantenverwaltung")
    active = users[(users["role"] == "supplier") & (users["status"] == "active")].copy()
    if active.empty:
        st.write("Keine aktiven Lieferanten.")
    else:
        target = st.selectbox("Lieferant wählen (zum Löschen)", ["–"] + active["email"].tolist())
        pin = st.text_input("Bestätigen mit Admin-PIN", type="password")
        if st.button("Lieferant löschen", help="Entfernt auch dessen Kunden & Materialien"):
            if pin != ADMIN_PIN:
                st.error("Admin-PIN falsch.")
            elif target == "–":
                st.error("Bitte einen Lieferanten wählen.")
            else:
                users = users[users["email"] != target].copy()
                save_csv(users, USERS_FILE)
                customers = load_csv(CUSTOMERS_FILE, ["supplier","customer"])
                materials = load_csv(MATERIALS_FILE, ["supplier","customer","material","price","unit"])
                customers = customers[customers["supplier"] != target]
                materials = materials[materials["supplier"] != target]
                save_csv(customers, CUSTOMERS_FILE)
                save_csv(materials, MATERIALS_FILE)
                st.success(f"Lieferant '{target}' und zugehörige Daten entfernt.")
                st.rerun()

# ===================== Lieferanten-Bereich =====================
def supplier_dashboard(user_email: str):
    hero_header("Lieferanten-Portal")
    st.markdown('<div class="card">Verwalten Sie Ihre Kunden & Materialien, inkl. Preis und Einheit (kg / t / m³).</div>', unsafe_allow_html=True)

    # KPI-Karten
    customers = load_csv(CUSTOMERS_FILE, ["supplier","customer"])
    materials = load_csv(MATERIALS_FILE, ["supplier","customer","material","price","unit"])
    my_customers = customers[customers["supplier"] == user_email].copy()
    my_materials = materials[materials["supplier"] == user_email].copy()

    k1, k2 = st.columns(2)
    with k1:
        st.markdown(f'<div class="card"><b>👥 Kunden</b><div class="muted">{len(my_customers)} Einträge</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="card"><b🧱>🧱 Materialien</b><div class="muted">{len(my_materials)} Einträge</div></div>', unsafe_allow_html=True)

    # --- Kundenliste + Suche ---
    st.subheader("Kunden")
    q = st.text_input("Kunde suchen")
    if q:
        show_customers = my_customers[my_customers["customer"].str.contains(q, case=False, na=False)]
    else:
        show_customers = my_customers

    if show_customers.empty:
        st.info("Noch keine Kunden angelegt.")
    else:
        st.write(", ".join(sorted(show_customers["customer"].unique())))

    col_add1, col_add2 = st.columns([3,1])
    with col_add1:
        new_cust = st.text_input("Neuen Kunden anlegen (Name)")
    with col_add2:
        if st.button("Kunde hinzufügen"):
            if not new_cust.strip():
                st.error("Bitte Kundenname eingeben.")
            else:
                if ((customers["supplier"] == user_email) & (customers["customer"] == new_cust)).any():
                    st.warning("Kunde existiert bereits.")
                else:
                    row = pd.DataFrame([{"supplier": user_email, "customer": new_cust.strip()}])
                    customers = pd.concat([customers, row], ignore_index=True)
                    save_csv(customers, CUSTOMERS_FILE)
                    st.success("Kunde angelegt.")
                    st.rerun()

    st.markdown("---")

    target_customer = st.selectbox("Kunde auswählen", ["–"] + sorted(my_customers["customer"].unique()))
    if target_customer != "–":
        st.subheader(f"Materialien für: {target_customer}")
        my_mat = materials[(materials["supplier"] == user_email) & (materials["customer"] == target_customer)].copy()

        if my_mat.empty:
            st.info("Noch keine Materialien hinterlegt.")
        else:
            st.dataframe(my_mat[["material","price","unit"]].reset_index(drop=True), use_container_width=True)

        with st.form(key="mat_form"):
            material = st.text_input("Materialname (z. B. 'Erdreich', 'Mais-Silage')")
            price = st.number_input("Preis (netto)", min_value=0.0, step=0.01, format="%.2f")
            unit = st.selectbox("Einheit", ["kg", "t", "m3"])
            submitted = st.form_submit_button("Speichern / Aktualisieren")
            if submitted:
                if not material.strip():
                    st.error("Materialname fehlt.")
                else:
                    mask = (
                        (materials["supplier"] == user_email) &
                        (materials["customer"] == target_customer) &
                        (materials["material"] == material)
                    )
                    if mask.any():
                        materials.loc[mask, ["price","unit"]] = [price, unit]
                        msg = "Material aktualisiert."
                    else:
                        row = pd.DataFrame([{
                            "supplier": user_email,
                            "customer": target_customer,
                            "material": material,
                            "price": price,
                            "unit": unit
                        }])
                        materials = pd.concat([materials, row], ignore_index=True)
                        msg = "Material angelegt."
                    save_csv(materials, MATERIALS_FILE)
                    st.success(msg)
                    st.rerun()

        del_mat = st.selectbox("Material löschen", ["–"] + sorted(my_mat["material"].unique()))
        if st.button("Löschen bestätigen", help="Entfernt nur das gewählte Material"):
            if del_mat != "–":
                materials = materials[~(
                    (materials["supplier"] == user_email) &
                    (materials["customer"] == target_customer) &
                    (materials["material"] == del_mat)
                )]
                save_csv(materials, MATERIALS_FILE)
                st.success(f"Material '{del_mat}' gelöscht.")
                st.rerun()

# ===================== App-Routing =====================
def main():
    ensure_dirs()
    st.set_page_config(page_title="Biomasse Abrechnungs-App", page_icon="🌿", layout="wide")
    inject_css()

    with st.sidebar:
        st.markdown("### ℹ️ Info")
        st.markdown(
            "- Zweck: Abrechnung von Biomasse-Lieferungen.\n"
            "- Speicherung: CSV/PDF lokal im App-Projekt.\n"
            "- E-Mail: Versand (falls konfiguriert) nur an Beteiligte via SMTP.\n"
        )
        if st.button("Logout"):
            logout()
            st.rerun()

    user = get_session_user()
    if not user:
        auth_tabs()
        return

    if user["role"] == "admin":
        admin_dashboard()
    else:
        # Nur aktive Nutzer zulassen
        users = load_csv(USERS_FILE, ["email","pass_hash","status","role"])
        row = users[users["email"] == user["email"]]
        if row.empty or row.iloc[0]["status"] != "active":
            st.warning("Konto ist (nicht mehr) freigeschaltet. Bitte Admin kontaktieren.")
            logout()
            st.rerun()
        supplier_dashboard(user["email"])

if __name__ == "__main__":
    main()
