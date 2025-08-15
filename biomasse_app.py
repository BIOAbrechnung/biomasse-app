import os
import io
import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText

import pandas as pd
import numpy as np
from PIL import Image
from datetime import datetime
import streamlit as st
from streamlit_drawable_canvas import st_canvas

# ===================== Grund-Setup & Pfade =====================
st.set_page_config(page_title="Biomasse Abrechnungs-App", page_icon="🌱", layout="wide")

APP_TITLE = "Biomasse Abrechnungs-App"
DATA_ROOT = "data"
USERS_FILE = os.path.join(DATA_ROOT, "suppliers.csv")          # Lieferanten (inkl. Status)
CUSTOMERS_FILE = os.path.join(DATA_ROOT, "customers.csv")      # Kunden
MATERIALS_FILE = os.path.join(DATA_ROOT, "materials.csv")      # Materialien
DELIVERIES_FILE = os.path.join(DATA_ROOT, "deliveries.csv")    # Lieferscheine-CSV
PDF_DIR = os.path.join(DATA_ROOT, "lieferscheine")
TMP_DIR = os.path.join(DATA_ROOT, "tmp")

LOGO_PATH = "logo.png"  # optional; wenn nicht vorhanden, wird automatisch übersprungen

ADMIN_EMAIL = "app.biomasse@gmail.com"   # Admin-Adresse (fix)
ADMIN_PIN = "8319"                        # Admin-PIN (fix)

# GMAIL SMTP (fix eingetragen; du kannst per Secrets überschreiben)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "app.biomasse@gmail.com"
# HIER DEIN GMAIL-APP-PASSWORT EINTRAGEN (16-stellig, NICHT dein normales Gmail-Passwort!)
SMTP_PASS = "HIER_DEIN_APP_PASSWORT_EINTRAGEN"

# Secrets erlauben (falls in Streamlit Cloud gesetzt, überschreibt obige Werte)
if "smtp" in st.secrets:
    SMTP_HOST = st.secrets.smtp.get("host", SMTP_HOST)
    SMTP_PORT = int(st.secrets.smtp.get("port", SMTP_PORT))
    SMTP_USER = st.secrets.smtp.get("user", SMTP_USER)
    SMTP_PASS = st.secrets.smtp.get("password", SMTP_PASS)
if "admin" in st.secrets:
    ADMIN_EMAIL = st.secrets.admin.get("email", ADMIN_EMAIL)
    ADMIN_PIN = st.secrets.admin.get("pin", ADMIN_PIN)

# ===================== Hilfsfunktionen Datei/CSV =====================
def ensure_dirs():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_ROOT, "suppliers"), exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

def load_csv(path, columns):
    if not os.path.exists(path):
        df = pd.DataFrame(columns=columns)
        df.to_csv(path, index=False)
        return df
    try:
        df = pd.read_csv(path)
        # Fehlende Spalten auffüllen
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        return df[columns]
    except Exception:
        return pd.DataFrame(columns=columns)

def save_csv(path, df):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

