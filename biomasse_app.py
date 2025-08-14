# biomasse_app.py
import streamlit as st
import pandas as pd
import os, re, uuid, hashlib, datetime, io
from fpdf import FPDF
from PIL import Image
from streamlit_drawable_canvas import st_canvas
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import numpy as np

# ===================== Grund-Setup =====================
st.set_page_config(page_title="Biomasse Abrechnung", page_icon="🌿", layout="wide")

ADMIN_PIN = "8319"  # wie gewünscht
DATA_ROOT = "data"
GLOBAL_LOG = os.path.join(DATA_ROOT, "lieferscheine", "index.csv")
LOGO_PATH = "logo.png"

# Verzeichnisse
def ensure_dirs():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(os.path.join(DATA_ROOT, "lieferscheine"), exist_ok=True)
    os.makedirs(os.path.join(DATA_ROOT, "suppliers"), exist_ok=True)

def email_key(e: str) -> str:
    # saubere Ordnernamen pro Lieferant
    return re.sub(r"[^a-zA-Z0-9]+", "_", (e or "").strip().lower())

def sup_dir(email: str) -> str:
    d = os.path.join(DATA_ROOT, "suppliers", email_key(email))
    os.makedirs(d, exist_ok=True)
    return d

def load_csv(path: str, cols: list) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
        except Exception:
            df = pd.DataFrame(columns=cols)
    else:
        df = pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c not in ("Preis_pro_kg","Preis_pro_t","Preis_pro_m3","menge","gesamtpreis_eur") else 0.0
    return df[cols]

def save_csv(df: pd.DataFrame, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

def sha256(txt: str) -> str:
    return hashlib.sha256((txt or "").encode("utf-8")).hexdigest()

ensure_dirs()

# ===== Nutzerdaten (global) =====
USERS_FILE = os.path.join(DATA_ROOT, "users.csv")
if not os.path.exists(USERS_FILE):
    save_csv(pd.DataFrame(columns=[
        "email","pass_hash","status","registered_at","approved_at",
        "disclaimer_accepted","disclaimer_pdf"
    ]), USERS_FILE)

# Globaler Lieferschein-Index
if not os.path.exists(GLOBAL_LOG):
    save_csv(pd.DataFrame(columns=[
        "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur",
        "pdf_path","lieferant_email"
    ]), GLOBAL_LOG)

# ===== Helper: Secrets & Mail =====
def secrets_get(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default

def send_email(to_email: str, subject: str, body: str, attachment_path: str | None = None):
    """SMTP via st.secrets: SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD"""
    smtp_server = secrets_get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(secrets_get("SMTP_PORT", 587))
    smtp_user = secrets_get("SMTP_USER")
    smtp_pass = secrets_get("SMTP_PASSWORD")
    if not (smtp_user and smtp_pass):
        st.info("✉️ Hinweis: E-Mail nicht gesendet (SMTP-Secrets fehlen).")
        return
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(attachment_path)}"'
        msg.attach(part)
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        st.warning(f"E-Mail-Versand fehlgeschlagen: {e}")

# ===== PDF: Haftungsausschluss =====
DISCLAIMER_TEXT = (
    "Haftungsausschluss und Nutzungsbedingungen\n\n"
    "1) Keine Haftung für Schäden: Der Betreiber übernimmt keine Haftung für direkte oder "
    "indirekte Schäden aus der Nutzung, soweit gesetzlich zulässig.\n"
    "2) Eigenverantwortliche Nutzung: Eingaben und Berechnungen ohne Gewähr auf Vollständigkeit, "
    "Richtigkeit oder Aktualität. Nutzer prüft die Richtigkeit seiner Eingaben.\n"
    "3) Datenschutz: Personenbezogene Daten werden nur für App-Funktionen genutzt und nicht an "
    "unberechtigte Dritte weitergegeben, außer es besteht eine gesetzliche Pflicht.\n"
    "4) Änderungen: Bedingungen können angepasst werden; Änderungen gelten mit Veröffentlichung.\n"
    "5) Rechtsgrundlage: EU-/AT-Recht findet Anwendung.\n\n"
    "Mit meiner Unterschrift bestätige ich, dass ich den Haftungsausschluss gelesen, verstanden "
    "und akzeptiert habe."
)

def create_disclaimer_pdf(email: str, name: str, sig_img: Image.Image, out_path: str):
    pdf = FPDF()
    pdf.add_page()
    if os.path.exists(LOGO_PATH):
        try:
            pdf.image(LOGO_PATH, x=10, y=8, w=28)
        except Exception:
            pass
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 12, "Haftungsausschluss – Biomasse App", ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 7, DISCLAIMER_TEXT)
    pdf.ln(4)
    pdf.cell(0, 8, f"Name: {name}", ln=True)
    pdf.cell(0, 8, f"E-Mail: {email}", ln=True)
    pdf.cell(0, 8, f"Datum: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
    # Signatur temporär speichern
    if sig_img:
        sig_tmp = os.path.join(DATA_ROOT, "tmp_sig_disclaimer.png")
        sig_img.save(sig_tmp)
        try:
            pdf.ln(6)
            pdf.cell(0, 8, "Unterschrift:", ln=True)
            pdf.image(sig_tmp, x=20, y=pdf.get_y()+2, w=70)
            pdf.ln(35)
        except Exception:
            pass
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)

