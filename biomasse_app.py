import os
import io
import csv
import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime
from uuid import uuid4

import numpy as np
import pandas as pd
from PIL import Image

import streamlit as st
from streamlit_drawable_canvas import st_canvas
from fpdf import FPDF


# ===================== Grund-Setup / Styling =====================

APP_TITLE = "Biomasse Abrechnungs-App"
ADMIN_PIN = "8319"  # Auf Wunsch fix im Code
DATA_ROOT = "data"
SUPPLIERS_FILE = os.path.join(DATA_ROOT, "suppliers.csv")
USERS_FILE = os.path.join(DATA_ROOT, "users.csv")  # (Optional für spätere Erweiterungen)
CUSTOMERS_FILE = os.path.join(DATA_ROOT, "customers.csv")
MATERIALS_FILE = os.path.join(DATA_ROOT, "materials.csv")
DELIVERY_FILE = os.path.join(DATA_ROOT, "deliveries.csv")
REG_PDFS_DIR = os.path.join(DATA_ROOT, "registrations")
DELIVERY_PDFS_DIR = os.path.join(DATA_ROOT, "lieferscheine")
LOGO_PATH = "logo.png"  # bitte ins Repo-Root legen

THEME_PRIMARY = "#198754"  # grüner Akzent (Bootstrap success)
THEME_BG = "#0b1727"
THEME_CARD = "#121f33"
THEME_TEXT = "#f1f5f9"

st.set_page_config(page_title=APP_TITLE, page_icon="🟢", layout="wide")