def to_latin1(text: str) -> str:
    """Erzwingt PDF-kompatible Latin-1-Zeichen (verhindert UnicodeEncodeError)."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return text.encode("latin-1", errors="replace").decode("latin-1")

# ===================== E-Mail Versand =====================
def send_email(subject, body_html, to_addrs, attachments=None):
    """
    Versand über Gmail SMTP.
    to_addrs: str oder Liste
    attachments: Liste von Tupeln (filename, bytes)
    """
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    if attachments:
        for fname, fb in attachments:
            part = MIMEApplication(fb, Name=fname)
            part["Content-Disposition"] = f'attachment; filename="{fname}"'
            msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_addrs, msg.as_string())
        server.quit()
        return True, "E-Mail gesendet."
    except Exception as e:
        return False, f"E-Mail Fehler: {e}"

# ===================== PDF (FPDF2, mit Signatur-Bildern) =====================
from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        # Logo (optional)
        if os.path.exists(LOGO_PATH):
            try:
                self.image(LOGO_PATH, x=10, y=8, w=24)
            except Exception:
                pass
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, to_latin1(APP_TITLE), ln=True, align="R")
        self.ln(5)

def _pdf_bytes(pdf: FPDF) -> bytes:
    """FPDF2: Output als Bytes."""
    return pdf.output(dest="S").encode("latin-1", "replace")

def export_pdf_with_signature(pdf: FPDF, sig_img: Image.Image | None, label: str):
    """
    Signatur (falls vorhanden) unter aktuelle Position einfügen.
    """
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, to_latin1(label), ln=True)
    if sig_img is not None:
        tmp = os.path.join(TMP_DIR, f"sig_{label.replace(' ','_')}.png")
        sig_img.save(tmp)
        try:
            pdf.image(tmp, x=20, y=pdf.get_y()+2, w=60)
            pdf.ln(30)
        except Exception:
            pdf.ln(10)

def pdf_delivery(data: dict, sig_customer: Image.Image | None, sig_supplier: Image.Image | None) -> bytes:
    """
    Lieferschein-PDF erzeugen und Bytes zurückgeben.
    data enthält:
      supplier_name, customer_name, material_name, unit, price, qty, weight_full, weight_empty, weight_net, date_str, note
    """
    pdf = PDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, to_latin1("Lieferschein"), ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)

    rows = [
        ("Lieferant", data.get("supplier_name","")),
        ("Kunde", data.get("customer_name","")),
        ("Material", data.get("material_name","")),
        ("Einheit", data.get("unit","")),
        ("Preis", f"{data.get('price','')} / {data.get('unit','')}"),
        ("Menge", str(data.get("qty","")) if data.get("unit")=="m3" else "-"),
        ("Vollgewicht", str(data.get("weight_full","")) if data.get("unit") in ("kg","t") else "-"),
        ("Leergewicht", str(data.get("weight_empty","")) if data.get("unit") in ("kg","t") else "-"),
        ("Nettogewicht", str(data.get("weight_net","")) if data.get("unit") in ("kg","t") else "-"),
        ("Datum", data.get("date_str","")),
        ("Notiz", data.get("note","")),
    ]
    for k,v in rows:
        pdf.cell(50, 7, to_latin1(f"{k}:"))
        pdf.cell(0, 7, to_latin1(str(v)), ln=True)

    pdf.ln(4)
    export_pdf_with_signature(pdf, sig_customer, "Unterschrift Kunde")
    export_pdf_with_signature(pdf, sig_supplier, "Unterschrift Lieferant")

    return _pdf_bytes(pdf)

# ===================== UI – Styles =====================
def app_header():
    col1, col2 = st.columns([1,5])
    with col1:
        if os.path.exists(LOGO_PATH):
            try:
                st.image(LOGO_PATH, use_container_width=True)
            except Exception:
                st.write("")
    with col2:
        st.markdown(f"<h1 style='margin-bottom:0'>{APP_TITLE}</h1>", unsafe_allow_html=True)
        st.caption("Verwalten von Lieferanten, Kunden, Materialien und Lieferscheinen – stabil & einfach.")

    st.markdown("""
    <style>
    .stButton>button { border-radius: 12px; padding: 0.5rem 1rem; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; }
    </style>
    """, unsafe_allow_html=True)

# ===================== Auth Tabs (Lieferant / Neuanmeldung / Admin) =====================
def auth_tabs():
    tabs = st.tabs(["Lieferanten-Login", "Neuanmeldung Lieferant", "Admin-Login"])

    # ---------- 1) Lieferanten-Login ----------
    with tabs[0]:
        st.subheader("Lieferanten-Login")
        email = st.text_input("E-Mail", key="login_email")
        pw = st.text_input("Passwort", type="password", key="login_pw")
        if st.button("Anmelden", key="login_btn"):
            users = load_csv(USERS_FILE, ["email","pass_hash","status","name","created_at"])
            row = users[users["email"] == email]
            if row.empty:
                st.error("Unbekannte E-Mail.")
            else:
                status = str(row.iloc[0]["status"])
                if status != "active":
                    st.warning("Noch nicht freigeschaltet. Bitte auf Admin-Bestätigung warten.")
                else:
                    if str(row.iloc[0]["pass_hash"]) == pw:
                        st.success("Erfolgreich angemeldet.")
                        st.session_state["logged_supplier"] = str(row.iloc[0]["email"])
                    else:
                        st.error("Falsches Passwort.")

    # ---------- 2) Neuanmeldung Lieferant ----------
    with tabs[1]:
        st.subheader("Neuanmeldung Lieferant")
        reg_name = st.text_input("Firmenname / Ansprechpartner", key="reg_name")
        reg_email = st.text_input("E-Mail", key="reg_email")
        reg_pw1 = st.text_input("Passwort", type="password", key="reg_pw1")
        reg_pw2 = st.text_input("Passwort wiederholen", type="password", key="reg_pw2")
        st.markdown("**Haftungsausschluss** (EU/AT):")
        st.info(
            "Mit Klick auf „Senden“ bestätige ich, dass alle eingegebenen Daten korrekt sind und ich für deren Richtigkeit verantwortlich bin. "
            "Die Betreiber dieser App übernehmen keine Haftung für fehlerhafte Eingaben, Falschabrechnungen oder daraus entstehende Schäden. "
            "Ich stimme der Verarbeitung meiner Daten zur Abwicklung der Biomasse-Abrechnung zu."
        )

        st.write("**Bitte unterschreiben:**")
        sig_can = st_canvas(
            fill_color="rgba(255,255,255,0)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=140,
            width=500,
            drawing_mode="freedraw",
            key="sig_new_supplier"
        )
        accepted = st.checkbox("Ich habe den Haftungsausschluss gelesen und stimme zu.", key="reg_accept")

        if st.button("Neuanmeldung senden", key="btn_register"):
            if not reg_name or not reg_email or not reg_pw1:
                st.error("Bitte alle Felder ausfüllen.")
            elif reg_pw1 != reg_pw2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accepted:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            else:
                sig_img = None
                if sig_can is not None and hasattr(sig_can, "image_data") and sig_can.image_data is not None:
                    arr = sig_can.image_data
                    if isinstance(arr, np.ndarray):
                        # Canvas liefert RGBA-Array
                        sig_img = Image.fromarray((arr[:, :, :3]).astype("uint8"))

                # Speichern / Vormerken
                users = load_csv(USERS_FILE, ["email","pass_hash","status","name","created_at"])
                if (users["email"] == reg_email).any():
                    st.error("E-Mail existiert bereits.")
                else:
                    new_row = {
                        "email": reg_email,
                        "pass_hash": reg_pw1,       # (einfach – du wolltest festen Code/Pass)
                        "status": "pending",
                        "name": reg_name,
                        "created_at": datetime.now().isoformat(timespec="seconds")
                    }
                    users = pd.concat([users, pd.DataFrame([new_row])], ignore_index=True)
                    save_csv(USERS_FILE, users)

                    # PDF Quittung der Anmeldung
                    pdf = PDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", "B", 12)
                    pdf.cell(0, 8, to_latin1("Neuanmeldung Lieferant"), ln=True)
                    pdf.set_font("Helvetica", "", 11)
                    pdf.cell(50, 7, to_latin1("Name:")); pdf.cell(0,7,to_latin1(reg_name), ln=True)
                    pdf.cell(50, 7, to_latin1("E-Mail:")); pdf.cell(0,7,to_latin1(reg_email), ln=True)
                    pdf.cell(50, 7, to_latin1("Zeit:")); pdf.cell(0,7,to_latin1(datetime.now().strftime("%d.%m.%Y %H:%M")), ln=True)
                    pdf.ln(4)
                    pdf.multi_cell(0, 6, to_latin1(
                        "Haftungsausschluss:\n"
                        "Die Betreiber dieser App übernehmen keine Haftung für fehlerhafte Eingaben, "
                        "Falschabrechnungen oder daraus entstehende Schäden. "
                        "Der Anmeldende bestätigt die Korrektheit seiner Angaben."
                    ))
                    export_pdf_with_signature(pdf, sig_img, "Unterschrift Anmeldender")
                    reg_pdf_bytes = _pdf_bytes(pdf)

                    # E-Mail an Admin + Anmelder
                    subject = "Neue Lieferanten-Anmeldung (Bestätigung erforderlich)"
                    body = f"""
                    <p>Neue Anmeldung eines Lieferanten:</p>
                    <ul>
                      <li>Name: {reg_name}</li>
                      <li>E-Mail: {reg_email}</li>
                      <li>Zeit: {datetime.now().strftime("%d.%m.%Y %H:%M")}</li>
                    </ul>
                    <p>Bitte im Admin-Bereich freigeben.</p>
                    """
                    ok, msg = send_email(subject, body, [ADMIN_EMAIL, reg_email], attachments=[("Anmeldung.pdf", reg_pdf_bytes)])
                    if ok:
                        st.success("Anmeldung gespeichert. E-Mail wurde versendet. Bitte auf Admin-Freigabe warten.")
                    else:
                        st.warning(f"Anmeldung gespeichert, aber E-Mail nicht gesendet: {msg}")

    # ---------- 3) Admin-Login ----------
    with tabs[2]:
        st.subheader("Admin-Login")
        admin_email = st.text_input("Admin E-Mail", key="admin_email_input", placeholder="E-Mail eingeben")
        admin_pin = st.text_input("Admin PIN", type="password", key="admin_pin_input")
        if st.button("Admin anmelden", key="admin_login_btn"):
            if admin_email.strip().lower() == ADMIN_EMAIL.lower() and admin_pin == ADMIN_PIN:
                st.success("Admin angemeldet.")
                st.session_state["is_admin"] = True
            else:
                st.error("Falsche Admin-Zugangsdaten.")

# ===================== Lieferanten-Bereich =====================
def supplier_area(supplier_email: str):
    st.markdown("### Lieferantenbereich")
    # Tabs-Reihenfolge: Lieferschein zuerst (Wunsch)
    t1, t2, t3 = st.tabs(["Lieferschein", "Kunden", "Materialien"])

    # -------- Lieferschein erstellen --------
    with t1:
        st.subheader("Neuer Lieferschein")
        customers = load_csv(CUSTOMERS_FILE, ["supplier","customer_name","customer_email"])
        mats = load_csv(MATERIALS_FILE, ["supplier","material_name","unit","price"])

        # Kundenfilter
        cust_list = customers[customers["supplier"] == supplier_email].reset_index(drop=True)
        sel_customer = st.selectbox(
            "Kunde",
            options=["– bitte wählen –"] + list(cust_list["customer_name"]),
            key="deliv_cust"
        )
        # Materialfilter
        mat_list = mats[mats["supplier"] == supplier_email].reset_index(drop=True)
        sel_mat = st.selectbox(
            "Material",
            options=["– bitte wählen –"] + list(mat_list["material_name"]),
            key="deliv_mat"
        )

        # Abhängig vom Material Einheit bestimmen
        unit = ""
        price = 0.0
        if sel_mat != "– bitte wählen –":
            row = mat_list[mat_list["material_name"] == sel_mat]
            if not row.empty:
                unit = str(row.iloc[0]["unit"])
                try:
                    price = float(row.iloc[0]["price"])
                except Exception:
                    price = 0.0

        st.write(f"**Einheit:** {unit if unit else '-'} (Preis: {price} pro Einheit)")

        qty = None
        weight_full = None
        weight_empty = None
        weight_net = None

        if unit == "m3":
            qty = st.number_input("Menge (m³)", min_value=0.0, step=0.1, key="qty_m3")
        elif unit in ("kg", "t"):
            weight_full = st.number_input("Vollgewicht", min_value=0.0, step=0.1, key="wg_full")
            weight_empty = st.number_input("Leergewicht", min_value=0.0, step=0.1, key="wg_empty")
            weight_net = max(0.0, (weight_full or 0) - (weight_empty or 0))
            st.info(f"Nettogewicht: **{weight_net:.2f} {unit}**")
        else:
            st.warning("Bitte zuerst ein Material wählen.")

        note = st.text_area("Notiz (optional)", key="deliv_note")
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")

        st.divider()
        st.write("**Unterschriften** (am Touchscreen mit dem Finger zeichnen):")
        colA, colB = st.columns(2)
        with colA:
            st.caption("Kunde unterschreibt:")
            can_cust = st_canvas(
                fill_color="rgba(255,255,255,0)",
                stroke_width=2,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=140,
                width=500,
                drawing_mode="freedraw",
                key="sig_customer_canvas"
            )
        with colB:
            st.caption("Lieferant unterschreibt:")
            can_sup = st_canvas(
                fill_color="rgba(255,255,255,0)",
                stroke_width=2,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=140,
                width=500,
                drawing_mode="freedraw",
                key="sig_supplier_canvas"
            )

        if st.button("Lieferschein erstellen & per E-Mail senden", key="btn_make_delivery"):
            if sel_customer == "– bitte wählen –" or sel_mat == "– bitte wählen –":
                st.error("Bitte Kunde und Material wählen.")
            else:
                # Canvas → PIL
                sig_cust = None
                if can_cust is not None and hasattr(can_cust, "image_data") and can_cust.image_data is not None and isinstance(can_cust.image_data, np.ndarray):
                    sig_cust = Image.fromarray((can_cust.image_data[:, :, :3]).astype("uint8"))
                sig_sup = None
                if can_sup is not None and hasattr(can_sup, "image_data") and can_sup.image_data is not None and isinstance(can_sup.image_data, np.ndarray):
                    sig_sup = Image.fromarray((can_sup.image_data[:, :, :3]).astype("uint8"))

                # Datan
                data = {
                    "supplier_name": supplier_email,
                    "customer_name": sel_customer,
                    "material_name": sel_mat,
                    "unit": unit,
                    "price": price,
                    "qty": qty,
                    "weight_full": weight_full,
                    "weight_empty": weight_empty,
                    "weight_net": weight_net,
                    "date_str": date_str,
                    "note": note
                }
                try:
                    pdf_bytes = pdf_delivery(data, sig_cust, sig_sup)
                except Exception as e:
                    st.error(f"PDF-Fehler: {e}")
                    return

                # CSV anhängen
                deliveries = load_csv(DELIVERIES_FILE, [
                    "time","supplier","customer","material","unit","price","qty","weight_full","weight_empty","weight_net","note"
                ])
                deliveries.loc[len(deliveries)] = [
                    datetime.now().isoformat(timespec="seconds"),
                    supplier_email, sel_customer, sel_mat, unit, price,
                    qty if unit=="m3" else "",
                    weight_full if unit in ("kg","t") else "",
                    weight_empty if unit in ("kg","t") else "",
                    weight_net if unit in ("kg","t") else "",
                    note
                ]
                save_csv(DELIVERIES_FILE, deliveries)

                # PDF speichern
                file_name = f"Lieferschein_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                out_path = os.path.join(PDF_DIR, file_name)
                os.makedirs(PDF_DIR, exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(pdf_bytes)

                # Empfänger ermitteln
                customers = load_csv(CUSTOMERS_FILE, ["supplier","customer_name","customer_email"])
                c_row = customers[(customers["supplier"]==supplier_email) & (customers["customer_name"]==sel_customer)]
                cust_mail = str(c_row.iloc[0]["customer_email"]) if not c_row.empty else ""

                subject = f"Lieferschein {sel_customer} – {sel_mat}"
                body = f"""
                <p>Automatisch erzeugter Lieferschein.</p>
                <ul>
                  <li>Kunde: {sel_customer}</li>
                  <li>Material: {sel_mat}</li>
                  <li>Einheit: {unit}</li>
                  <li>Datum: {date_str}</li>
                </ul>
                """
                to_list = [ADMIN_EMAIL]
                if cust_mail:
                    to_list.append(cust_mail)
                ok, msg = send_email(subject, body, to_list, attachments=[(file_name, pdf_bytes)])
                if ok:
                    st.success(f"Lieferschein gespeichert & E-Mail versendet ({', '.join(to_list)}).")
                else:
                    st.warning(f"Lieferschein gespeichert, aber E-Mail fehlgeschlagen: {msg}")

    # -------- Kunden verwalten --------
    with t2:
        st.subheader("Kunden verwalten")
        customers = load_csv(CUSTOMERS_FILE, ["supplier","customer_name","customer_email"])
        st.markdown("**Neuen Kunden anlegen**")
        new_c_name = st.text_input("Kundenname", key="new_c_name")
        new_c_mail = st.text_input("E-Mail Kunde", key="new_c_mail")
        if st.button("Kunde speichern", key="btn_save_customer"):
            customers.loc[len(customers)] = [supplier_email, new_c_name, new_c_mail]
            save_csv(CUSTOMERS_FILE, customers)
            st.success("Kunde gespeichert.")

        st.markdown("---")
        st.markdown("**Meine Kunden**")
        own = customers[customers["supplier"] == supplier_email].reset_index(drop=True)
        st.dataframe(own)

    # -------- Materialien verwalten --------
    with t3:
        st.subheader("Materialien verwalten")
        mats = load_csv(MATERIALS_FILE, ["supplier","material_name","unit","price"])
        st.markdown("**Neues Material**")
        m_name = st.text_input("Materialname", key="mat_name")
        unit = st.selectbox("Einheit", options=["kg","t","m3"], key="mat_unit")
        m_price = st.number_input("Preis pro Einheit", min_value=0.0, step=0.01, key="mat_price")
        if st.button("Material speichern", key="btn_save_mat"):
            mats.loc[len(mats)] = [supplier_email, m_name, unit, m_price]
            save_csv(MATERIALS_FILE, mats)
            st.success("Material gespeichert.")

        st.markdown("---")
        st.markdown("**Meine Materialien** (bearbeiten/löschen)")
        own_mats = mats[mats["supplier"] == supplier_email].reset_index(drop=True)
        if not own_mats.empty:
            # kleine Bearbeitungszeile
            idx = st.selectbox("Material auswählen", options=own_mats.index.tolist(), format_func=lambda i: own_mats.loc[i,"material_name"], key="edit_mat_idx")
            edit_name = st.text_input("Name", value=str(own_mats.loc[idx,"material_name"]), key="edit_mat_name")
            edit_unit = st.selectbox("Einheit", options=["kg","t","m3"], index=["kg","t","m3"].index(str(own_mats.loc[idx,"unit"])), key="edit_mat_unit")
            edit_price = st.number_input("Preis", min_value=0.0, step=0.01, value=float(own_mats.loc[idx,"price"]), key="edit_mat_price")
            colx1, colx2 = st.columns(2)
            with colx1:
                if st.button("Speichern", key="btn_update_mat"):
                    own_mats.loc[idx, "material_name"] = edit_name
                    own_mats.loc[idx, "unit"] = edit_unit
                    own_mats.loc[idx, "price"] = edit_price
                    # zurückschreiben
                    mats = load_csv(MATERIALS_FILE, ["supplier","material_name","unit","price"])
                    mats = mats[~((mats["supplier"]==supplier_email) & (mats["material_name"]==own_mats.loc[idx,"material_name"]))]  # alte Zeile wird eh überschrieben, zur Sicherheit filtern wir im nächsten Schritt sauberer
                    mats = mats[mats["supplier"] != supplier_email].copy().append(own_mats, ignore_index=True)
                    save_csv(MATERIALS_FILE, mats)
                    st.success("Geändert.")
            with colx2:
                if st.button("Löschen", key="btn_delete_mat"):
                    mats = mats[~((mats["supplier"]==supplier_email) & (mats["material_name"]==own_mats.loc[idx,"material_name"]))]
                    save_csv(MATERIALS_FILE, mats)
                    st.success("Gelöscht.")
        else:
            st.info("Keine Materialien vorhanden.")

# ===================== Admin-Bereich =====================
def admin_area():
    st.markdown("### Adminbereich – Freigaben & Verwaltung")

    users = load_csv(USERS_FILE, ["email","pass_hash","status","name","created_at"])

    st.subheader("Ausstehende Neuanmeldungen")
    pend = users[users["status"] == "pending"].reset_index(drop=True)
    if pend.empty:
        st.info("Keine ausstehenden Anträge.")
    else:
        st.dataframe(pend[["name","email","created_at"]])
        sel = st.selectbox("Einen Antrag auswählen", options=["–"] + list(pend["email"]), key="admin_sel_user")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Freigeben (aktivieren)", key="btn_admin_approve"):
                if sel != "–":
                    users.loc[users["email"]==sel, "status"] = "active"
                    save_csv(USERS_FILE, users)
                    # Info-Mail an Lieferant
                    send_email(
                        "Zugang freigeschaltet",
                        "<p>Ihr Zugang wurde freigeschaltet. Sie können sich nun einloggen.</p>",
                        sel
                    )
                    st.success("Freigeschaltet.")
        with col2:
            if st.button("Löschen (komplett entfernen)", key="btn_admin_delete"):
                if sel != "–":
                    users = users[users["email"] != sel]
                    save_csv(USERS_FILE, users)
                    st.success("Anmeldung gelöscht.")

    st.subheader("Alle Lieferanten")
    st.dataframe(users)

# ===================== Sidebar / Routing =====================
def topbar():
    with st.sidebar:
        st.markdown("## Navigation")
        if "logged_supplier" in st.session_state:
            st.success(f"Angemeldet als\n**{st.session_state['logged_supplier']}**")
            if st.button("Logout", key="btn_logout"):
                st.session_state.pop("logged_supplier", None)
                st.rerun()
        elif st.session_state.get("is_admin", False):
            st.success("Admin angemeldet")
            if st.button("Admin-Logout", key="btn_admin_logout"):
                st.session_state["is_admin"] = False
                st.rerun()
        else:
            st.info("Bitte zuerst anmelden (oben).")

# ===================== Main =====================
def main():
    ensure_dirs()
    app_header()

    st.markdown("""
    <div style='padding:10px; background:#F6FAF6; border:1px solid #DDEBDD; border-radius:10px;'>
    Willkommen! Bitte wählen Sie oben den passenden Tab:
    <ul>
    <li><b>Lieferanten-Login</b>: einloggen, Lieferscheine erstellen, Kunden & Materialien verwalten.</li>
    <li><b>Neuanmeldung Lieferant</b>: Registrierung mit Haftungsausschluss & Unterschrift (E-Mail an Admin & Anmelder).</li>
    <li><b>Admin-Login</b>: Anträge freigeben oder löschen.</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    auth_tabs()
    topbar()

    # Bereich nach Login
    if "logged_supplier" in st.session_state:
        supplier_area(st.session_state["logged_supplier"])
    elif st.session_state.get("is_admin", False):
        admin_area()

if __name__ == "__main__":
    main()