# ===== PDF: Lieferschein =====
def create_delivery_pdf(kunde, material, basis, menge, einheit, preis_eur, datum,
                        uk_text, ul_text, sig_kunde_img: Image.Image | None, sig_lief_img: Image.Image | None,
                        out_path: str):
    pdf = FPDF()
    pdf.add_page()
    if os.path.exists(LOGO_PATH):
        try:
            pdf.image(LOGO_PATH, x=10, y=8, w=28)
        except Exception:
            pass
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 12, "Lieferschein", ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 8, f"Datum: {datum}", ln=True)
    pdf.cell(0, 8, f"Kunde: {kunde}", ln=True)
    pdf.cell(0, 8, f"Material: {material}", ln=True)
    pdf.cell(0, 8, f"Preis-Basis: {basis}", ln=True)
    pdf.cell(0, 8, f"Menge: {menge:.3f} {einheit}", ln=True)
    pdf.cell(0, 8, f"Gesamtpreis: {preis_eur:.2f} €", ln=True)
    pdf.ln(6)
    # Signaturblöcke
    y_start = pdf.get_y()
    pdf.cell(95, 8, f"Unterschrift Kunde: {uk_text}", ln=0)
    pdf.cell(0, 8, f"Unterschrift Lieferant: {ul_text}", ln=1)
    # Bilder
    def put_sig(img: Image.Image | None, x):
        if img:
            tmp = os.path.join(DATA_ROOT, f"tmp_sig_{uuid.uuid4().hex}.png")
            img.save(tmp)
            try:
                pdf.image(tmp, x=x, y=y_start+10, w=70)
            except Exception:
                pass
    put_sig(sig_kunde_img, 20)
    put_sig(sig_lief_img, 115)
    pdf.ln(40)
    pdf.set_font("Arial", "I", 10)
    pdf.multi_cell(0, 6, "Automatisch erstellt von der Biomasse Abrechnung App.")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)

# ===================== Session =====================
if "role" not in st.session_state:
    st.session_state.role = None      # "supplier" | "admin"
if "email" not in st.session_state:
    st.session_state.email = None