# Custom CSS
st.markdown(
    f"""
    <style>
      .stApp {{
        background: radial-gradient(1200px 600px at 20% 0%, #0f1e33 0%, {THEME_BG} 60%);
        color: {THEME_TEXT};
      }}
      .app-card {{
        background: {THEME_CARD};
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 18px;
        padding: 18px 18px 6px 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.25);
      }}
      .accent {{
        color: {THEME_PRIMARY};
        font-weight: 700;
      }}
      .muted {{
        color: #9fb3c8;
      }}
      .stTabs [data-baseweb="tab-list"] button {{
        background: transparent;
        border: 1px solid rgba(255,255,255,.12);
        border-bottom: none;
        border-radius: 10px 10px 0 0;
        margin-right: 8px;
      }}
      .stTabs [aria-selected="true"] {{
        background: {THEME_CARD};
        color: {THEME_TEXT};
        border-bottom: 2px solid {THEME_PRIMARY} !important;
      }}
      .stButton>button {{
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,.15);
      }}
      .good {{ color: #22c55e; font-weight: 600; }}
      .bad {{ color: #ef4444; font-weight: 600; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ===================== Hilfsfunktionen (Dateien/CSV) =====================

def ensure_dirs():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(REG_PDFS_DIR, exist_ok=True)
    os.makedirs(DELIVERY_PDFS_DIR, exist_ok=True)


def load_csv(path, headers):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
        return pd.DataFrame(columns=headers)
    try:
        df = pd.read_csv(path, dtype=str)
        if set(headers) - set(df.columns):
            # Spalten eines Altbestands ergänzen
            for col in headers:
                if col not in df.columns:
                    df[col] = ""
            df = df[headers]
        return df
    except Exception:
        return pd.DataFrame(columns=headers)


def save_csv(path, df):
    df.to_csv(path, index=False)


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def check_password(pw: str, pw_hash: str) -> bool:
    return hash_password(pw) == pw_hash


def new_id(prefix="ID"):
    return f"{prefix}_{uuid4().hex[:8]}"


# ===================== E-Mail Versand =====================

def send_email(subject: str, body: str, to: list, attachments: list = None):
    """
    attachments: list of tuples (filename, bytes, mime)
    Secrets-Struktur (Streamlit Cloud → Settings → Secrets):
    [smtp]
    host=""
    port=465
    user=""
    password=""
    use_ssl=true
    from=""
    """
    try:
        smtp_conf = st.secrets["smtp"]
        host = smtp_conf.get("host", "")
        port = int(smtp_conf.get("port", 465))
        user = smtp_conf.get("user", "")
        pwd = smtp_conf.get("password", "")
        use_ssl = bool(smtp_conf.get("use_ssl", True))
        mail_from = smtp_conf.get("from", user)
    except Exception:
        st.info("ℹ️ Kein SMTP in Secrets konfiguriert – E-Mail-Versand wird übersprungen.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(to)
    msg.set_content(body)

    if attachments:
        for fname, data, mime in attachments:
            maintype, subtype = mime.split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                if user:
                    server.login(user, pwd)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                if user:
                    server.login(user, pwd)
                server.send_message(msg)
        return True
    except Exception as e:
        st.warning(f"⚠️ E-Mail konnte nicht gesendet werden: {e}")
        return False


# ===================== Signatur / Canvas Hilfen =====================

def canvas_signature(label: str, key: str, height: int = 140):
    st.caption(label)
    can = st_canvas(
        fill_color="rgba(255,255,255,0)",
        stroke_width=2,
        stroke_color="#000000",
        background_color="#FFFFFF",
        height=height,
        width=600,
        drawing_mode="freedraw",
        key=key,
    )
    # can.image_data ist ein np.ndarray oder None
    if can is None or getattr(can, "image_data", None) is None:
        return None
    arr = can.image_data
    # prüfen ob überhaupt „Striche“ vorhanden sind (irgendetwas ≠ weiß)
    try:
        if isinstance(arr, np.ndarray) and np.any(arr[:, :, 3] > 0):  # Alpha-Kanal genutzt
            # In PIL Bild konvertieren (RGBA -> RGB mit weißem Hintergrund)
            pil = Image.fromarray(arr.astype("uint8"), mode="RGBA")
            bg = Image.new("RGB", pil.size, (255, 255, 255))
            bg.paste(pil, mask=pil.split()[3])
            return bg
        else:
            return None
    except Exception:
        return None


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===================== PDF Generatoren =====================

class SimplePDF(FPDF):
    def header(self):
        if os.path.exists(LOGO_PATH):
            try:
                self.image(LOGO_PATH, 10, 8, 22)
            except Exception:
                pass
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Biomasse Abrechnungs-System", ln=True, align="R")
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Arial", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Seite {self.page_no()}", align="C")


def export_pdf_with_signature(pdf: SimplePDF, sig_img: Image.Image | None, x: int, w: int, label: str):
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 8, label, ln=True)
    if sig_img:
        # temporär speichern
        tmp = os.path.join(DATA_ROOT, f"sig_{uuid4().hex[:6]}.png")
        os.makedirs(DATA_ROOT, exist_ok=True)
        try:
            sig_img.save(tmp)
            pdf.image(tmp, x=x, y=pdf.get_y() + 2, w=w)
            pdf.ln(int(w * 0.6) + 6)
        except Exception:
            pdf.ln(8)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    else:
        pdf.ln(8)


def pdf_registration(reg: dict, sig_img: Image.Image | None) -> bytes:
    pdf = SimplePDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 10, "Neuanmeldung Lieferant (Haftungsausschluss)", ln=True)
    pdf.set_font("Arial", "", 11)

    pdf.cell(0, 8, f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}", ln=True)
    for k in ["firma", "email", "telefon", "adresse"]:
        pdf.cell(0, 8, f"{k.capitalize()}: {reg.get(k, '')}", ln=True)

    pdf.ln(4)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Haftungsausschluss:", ln=True)
    pdf.set_font("Arial", "", 11)
    disclaimer = (
        "Der/die Anmeldende erklärt, dass alle gemachten Angaben richtig sind. "
        "Die Nutzung der App erfolgt auf eigene Verantwortung. Der Betreiber "
        "(Lotmar Riedl) übernimmt – soweit gesetzlich zulässig – keine Haftung "
        "für mittelbare oder unmittelbare Schäden, Datenverluste oder entgangenen "
        "Gewinn. Es gelten österreichisches Recht und die zwingenden Bestimmungen "
        "des Verbraucherrechts der EU. Mit Abgabe der Unterschrift wird der "
        "Haftungsausschluss akzeptiert."
    )
    pdf.multi_cell(0, 6, disclaimer)

    pdf.ln(6)
    export_pdf_with_signature(pdf, sig_img, x=18, w=70, label="Unterschrift (Antragsteller/in):")

    # Bytes zurückgeben
    out = io.BytesIO()
    pdf.output(out)
    return out.getvalue()


def pdf_delivery(d: dict, sig_customer: Image.Image | None, sig_supplier: Image.Image | None) -> bytes:
    pdf = SimplePDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 10, "Lieferschein / Biomasse", ln=True)
    pdf.set_font("Arial", "", 11)

    for label, key in [
        ("Nummer", "delivery_id"),
        ("Datum/Zeit", "ts"),
        ("Lieferant", "supplier"),
        ("Kunde", "customer"),
        ("Material", "material"),
        ("Menge", "amount"),
        ("Einheit", "unit"),
        ("Preis/Einheit", "price"),
        ("Summe", "total"),
    ]:
        pdf.cell(0, 8, f"{label}: {d.get(key, '')}", ln=True)

    pdf.ln(4)
    export_pdf_with_signature(pdf, sig_supplier, x=18, w=60, label="Unterschrift Lieferant:")
    export_pdf_with_signature(pdf, sig_customer, x=18, w=60, label="Unterschrift Kunde:")

    out = io.BytesIO()
    pdf.output(out)
    return out.getvalue()


# ===================== Daten-Schichten =====================

def db_get_suppliers():
    return load_csv(SUPPLIERS_FILE, ["supplier_id", "firma", "email", "telefon", "adresse", "pw_hash", "status", "created"])


def db_save_suppliers(df):
    save_csv(SUPPLIERS_FILE, df)


def db_get_customers():
    return load_csv(CUSTOMERS_FILE, ["customer_id", "supplier_id", "name", "adresse", "email", "telefon"])


def db_save_customers(df):
    save_csv(CUSTOMERS_FILE, df)


def db_get_materials():
    return load_csv(MATERIALS_FILE, ["material_id", "supplier_id", "customer_id", "name", "einheit", "preis"])


def db_save_materials(df):
    save_csv(MATERIALS_FILE, df)


def db_get_deliveries():
    return load_csv(DELIVERY_FILE, ["delivery_id", "supplier_id", "customer_id", "material", "amount", "unit", "price", "total", "ts"])


def db_save_deliveries(df):
    save_csv(DELIVERY_FILE, df)


# ===================== UI Bausteine =====================

def app_header():
    cols = st.columns([1, 6, 1])
    with cols[0]:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, use_container_width=True)
    with cols[1]:
        st.markdown(f"<h2 style='margin-bottom:3px;'>{APP_TITLE}</h2>", unsafe_allow_html=True)
        st.markdown("<div class='muted'>Abrechnung • Lieferscheine • Kunden & Materialien</div>", unsafe_allow_html=True)
    with cols[2]:
        st.markdown(f"<div style='text-align:right;'>🟢 <span class='accent'>Online</span></div>", unsafe_allow_html=True)
    st.markdown("<hr style='opacity:.15;'>", unsafe_allow_html=True)


def info_box(title, body):
    with st.container():
        st.markdown(f"<div class='app-card'><div class='accent'>{title}</div><div class='muted' style='margin-top:6px;'>{body}</div></div>", unsafe_allow_html=True)


# ===================== Auth / Registrierung =====================

def auth_tabs():
    st.subheader("Anmeldung & Registrierung")

    tab_login, tab_register, tab_admin = st.tabs(["Lieferanten-Login", "Lieferant neu anmelden", "Admin-Login"])

    # ---- Lieferanten-Login
    with tab_login:
        st.markdown("#### Lieferanten-Login")
        le = st.text_input("E-Mail", key="login_email")
        lp = st.text_input("Passwort", type="password", key="login_pw")
        if st.button("Einloggen", key="btn_login"):
            sup = db_get_suppliers()
            row = sup.loc[sup["email"] == le].head(1)
            if row.empty:
                st.error("E-Mail nicht gefunden.")
            else:
                row = row.iloc[0]
                if row["status"] != "active":
                    st.warning("Noch nicht freigeschaltet. Bitte warten, bis der Admin dich aktiviert.")
                elif not check_password(lp, row["pw_hash"]):
                    st.error("Passwort falsch.")
                else:
                    st.session_state["role"] = "supplier"
                    st.session_state["supplier_id"] = row["supplier_id"]
                    st.session_state["supplier_email"] = row["email"]
                    st.success("Login erfolgreich.")

    # ---- Lieferanten-Neuanmeldung (mit Disclaimer + Unterschrift + PDF + E-Mail)
    with tab_register:
        st.markdown("#### Lieferant neu anmelden")
        firma = st.text_input("Firmenname", key="reg_firma")
        email = st.text_input("E-Mail", key="reg_email")
        telefon = st.text_input("Telefon", key="reg_tel")
        adresse = st.text_input("Adresse", key="reg_addr")
        pw1 = st.text_input("Passwort", type="password", key="reg_pw1")
        pw2 = st.text_input("Passwort wiederholen", type="password", key="reg_pw2")

        st.markdown("**Haftungsausschluss** (EU/Österreich):")
        st.markdown(
            "Mit der Registrierung bestätige ich die Richtigkeit meiner Angaben und akzeptiere den "
            "Haftungsausschluss. Die Nutzung erfolgt auf eigene Verantwortung. Es gelten österreichisches Recht "
            "und die zwingenden Bestimmungen des EU-Verbraucherrechts."
        )
        accepted = st.checkbox("Ich akzeptiere den Haftungsausschluss.", key="reg_accept")

        sig = canvas_signature("Bitte hier unterschreiben:", key="reg_sig")

        if st.button("Antrag absenden", key="btn_reg_submit"):
            if not all([firma.strip(), email.strip(), pw1.strip(), pw2.strip()]):
                st.error("Bitte alle Pflichtfelder ausfüllen.")
            elif pw1 != pw2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accepted:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            elif sig is None:
                st.error("Bitte Unterschrift zeichnen.")
            else:
                sup = db_get_suppliers()
                if (sup["email"] == email).any():
                    st.error("Diese E-Mail ist bereits registriert.")
                else:
                    sid = new_id("SUPP")
                    new_row = {
                        "supplier_id": sid,
                        "firma": firma,
                        "email": email,
                        "telefon": telefon,
                        "adresse": adresse,
                        "pw_hash": hash_password(pw1),
                        "status": "pending",
                        "created": datetime.now().isoformat(timespec="seconds"),
                    }
                    sup = pd.concat([sup, pd.DataFrame([new_row])], ignore_index=True)
                    db_save_suppliers(sup)

                    # PDF bauen
                    pdf_bytes = pdf_registration(
                        {"firma": firma, "email": email, "telefon": telefon, "adresse": adresse},
                        sig
                    )
                    os.makedirs(REG_PDFS_DIR, exist_ok=True)
                    pdf_name = f"registrierung_{sid}.pdf"
                    with open(os.path.join(REG_PDFS_DIR, pdf_name), "wb") as f:
                        f.write(pdf_bytes)

                    # E-Mail an Admin & Antragsteller
                    subject = "Neue Lieferanten-Registrierung (Biomasse-App)"
                    body = (
                        f"Neue Registrierung eingegangen:\n\n"
                        f"Firma: {firma}\nE-Mail: {email}\nTelefon: {telefon}\nAdresse: {adresse}\n\n"
                        f"Bitte im Admin-Bereich freischalten."
                    )
                    attachments = [(pdf_name, pdf_bytes, "application/pdf")]
                    send_email(subject, body, ["app.biomasse@gmail.com", email], attachments)

                    st.success("Antrag eingereicht. Der Admin wird dich freischalten. PDF wurde per E-Mail versendet.")

    # ---- Admin-Login (E-Mail + PIN)
    with tab_admin:
        st.markdown("#### Admin-Login")
        admin_email = st.text_input("Admin-E-Mail", key="adm_email")
        admin_pin = st.text_input("Admin-PIN", type="password", key="adm_pin")
        if st.button("Admin einloggen", key="btn_admin_login"):
            if admin_pin == ADMIN_PIN and admin_email.strip():
                st.session_state["role"] = "admin"
                st.session_state["admin_email"] = admin_email.strip()
                st.success("Admin erfolgreich angemeldet.")
            else:
                st.error("Falsche PIN oder E-Mail leer.")


# ===================== Admin-Bereich =====================

def admin_area():
    st.subheader("Admin-Bereich")
    sup = db_get_suppliers()

    pending = sup.loc[sup["status"] == "pending"]
    active = sup.loc[sup["status"] == "active"]

    st.markdown("##### Ausstehende Anträge")
    if pending.empty:
        st.info("Keine ausstehenden Anträge.")
    else:
        for _, row in pending.iterrows():
            with st.container():
                st.markdown("<div class='app-card'>", unsafe_allow_html=True)
                cols = st.columns([3, 3, 3, 1.5, 1.5])
                cols[0].markdown(f"**Firma:** {row['firma']}  \n**E-Mail:** {row['email']}")
                cols[1].markdown(f"**Telefon:** {row['telefon']}  \n**Adresse:** {row['adresse']}")
                cols[2].markdown(f"**Angelegt:** {row['created']}  \n**Status:** {row['status']}")
                if cols[3].button("Annehmen", key=f"accept_{row['supplier_id']}"):
                    sup.loc[sup["supplier_id"] == row["supplier_id"], "status"] = "active"
                    db_save_suppliers(sup)
                    send_email(
                        "Freischaltung Biomasse-App",
                        "Dein Zugang wurde freigeschaltet. Bitte erneut einloggen.",
                        [row["email"]],
                    )
                    st.success(f"{row['firma']} freigeschaltet.")
                    st.rerun()
                if cols[4].button("Ablehnen", key=f"reject_{row['supplier_id']}"):
                    sup = sup.loc[sup["supplier_id"] != row["supplier_id"]]
                    db_save_suppliers(sup)
                    send_email(
                        "Antrag abgelehnt (Biomasse-App)",
                        "Leider wurde dein Antrag abgelehnt. Für Rückfragen bitte antworten.",
                        [row["email"]],
                    )
                    st.warning("Antrag abgelehnt und gelöscht.")
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("##### Aktive Lieferanten")
    if active.empty:
        st.info("Keine aktiven Lieferanten.")
    else:
        st.dataframe(active[["supplier_id", "firma", "email", "telefon", "adresse", "created"]], use_container_width=True)

    st.markdown("##### Lieferant löschen (Code-geschützt)")
    del_id = st.text_input("Supplier ID zum Löschen", key="adm_del_id")
    del_code = st.text_input("Bestätigungs-PIN", type="password", key="adm_del_pin")
    if st.button("Lieferant löschen", key="adm_btn_del"):
        if del_code != ADMIN_PIN:
            st.error("PIN falsch.")
        else:
            if (sup["supplier_id"] == del_id).any():
                mail = sup.loc[sup["supplier_id"] == del_id, "email"].iloc[0]
                sup2 = sup.loc[sup["supplier_id"] != del_id]
                db_save_suppliers(sup2)
                # Zugehörige Kunden/Materialien/Lieferscheine entfernen
                cust = db_get_customers()
                mats = db_get_materials()
                dels = db_get_deliveries()
                cust = cust.loc[cust["supplier_id"] != del_id]
                mats = mats.loc[mats["supplier_id"] != del_id]
                dels = dels.loc[dels["supplier_id"] != del_id]
                db_save_customers(cust)
                db_save_materials(mats)
                db_save_deliveries(dels)
                send_email(
                    "Zugang gelöscht (Biomasse-App)",
                    "Dein Zugang wurde vom Admin gelöscht.",
                    [mail],
                )
                st.success("Lieferant und zugehörige Daten gelöscht.")
            else:
                st.warning("Supplier ID nicht gefunden.")


# ===================== Lieferant-Bereich =====================

def supplier_area(supplier_id: str):
    st.subheader("Lieferanten-Bereich")

    tab_kunden, tab_material, tab_lieferschein = st.tabs(["Kunden", "Materialien", "Lieferschein"])

    # ---- Kunden
    with tab_kunden:
        st.markdown("##### Kunden verwalten")
        cust = db_get_customers()
        my = cust.loc[cust["supplier_id"] == supplier_id].copy()

        # Suche
        q = st.text_input("Kunden suchen (Name/Adresse/E-Mail/Telefon)", key="cust_search")
        if q.strip():
            mask = (
                my["name"].str.contains(q, case=False, na=False) |
                my["adresse"].str.contains(q, case=False, na=False) |
                my["email"].str.contains(q, case=False, na=False) |
                my["telefon"].str.contains(q, case=False, na=False)
            )
            my = my.loc[mask]

        st.dataframe(my[["customer_id", "name", "adresse", "email", "telefon"]], use_container_width=True)

        st.markdown("**Neuen Kunden anlegen**")
        c_name = st.text_input("Name", key="c_new_name")
        c_addr = st.text_input("Adresse", key="c_new_addr")
        c_mail = st.text_input("E-Mail", key="c_new_mail")
        c_tel = st.text_input("Telefon", key="c_new_tel")
        if st.button("Kunde anlegen", key="btn_create_cust"):
            if not c_name.strip():
                st.error("Name fehlt.")
            else:
                row = {
                    "customer_id": new_id("CUST"),
                    "supplier_id": supplier_id,
                    "name": c_name.strip(),
                    "adresse": c_addr.strip(),
                    "email": c_mail.strip(),
                    "telefon": c_tel.strip(),
                }
                cust = pd.concat([cust, pd.DataFrame([row])], ignore_index=True)
                db_save_customers(cust)
                st.success("Kunde angelegt.")
                st.rerun()

        st.markdown("**Kunde löschen**")
        del_cust = st.text_input("Customer ID", key="cust_del_id")
        if st.button("Kunde löschen", key="btn_del_cust"):
            cust2 = db_get_customers()
            if (cust2["customer_id"] == del_cust).any() and (cust2.loc[cust2["customer_id"] == del_cust, "supplier_id"].iloc[0] == supplier_id):
                cust2 = cust2.loc[cust2["customer_id"] != del_cust]
                db_save_customers(cust2)
                # zugehörige Materialien mit customer_id löschen
                mats = db_get_materials()
                mats = mats.loc[mats["customer_id"] != del_cust]
                db_save_materials(mats)
                st.success("Kunde (und zugehörige Materialien) gelöscht.")
                st.rerun()
            else:
                st.warning("Customer ID nicht gefunden oder gehört dir nicht.")

    # ---- Materialien
    with tab_material:
        st.markdown("##### Materialien pro Kunde")
        cust = db_get_customers()
        mats = db_get_materials()

        my_c = cust.loc[cust["supplier_id"] == supplier_id]
        if my_c.empty:
            st.info("Bitte zuerst einen Kunden anlegen.")
        else:
            sel_cust_name = st.selectbox(
                "Kunde auswählen",
                my_c["name"].tolist(),
                key="mat_sel_cust"
            )
            sel_cust_id = my_c.loc[my_c["name"] == sel_cust_name, "customer_id"].iloc[0]
            my_mats = mats.loc[(mats["supplier_id"] == supplier_id) & (mats["customer_id"] == sel_cust_id)]

            st.dataframe(my_mats[["material_id", "name", "einheit", "preis"]], use_container_width=True)

            st.markdown("**Material hinzufügen/ändern**")
            m_name = st.text_input("Materialname", key="mat_name")
            m_unit = st.selectbox("Einheit", ["m³", "t", "kg"], key="mat_unit")
            m_price = st.text_input("Preis pro Einheit (€)", key="mat_price")

            if st.button("Material speichern", key="btn_mat_save"):
                if not m_name.strip():
                    st.error("Materialname fehlt.")
                else:
                    # Prüfen ob Material schon existiert (Name + Kunde)
                    exists = my_mats.loc[my_mats["name"].str.lower() == m_name.strip().lower()]
                    if exists.empty:
                        new_row = {
                            "material_id": new_id("MAT"),
                            "supplier_id": supplier_id,
                            "customer_id": sel_cust_id,
                            "name": m_name.strip(),
                            "einheit": m_unit,
                            "preis": m_price.strip(),
                        }
                        mats = pd.concat([mats, pd.DataFrame([new_row])], ignore_index=True)
                        db_save_materials(mats)
                        st.success("Material hinzugefügt.")
                    else:
                        # Update Preis/Einheit
                        idx = exists.index[0]
                        mats.loc[idx, "einheit"] = m_unit
                        mats.loc[idx, "preis"] = m_price.strip()
                        db_save_materials(mats)
                        st.success("Material aktualisiert.")
                    st.rerun()

            st.markdown("**Material löschen**")
            del_mat = st.text_input("Material ID", key="mat_del_id")
            if st.button("Material löschen", key="btn_del_mat"):
                mats2 = db_get_materials()
                if (mats2["material_id"] == del_mat).any() and (mats2.loc[mats2["material_id"] == del_mat, "supplier_id"].iloc[0] == supplier_id):
                    mats2 = mats2.loc[mats2["material_id"] != del_mat]
                    db_save_materials(mats2)
                    st.success("Material gelöscht.")
                    st.rerun()
                else:
                    st.warning("Material ID nicht gefunden oder gehört dir nicht.")

    # ---- Lieferschein
    with tab_lieferschein:
        st.markdown("##### Lieferschein erfassen")

        cust = db_get_customers()
        mats = db_get_materials()

        my_c = cust.loc[cust["supplier_id"] == supplier_id]
        if my_c.empty:
            st.info("Bitte zuerst Kunden anlegen.")
            return

        c_name = st.selectbox("Kunde", my_c["name"].tolist(), key="dlv_cust")
        c_id = my_c.loc[my_c["name"] == c_name, "customer_id"].iloc[0]
        my_mats = mats.loc[(mats["supplier_id"] == supplier_id) & (mats["customer_id"] == c_id)]

        if my_mats.empty:
            st.info("Für diesen Kunden sind noch keine Materialien hinterlegt.")
            return

        m_name = st.selectbox("Material", my_mats["name"].tolist(), key="dlv_mat")
        m_row = my_mats.loc[my_mats["name"] == m_name].iloc[0]
        unit = st.selectbox("Einheit", ["m³", "t", "kg"], index=["m³", "t", "kg"].index(m_row["einheit"]), key="dlv_unit")
        price = st.text_input("Preis/Einheit (€)", value=str(m_row["preis"]), key="dlv_price")

        colA, colB = st.columns(2)
        with colA:
            amount = st.text_input("Menge (Zahl)", key="dlv_amount")
        with colB:
            st.caption("Optional statt Menge: Voll/Leer Gewicht")
            voll = st.text_input("Voll (kg)", key="dlv_voll")
            leer = st.text_input("Leer (kg)", key="dlv_leer")

        st.markdown("**Unterschriften**")
        sig_sup = canvas_signature("Lieferant unterschreibt hier:", key="sig_supplier")
        sig_cus = canvas_signature("Kunde unterschreibt hier:", key="sig_customer")

        if st.button("Lieferschein speichern (PDF & E-Mail)", key="btn_dlv_save"):
            # Menge ermitteln
            qty = None
            try:
                if amount.strip():
                    qty = float(amount.replace(",", "."))
                elif voll.strip() and leer.strip():
                    qty = max(0.0, float(voll.replace(",", ".")) - float(leer.replace(",", ".")))
                    # wenn Einheit kg/t: bei t ggf. /1000
                    if unit == "t":
                        qty = qty / 1000.0
                else:
                    st.error("Bitte Menge eingeben oder Voll/Leer angeben.")
                    return
            except Exception:
                st.error("Mengenangaben ungültig.")
                return

            try:
                pr = float(str(price).replace(",", "."))
            except Exception:
                st.error("Preis ungültig.")
                return

            total = round(qty * pr, 2)
            delivery_id = new_id("DLV")
            ts = datetime.now().strftime("%d.%m.%Y %H:%M")

            # Speichern in CSV
            dels = db_get_deliveries()
            row = {
                "delivery_id": delivery_id,
                "supplier_id": supplier_id,
                "customer_id": c_id,
                "material": m_name,
                "amount": f"{qty}",
                "unit": unit,
                "price": f"{pr}",
                "total": f"{total}",
                "ts": ts,
            }
            dels = pd.concat([dels, pd.DataFrame([row])], ignore_index=True)
            db_save_deliveries(dels)

            # PDF
            pdf_bytes = pdf_delivery(
                {
                    "delivery_id": delivery_id,
                    "supplier": st.session_state.get("supplier_email", supplier_id),
                    "customer": c_name,
                    "material": m_name,
                    "amount": f"{qty}",
                    "unit": unit,
                    "price": f"{pr} €",
                    "total": f"{total} €",
                    "ts": ts,
                },
                sig_customer=sig_cus,
                sig_supplier=sig_sup
            )
            os.makedirs(DELIVERY_PDFS_DIR, exist_ok=True)
            pdf_name = f"lieferschein_{delivery_id}.pdf"
            with open(os.path.join(DELIVERY_PDFS_DIR, pdf_name), "wb") as f:
                f.write(pdf_bytes)

            # Mail (an Lieferant + optional Kunde)
            cust_df = db_get_customers()
            cust_mail = cust_df.loc[cust_df["customer_id"] == c_id, "email"].iloc[0]
            to_list = [st.session_state.get("supplier_email", "")]
            if cust_mail:
                to_list.append(cust_mail)
            send_email(
                subject=f"Lieferschein {delivery_id}",
                body=f"Lieferschein {delivery_id} angehängt.",
                to=to_list,
                attachments=[(pdf_name, pdf_bytes, "application/pdf")]
            )

            st.success(f"Lieferschein gespeichert. Summe: {total:.2f} €")
            st.download_button("PDF herunterladen", data=pdf_bytes, file_name=pdf_name, mime="application/pdf", key=f"dl_{delivery_id}")


# ===================== Haupt-Routing =====================

def main():
    ensure_dirs()
    app_header()

    role = st.session_state.get("role")

    if not role:
        # Startseite / Hinweise
        info_box("Willkommen!", "Melde dich als Lieferant an, registriere dich neu oder gehe in den Admin-Bereich.")
        auth_tabs()
        return

    if role == "admin":
        admin_area()
    elif role == "supplier":
        supplier_id = st.session_state.get("supplier_id")
        if not supplier_id:
            st.warning("Session abgelaufen. Bitte erneut einloggen.")
            st.session_state.clear()
            st.rerun()
        supplier_area(supplier_id)

    # Sidebar: Logout
    with st.sidebar:
        st.markdown("### Navigation")
        if role:
            st.info(f"Eingeloggt als: **{role}**")
            if st.button("Logout", key="btn_logout"):
                st.session_state.clear()
                st.rerun()

    # Fußbereich – kurze Datenschutzinfo
    st.markdown("<hr style='opacity:.15;'>", unsafe_allow_html=True)
    st.caption(
        "Datenschutzhinweis: Es werden nur zur Abrechnung notwendige Daten gespeichert. "
        "PDFs und CSVs liegen im App-Speicher. E-Mails gehen ausschließlich an Beteiligte."
    )


if __name__ == "__main__":
    main()