# ===================== UI: Header =====================
col_logo, col_title = st.columns([1,6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
with col_title:
    st.markdown("<h1 style='margin-bottom:0'>🌿 Biomasse Abrechnung</h1>", unsafe_allow_html=True)
    st.caption("Einfach. Übersichtlich. Für Admin & Lieferanten.")

# ===================== AUTH =====================
def auth_tabs():
    st.subheader("Anmeldung / Registrierung")
    tabs = st.tabs(["🚚 Lieferant (Login)", "📝 Lieferant (Neuanmeldung)", "🔑 Admin-Login"])

    # --- Lieferant Login ---
    with tabs[0]:
        email = st.text_input("E-Mail", key="sup_login_email")
        pwd = st.text_input("Passwort", type="password", key="sup_login_pwd")
        if st.button("Anmelden", key="sup_login_btn"):
            users = load_csv(USERS_FILE, ["email","pass_hash","status","registered_at","approved_at",
                                          "disclaimer_accepted","disclaimer_pdf"])
            row = users[users["email"] == email]
            if row.empty:
                st.error("Benutzer nicht gefunden. Bitte zuerst registrieren.")
            else:
                if row["status"].values[0] != "approved":
                    st.warning("Noch nicht freigeschaltet. Bitte Admin-Freigabe abwarten.")
                elif sha256(pwd) != row["pass_hash"].values[0]:
                    st.error("❌ Passwort falsch.")
                else:
                    st.session_state.role = "supplier"
                    st.session_state.email = email
                    st.success("✅ Angemeldet.")
                    st.rerun()

    # --- Lieferant Neuanmeldung (mit Disclaimer + Unterschrift) ---
    with tabs[1]:
        st.markdown("**Neuanmeldung für Lieferanten**")
        n_email = st.text_input("E-Mail (Login)", key="reg_email")
        n_name  = st.text_input("Vor- und Nachname / Firma", key="reg_name")
        pwd1 = st.text_input("Passwort", type="password", key="reg_pwd1")
        pwd2 = st.text_input("Passwort wiederholen", type="password", key="reg_pwd2")
        st.markdown("**Haftungsausschluss (EU/Österreich):**")
        with st.expander("Text anzeigen"):
            st.write(DISCLAIMER_TEXT)

        st.markdown("**Bitte zeichnen Sie Ihre Unterschrift (Finger/Maus):**")
        can = st_canvas(
            fill_color="rgba(255,255,255,0)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=120,
            width=500,
            drawing_mode="freedraw",
            key="reg_canvas"
        )
        accepted = st.checkbox("Ich habe den Haftungsausschluss gelesen und akzeptiere ihn.")

        if st.button("Registrieren & Freigabe anfordern", key="reg_btn"):
            if not n_email or not pwd1:
                st.error("Bitte E-Mail und Passwort eingeben.")
            elif pwd1 != pwd2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accepted:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            elif not can.image_data:
                st.error("Bitte Unterschrift zeichnen.")
            else:
                users = load_csv(USERS_FILE, ["email","pass_hash","status","registered_at","approved_at",
                                              "disclaimer_accepted","disclaimer_pdf"])
                if not users[users["email"] == n_email].empty:
                    st.warning("E-Mail ist bereits registriert.")
                else:
                    # Signatur in PIL
                    sig_img = Image.fromarray(can.image_data.astype("uint8")) if can.image_data is not None else None
                    # PDF Haftungsausschluss
                    out_pdf = os.path.join(sup_dir(n_email), "haftungsausschluss.pdf")
                    create_disclaimer_pdf(n_email, n_name, sig_img, out_pdf)

                    # Nutzer eintragen
                    users.loc[len(users)] = [
                        n_email, sha256(pwd1), "pending",
                        datetime.datetime.now().isoformat(), "", "true", out_pdf
                    ]
                    save_csv(users, USERS_FILE)

                    # Ordnerstruktur des Lieferanten vorbereiten
                    save_csv(pd.DataFrame(columns=["Kundenname","Email"]), os.path.join(sup_dir(n_email), "kunden.csv"))
                    save_csv(pd.DataFrame(columns=[
                        "Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3","Basis"
                    ]), os.path.join(sup_dir(n_email), "material.csv"))

                    # E-Mails: an Neuanmelder & an Firmenadresse
                    body = (
                        f"Sehr geehrte/r {n_name},\n\n"
                        "vielen Dank für Ihre Registrierung in der Biomasse-Abrechnungs-App.\n"
                        "Sie haben den Haftungsausschluss akzeptiert. Im Anhang finden Sie eine Kopie.\n"
                        "Freigabe erfolgt nach Prüfung durch den Admin.\n\n"
                        "Mit freundlichen Grüßen\nBiomasse-Abrechnungs-Team"
                    )
                    send_email(n_email, "Bestätigung Registrierung & Haftungsausschluss", body, out_pdf)
                    send_email("app.biomasse@gmail.com",
                               f"Neue Lieferanten-Registrierung: {n_email}",
                               "Bitte im Admin-Bereich prüfen und freigeben.", out_pdf)

                    st.success("✅ Registriert. Freigabe durch Admin erforderlich.")

    # --- Admin Login (ohne vorbefüllte E-Mail) ---
    with tabs[2]:
        a_email = st.text_input("Admin E-Mail", key="admin_email_input")
        a_pin   = st.text_input("Admin PIN", type="password", key="admin_pin_input")
        if st.button("Als Admin anmelden", key="admin_login_btn"):
            if a_pin == ADMIN_PIN and a_email:
                st.session_state.role = "admin"
                st.session_state.email = a_email
                st.success("✅ Admin angemeldet.")
                st.rerun()
            else:
                st.error("Falsche Admin-Daten.")

# ===================== Admin Ansicht =====================
def admin_view():
    st.success(f"Admin: {st.session_state.email}")
    tabs = st.tabs(["👥 Lieferanten", "📚 Archiv (alle)", "🔒 Datenschutz"])

    # --- Lieferanten verwalten ---
    with tabs[0]:
        users = load_csv(USERS_FILE, ["email","pass_hash","status","registered_at","approved_at",
                                      "disclaimer_accepted","disclaimer_pdf"])
        st.markdown("### Ausstehende Freigaben")
        pending = users[users["status"]=="pending"]
        if pending.empty:
            st.info("Keine offenen Anträge.")
        else:
            for i, row in pending.iterrows():
                c1, c2, c3 = st.columns([4,2,2])
                with c1:
                    st.write(row["email"])
                with c2:
                    if st.button("Freigeben", key=f"approve_{i}"):
                        users.loc[i,"status"]="approved"
                        users.loc[i,"approved_at"]=datetime.datetime.now().isoformat()
                        save_csv(users, USERS_FILE)
                        send_email(row["email"], "Freigeschaltet",
                                   "Ihr Lieferanten-Zugang wurde freigeschaltet.")
                        st.success(f"{row['email']} freigeschaltet.")
                        st.rerun()
                with c3:
                    pin = st.text_input(f"PIN für Löschen ({row['email']})", type="password", key=f"pin_del_pending_{i}")
                    if st.button("Ablehnen/Löschen", key=f"reject_{i}"):
                        if pin != ADMIN_PIN:
                            st.error("Falscher PIN.")
                        else:
                            users = users.drop(index=i)
                            save_csv(users, USERS_FILE)
                            st.warning(f"{row['email']} gelöscht.")
                            st.rerun()

        st.markdown("---")
        st.markdown("### Freigeschaltete Lieferanten")
        approved = users[users["status"]=="approved"][["email","approved_at"]].reset_index(drop=True)
        st.dataframe(approved, use_container_width=True)

        # Löschen freigeschalteter Lieferanten (inkl. Daten)
        st.markdown("#### Lieferant löschen (inkl. seiner Kunden/Materialien)")
        del_email = st.text_input("E-Mail des zu löschenden Lieferanten", key="del_supplier_email")
        del_pin   = st.text_input("Admin-PIN bestätigen", type="password", key="del_supplier_pin")
        if st.button("Lieferant endgültig löschen", key="del_supplier_btn"):
            if del_pin != ADMIN_PIN:
                st.error("Falscher PIN.")
            else:
                idx = users[users["email"]==del_email].index
                if len(idx)==0:
                    st.error("E-Mail nicht gefunden.")
                else:
                    users = users.drop(index=idx)
                    save_csv(users, USERS_FILE)
                    # Ordner löschen (soft: umbenennen)
                    sd = sup_dir(del_email)
                    if os.path.exists(sd):
                        try:
                            os.rename(sd, sd+"_DELETED_"+uuid.uuid4().hex[:6])
                        except Exception:
                            pass
                    st.warning("Lieferant & seine Daten entfernt.")

    # --- Archiv (global) ---
    with tabs[1]:
        log = load_csv(GLOBAL_LOG, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur",
            "pdf_path","lieferant_email"
        ])
        if log.empty:
            st.info("Noch keine Lieferscheine vorhanden.")
        else:
            st.dataframe(log.sort_values("datum", ascending=False), use_container_width=True)
            for i, r in log.iterrows():
                fp = r["pdf_path"]
                if os.path.exists(fp):
                    with open(fp, "rb") as f:
                        st.download_button(
                            f"Download {os.path.basename(fp)}",
                            f,
                            file_name=os.path.basename(fp),
                            key=f"adm_dl_{i}"
                        )

    with tabs[2]:
        st.subheader("Datenschutz (Kurzinfo)")
        st.markdown("""
**Zweck:** Abrechnung von Biomasse-Lieferungen.  
**Speicherung:** CSV/PDF im Projektordner.  
**E-Mail:** Versand nur an Beteiligte; SMTP via Secrets.  
        """)

# ===================== Lieferant Ansicht =====================
def supplier_view():
    st.success(f"Lieferant: {st.session_state.email}")
    tabs = st.tabs(["📦 Kunden & Materialien", "🧮 Lieferschein", "📚 Archiv", "🔒 Datenschutz"])

    # --- Kunden & Materialien (pro Lieferant) ---
    with tabs[0]:
        sdir = sup_dir(st.session_state.email)
        kunden_file = os.path.join(sdir, "kunden.csv")
        mats_file   = os.path.join(sdir, "material.csv")
        kunden = load_csv(kunden_file, ["Kundenname","Email"])
        mats = load_csv(mats_file, ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3","Basis"])

        st.markdown("#### Kunden")
        st.dataframe(kunden.sort_values("Kundenname"), use_container_width=True)
        kc1, kc2 = st.columns(2)
        with kc1: kname = st.text_input("Kundenname", key="k_name")
        with kc2: kmail = st.text_input("Kunden-E-Mail", key="k_mail")
        if st.button("Kunde hinzufügen", key="k_add"):
            if not kname:
                st.error("Name fehlt.")
            else:
                kunden.loc[len(kunden)] = [kname, kmail]
                save_csv(kunden, kunden_file)
                st.success("Kunde hinzugefügt.")
                st.rerun()

        st.markdown("---")
        st.markdown("#### Materialien (Preisbasis fix je Material)")
        st.dataframe(mats.sort_values("Material"), use_container_width=True)
        mc1, mc2, mc3, mc4, mc5 = st.columns([2,1,1,1,1])
        with mc1: mname = st.text_input("Material", key="m_name")
        with mc2: mkg = st.number_input("€/kg", min_value=0.0, format="%.4f", key="m_kg")
        with mc3: mt  = st.number_input("€/t",  min_value=0.0, format="%.2f",  key="m_t")
        with mc4: mm3 = st.number_input("€/m³", min_value=0.0, format="%.4f", key="m_m3")
        with mc5: basis = st.selectbox("Basis", ["pro kg","pro t","pro m³"], key="m_basis")
        if st.button("Material hinzufügen/aktualisieren", key="m_add"):
            if not mname:
                st.error("Materialname fehlt.")
            else:
                # upsert
                idx = mats[mats["Material"]==mname].index
                if len(idx)>0:
                    mats.loc[idx, ["Preis_pro_kg","Preis_pro_t","Preis_pro_m3","Basis"]] = [mkg, mt, mm3, basis]
                else:
                    mats.loc[len(mats)] = [mname, mkg, mt, mm3, basis]
                save_csv(mats, mats_file)
                st.success("Material gespeichert.")
                st.rerun()

    # --- Lieferschein ---
    with tabs[1]:
        sdir = sup_dir(st.session_state.email)
        kunden_file = os.path.join(sdir, "kunden.csv")
        mats_file   = os.path.join(sdir, "material.csv")
        kunden = load_csv(kunden_file, ["Kundenname","Email"])
        mats = load_csv(mats_file, ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3","Basis"])

        if kunden.empty:
            st.info("Bitte zuerst Kunden anlegen.")
            return
        if mats.empty:
            st.info("Bitte zuerst Materialien anlegen.")
            return

        sc1, sc2 = st.columns(2)
        with sc1:
            kunde = st.selectbox("Kunde auswählen", kunden["Kundenname"].sort_values().tolist(), key="ls_kunde")
        with sc2:
            # filter: nur Materialien des Lieferanten
            material = st.selectbox("Material", mats["Material"].sort_values().tolist(), key="ls_material")

        # Preisbasis kommt aus Material
        row = mats[mats["Material"] == material]
        basis = row["Basis"].values[0] if not row.empty else "pro kg"
        pkg = float(row["Preis_pro_kg"].values[0]) if not row.empty else 0.0
        pt  = float(row["Preis_pro_t"].values[0]) if not row.empty else 0.0
        pm3 = float(row["Preis_pro_m3"].values[0]) if not row.empty else 0.0

        st.markdown(f"**Preis-Basis (fix):** {basis}")

        if basis in ["pro kg", "pro t"]:
            c3, c4 = st.columns(2)
            with c3: voll = st.number_input("Gewicht voll (kg)", min_value=0.0, format="%.3f", key="ls_voll")
            with c4: leer = st.number_input("Gewicht leer (kg)", min_value=0.0, format="%.3f", key="ls_leer")
            netto = max(0.0, (voll - leer))
            menge = netto if basis == "pro kg" else (netto/1000.0)
            einheit = "kg" if basis == "pro kg" else "t"
        else:
            menge = st.number_input("Volumen (m³)", min_value=0.0, format="%.3f", key="ls_m3")
            einheit = "m³"

        if basis == "pro kg":
            gesamt = menge * pkg
        elif basis == "pro t":
            gesamt = menge * pt
        else:
            gesamt = menge * pm3

        st.metric("Menge", f"{menge:.3f} {einheit}")
        st.metric("Gesamtpreis (€)", f"{gesamt:.2f}")

        st.markdown("**Unterschrift Kunde (zeichnen):**")
        canv_kunde = st_canvas(
            fill_color="rgba(255,255,255,0)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=120,
            width=450,
            drawing_mode="freedraw",
            key="sig_kunde"
        )
        uk = st.text_input("Name Kunde (für PDF)", key="uk_text")

        st.markdown("**Unterschrift Lieferant (zeichnen):**")
        canv_lief = st_canvas(
            fill_color="rgba(255,255,255,0)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#FFFFFF",
            height=120,
            width=450,
            drawing_mode="freedraw",
            key="sig_lief"
        )
        ul = st.text_input("Name Lieferant (für PDF)", key="ul_text")

        if st.button("PDF erstellen & senden", key="ls_pdf_btn"):
            if not canv_kunde.image_data or not canv_lief.image_data:
                st.error("Bitte beide Unterschriften zeichnen.")
            else:
                sig_k_img = Image.fromarray(canv_kunde.image_data.astype("uint8"))
                sig_l_img = Image.fromarray(canv_lief.image_data.astype("uint8"))
                rid = uuid.uuid4().hex[:8]
                datum = datetime.datetime.now().strftime("%Y-%m-%d")
                pdf_path = os.path.join(DATA_ROOT, "lieferscheine", f"lieferschein_{rid}.pdf")

                create_delivery_pdf(
                    kunde, material, basis, menge, einheit, gesamt, datum,
                    uk, ul, sig_k_img, sig_l_img, pdf_path
                )

                # Empfänger
                try:
                    kunde_mail = kunden[kunden["Kundenname"]==kunde]["Email"].values[0]
                except Exception:
                    kunde_mail = ""
                subj = "Lieferschein Biomasse"
                body = "Im Anhang finden Sie den Lieferschein."
                if kunde_mail:
                    send_email(kunde_mail, subj, body, pdf_path)
                send_email(st.session_state.email, "Kopie Lieferschein", "Kopie zur Datensicherung.", pdf_path)
                send_email("app.biomasse@gmail.com", "Kopie Lieferschein (Admin)", "Kopie zur Datensicherung.", pdf_path)

                # Logs
                glog = load_csv(GLOBAL_LOG, [
                    "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur",
                    "pdf_path","lieferant_email"
                ])
                glog.loc[len(glog)] = [
                    rid, datum, kunde, material, basis, round(menge,3), einheit, round(gesamt,2), pdf_path, st.session_state.email
                ]
                save_csv(glog, GLOBAL_LOG)

                st.success(f"📄 PDF erstellt & versendet. ID: {rid}")

    # --- Archiv (eigene) ---
    with tabs[2]:
        log = load_csv(GLOBAL_LOG, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur",
            "pdf_path","lieferant_email"
        ])
        own = log[log["lieferant_email"] == st.session_state.email]
        if own.empty:
            st.info("Noch keine Lieferscheine.")
        else:
            st.dataframe(own.sort_values("datum", ascending=False), use_container_width=True)
            for i, r in own.iterrows():
                fp = r["pdf_path"]
                if os.path.exists(fp):
                    with open(fp, "rb") as f:
                        st.download_button(
                            f"Download {os.path.basename(fp)}",
                            f,
                            file_name=os.path.basename(fp),
                            key=f"dl_{i}"
                        )

    with tabs[3]:
        st.subheader("Datenschutz (Kurzinfo)")
        st.markdown("""
**Zweck:** Abrechnung von Biomasse-Lieferungen.  
**Speicherung:** CSV/PDF lokal im Projektordner.  
**E-Mail:** Versand nur an Beteiligte; SMTP via Secrets.  
        """)

# ===================== Sidebar / Routing =====================
def topbar():
    with st.sidebar:
        st.markdown("### Navigation")
        if st.session_state.role == "admin":
            st.write("• Admin-Bereich")
        elif st.session_state.role == "supplier":
            st.write("• Lieferanten-Bereich")
        if st.button("Abmelden"):
            st.session_state.role = None
            st.session_state.email = None
            st.rerun()

# Start
if st.session_state.role is None:
    auth_tabs()
else:
    topbar()
    if st.session_state.role == "admin":
        admin_view()
    elif st.session_state.role == "supplier":
        supplier_view()

st.markdown("---")
st.caption("© 2025 Biomasse Abrechnung – Privatperson Otmar Riedl")

