# biomasse_app.py
import streamlit as st
import pandas as pd
import os, uuid, hashlib, datetime
from fpdf import FPDF
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# ------------------ Grund-Setup ------------------
st.set_page_config(page_title="Biomasse Abrechnung", page_icon="🌿", layout="wide")

# >>> Deine Admin-Zugangsdaten <<<
ADMIN_EMAIL = "riedlotmar0@gmail.com"
ADMIN_PIN = "8319"

DATA_PATH = "data"
LOGO_PATH = "logo.png"

# Ordnerstruktur
os.makedirs(f"{DATA_PATH}/user", exist_ok=True)
os.makedirs(f"{DATA_PATH}/kunden", exist_ok=True)
os.makedirs(f"{DATA_PATH}/materialien", exist_ok=True)
os.makedirs(f"{DATA_PATH}/lieferscheine", exist_ok=True)

USERS_FILE = f"{DATA_PATH}/user/users.csv"                       # email, pass_hash, status
KUNDEN_FILE = f"{DATA_PATH}/kunden/kunden.csv"                   # Kundenname, Email
MATERIAL_FILE = f"{DATA_PATH}/materialien/material.csv"          # Material, Preis_pro_kg, Preis_pro_t, Preis_pro_m3
LIEFERSCHEINLOG_FILE = f"{DATA_PATH}/lieferscheine/index.csv"    # id, datum, kunde, material, basis, menge, einheit, gesamtpreis_eur, pdf_path, lieferant_email

# ------------------ Utilities ------------------
def sha256(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()

def load_csv(path: str, cols: list) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            return df[cols]
        except Exception:
            return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_csv(df: pd.DataFrame, path: str):
    df.to_csv(path, index=False)

def init_files():
    # Nutzer
    if not os.path.exists(USERS_FILE):
        df = pd.DataFrame(columns=["email", "pass_hash", "status"])
        # Admin-Zeile nur als Marker; Admin-Login erfolgt über ADMIN_EMAIL/ADMIN_PIN separat
        df.loc[len(df)] = [ADMIN_EMAIL, "", "approved_admin"]
        save_csv(df, USERS_FILE)
    # Kunden
    if not os.path.exists(KUNDEN_FILE):
        save_csv(pd.DataFrame(columns=["Kundenname", "Email"]), KUNDEN_FILE)
    # Materialien (inkl. m³)
    if not os.path.exists(MATERIAL_FILE):
        save_csv(pd.DataFrame(columns=["Material", "Preis_pro_kg", "Preis_pro_t", "Preis_pro_m3"]), MATERIAL_FILE)
    else:
        # Falls alte Datei ohne m3-Spalte vorhanden, ergänzen
        mats = load_csv(MATERIAL_FILE, ["Material", "Preis_pro_kg", "Preis_pro_t"])
        if "Preis_pro_m3" not in mats.columns:
            mats["Preis_pro_m3"] = 0.0
            save_csv(mats, MATERIAL_FILE)
    # Lieferschein-Log
    if not os.path.exists(LIEFERSCHEINLOG_FILE):
        save_csv(pd.DataFrame(columns=[
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
        ]), LIEFERSCHEINLOG_FILE)

init_files()

def secrets_get(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default

def send_email(to_email: str, subject: str, body: str, attachment_path: str | None = None):
    """E-Mail Versand via st.secrets: SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD"""
    smtp_server = secrets_get("SMTP_SERVER")
    smtp_port = int(secrets_get("SMTP_PORT", 587) or 587)
    smtp_user = secrets_get("SMTP_USER")
    smtp_pass = secrets_get("SMTP_PASSWORD")

    if not (smtp_server and smtp_user and smtp_pass):
        st.warning("✉️ E-Mail-Versand nicht konfiguriert (Secrets fehlen).")
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
        st.error(f"E-Mail-Versand fehlgeschlagen: {e}")

def create_delivery_pdf(kunde: str,
                        material: str,
                        basis: str,
                        menge: float,
                        einheit: str,
                        preis_eur: float,
                        datum: str,
                        unterschrift_kunde: str,
                        unterschrift_lieferant: str,
                        out_path: str):
    """Erstellt PDF-Lieferschein."""
    pdf = FPDF()
    pdf.add_page()

    # Logo
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
    pdf.ln(8)
    pdf.cell(0, 8, f"Unterschrift Kunde: {unterschrift_kunde}", ln=True)
    pdf.cell(0, 8, f"Unterschrift Lieferant: {unterschrift_lieferant}", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", "I", 10)
    pdf.multi_cell(0, 6, "Automatisch erstellt von der Biomasse Abrechnung App.")

    pdf.output(out_path)

# ------------------ Branding / Header ------------------
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
with col_title:
    st.markdown("<h1 style='margin-bottom:0'>🌿 Biomasse Abrechnung</h1>", unsafe_allow_html=True)
    st.caption("Einfach. Übersichtlich. Für Admin & Lieferanten.")

# ------------------ Session State ------------------
if "auth_role" not in st.session_state:
    st.session_state.auth_role = None  # "admin" | "supplier"
if "auth_email" not in st.session_state:
    st.session_state.auth_email = None

# ------------------ Auth / Registrierung ------------------
def show_login_register():
    st.subheader("Anmeldung / Registrierung")

    # REIHENFOLGE wie gewünscht:
    tabs = st.tabs(["🚚 Lieferant (Login)", "📝 Lieferant (Registrierung)", "🔑 Admin"])

    # 1) Lieferant Login
    with tabs[0]:
        st.markdown("**Lieferanten-Login** – zuerst E-Mail, dann Passwort.")
        email = st.text_input("E-Mail", key="sup_login_email")
        pwd = st.text_input("Passwort", type="password", key="sup_login_pwd")
        if st.button("Als Lieferant anmelden", key="sup_login_btn"):
            users = load_csv(USERS_FILE, ["email", "pass_hash", "status"])
            row = users[users["email"].str.lower() == (email or "").lower()]
            if row.empty:
                st.error("Benutzer nicht gefunden. Bitte registrieren.")
            else:
                status = row["status"].values[0]
                if status != "approved":
                    st.warning("Noch nicht freigeschaltet. Bitte Admin-Freigabe abwarten.")
                elif sha256(pwd) == row["pass_hash"].values[0]:
                    st.session_state.auth_role = "supplier"
                    st.session_state.auth_email = email
                    st.success("✅ Lieferant angemeldet.")
                    st.rerun()
                else:
                    st.error("❌ Passwort falsch.")

    # 2) Lieferant Registrierung
    with tabs[1]:
        st.markdown("**Noch kein Zugang?** Hier registrieren. Nach Freigabe durch Admin einloggen.")
        email = st.text_input("E-Mail (Registrierung)", key="sup_reg_email")
        pwd1 = st.text_input("Passwort", type="password", key="sup_reg_pwd1")
        pwd2 = st.text_input("Passwort wiederholen", type="password", key="sup_reg_pwd2")
        if st.button("Registrieren & Freigabe anfordern", key="sup_reg_btn"):
            if not email or not pwd1:
                st.error("Bitte E-Mail und Passwort eingeben.")
            elif pwd1 != pwd2:
                st.error("Passwörter stimmen nicht überein.")
            else:
                users = load_csv(USERS_FILE, ["email", "pass_hash", "status"])
                if not users[users["email"].str.lower() == email.lower()].empty:
                    st.warning("E-Mail ist bereits registriert.")
                else:
                    users.loc[len(users)] = [email, sha256(pwd1), "pending"]
                    save_csv(users, USERS_FILE)
                    st.success("✅ Registriert. Freigabe durch Admin erforderlich.")
                    # Admin informieren
                    send_email(
                        ADMIN_EMAIL,
                        "Neue Lieferanten-Registrierung",
                        f"Neue Registrierung: {email}\nBitte im Admin-Bereich freigeben."
                    )

    # 3) Admin Login (dein fester Login: Email + Code)
    with tabs[2]:
        st.markdown("**Admin-Login** – nur für dich (Privatperson Otmar Riedl).")
        email = st.text_input("Admin E-Mail", value=ADMIN_EMAIL, key="admin_email")
        pin = st.text_input("Admin Code", type="password", key="admin_pin_input")
        if st.button("Als Admin anmelden", key="admin_login_btn"):
            if email == ADMIN_EMAIL and pin == ADMIN_PIN:
                st.session_state.auth_role = "admin"
                st.session_state.auth_email = ADMIN_EMAIL
                st.success("✅ Admin angemeldet.")
                st.rerun()
            else:
                st.error("❌ Falsche Admin-Daten.")

# ------------------ Admin-Ansicht ------------------
def admin_view():
    st.success(f"Angemeldet als Admin: {st.session_state.auth_email}")
    tabs = st.tabs([
        "👥 Benutzer", "📦 Kunden", "🪵 Materialien",
        "🧮 Lieferschein", "📚 Archiv", "🤖 KI (Wunschliste)", "🔒 Datenschutz"
    ])

    # Benutzerverwaltung
    with tabs[0]:
        st.subheader("Benutzerverwaltung")
        users = load_csv(USERS_FILE, ["email", "pass_hash", "status"])
        st.markdown("**Ausstehende Freigaben**")
        pending = users[users["status"] == "pending"]
        if pending.empty:
            st.info("Keine offenen Anträge.")
        else:
            for i, row in pending.iterrows():
                c1, c2, c3 = st.columns([3,1,1])
                with c1:
                    st.write(row["email"])
                with c2:
                    if st.button("Freigeben", key=f"approve_{i}"):
                        users.loc[i, "status"] = "approved"
                        save_csv(users, USERS_FILE)
                        send_email(row["email"], "Freigeschaltet", "Ihr Zugang wurde freigeschaltet.")
                        st.success(f"{row['email']} freigeschaltet.")
                        st.rerun()
                with c3:
                    if st.button("Ablehnen", key=f"reject_{i}"):
                        users = users.drop(index=i)
                        save_csv(users, USERS_FILE)
                        st.warning(f"{row['email']} abgelehnt und entfernt.")
                        st.rerun()
        st.markdown("---")
        st.markdown("**Freigeschaltete Lieferanten**")
        st.dataframe(
            users[users["status"]=="approved"][["email","status"]].reset_index(drop=True),
            use_container_width=True
        )

    # Kunden
    with tabs[1]:
        st.subheader("Kundenverwaltung")
        kunden = load_csv(KUNDEN_FILE, ["Kundenname", "Email"])
        st.dataframe(kunden.sort_values("Kundenname"), use_container_width=True, key="admin_kunden_df")
        c1, c2 = st.columns(2)
        with c1: kname = st.text_input("Kundenname", key="admin_kname")
        with c2: kmail = st.text_input("Kunden-E-Mail", key="admin_kmail")
        if st.button("Kunden hinzufügen", key="admin_k_add"):
            if not kname:
                st.error("Name fehlt.")
            else:
                kunden.loc[len(kunden)] = [kname, kmail]
                save_csv(kunden, KUNDEN_FILE)
                st.success("Kunde hinzugefügt.")
                st.rerun()

    # Materialien
    with tabs[2]:
        st.subheader("Materialverwaltung")
        mats = load_csv(MATERIAL_FILE, ["Material", "Preis_pro_kg", "Preis_pro_t", "Preis_pro_m3"])
        st.dataframe(mats.sort_values("Material"), use_container_width=True, key="admin_mats_df")
        c1, c2, c3, c4 = st.columns(4)
        with c1: mname = st.text_input("Material", key="admin_mat_name")
        with c2: mkg = st.number_input("Preis pro kg (€)", min_value=0.0, format="%.4f", key="admin_mat_kg")
        with c3: mt  = st.number_input("Preis pro t (€)",  min_value=0.0, format="%.2f",  key="admin_mat_t")
        with c4: mm3 = st.number_input("Preis pro m³ (€)", min_value=0.0, format="%.4f", key="admin_mat_m3")
        if st.button("Material hinzufügen", key="admin_mat_add"):
            if not mname:
                st.error("Materialname fehlt.")
            else:
                mats.loc[len(mats)] = [mname, mkg, mt, mm3]
                save_csv(mats, MATERIAL_FILE)
                st.success("Material hinzugefügt.")
                st.rerun()

    # Lieferschein erstellen (Admin)
    with tabs[3]:
        st.subheader("Neuer Lieferschein")
        kunden = load_csv(KUNDEN_FILE, ["Kundenname", "Email"])
        mats = load_csv(MATERIAL_FILE, ["Material", "Preis_pro_kg", "Preis_pro_t", "Preis_pro_m3"])

        if kunden.empty or mats.empty:
            st.info("Bitte zuerst Kunden & Materialien anlegen.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                kunde = st.selectbox("Kunde", kunden["Kundenname"].sort_values().tolist(), key="admin_ls_kunde")
                material = st.selectbox("Material", mats["Material"].sort_values().tolist(), key="admin_ls_material")
            with c2:
                basis = st.radio("Preis-Basis", ["pro kg", "pro t", "pro m³"], key="admin_ls_basis")

            if basis in ["pro kg", "pro t"]:
                c3, c4 = st.columns(2)
                with c3: voll = st.number_input("Gewicht voll (kg)", min_value=0.0, format="%.3f", key="admin_ls_voll")
                with c4: leer = st.number_input("Gewicht leer (kg)", min_value=0.0, format="%.3f", key="admin_ls_leer")
                netto = max(0.0, voll - leer)
                menge = netto if basis == "pro kg" else netto/1000.0
                einheit = "kg" if basis == "pro kg" else "t"
            else:
                # pro m³
                menge = st.number_input("Volumen (m³)", min_value=0.0, format="%.3f", key="admin_ls_vol_m3")
                einheit = "m³"

            row = mats[mats["Material"] == material]
            pkg = float(row["Preis_pro_kg"].values[0]) if not row.empty else 0.0
            pt  = float(row["Preis_pro_t"].values[0]) if not row.empty else 0.0
            pm3 = float(row["Preis_pro_m3"].values[0]) if not row.empty else 0.0

            if basis == "pro kg":
                gesamt = menge * pkg
            elif basis == "pro t":
                gesamt = menge * pt
            else:
                gesamt = menge * pm3

            st.metric("Menge", f"{menge:.3f} {einheit}")
            st.metric("Gesamtpreis (€)", f"{gesamt:.2f}")

            uk = st.text_input("Unterschrift Kunde (Name)", key="admin_ls_uk")
            ul = st.text_input("Unterschrift Lieferant (Name)", key="admin_ls_ul")

            if st.button("PDF erstellen & versenden", key="admin_ls_btn"):
                rid = uuid.uuid4().hex[:8]
                datum = datetime.datetime.now().strftime("%Y-%m-%d")
                pdf_path = f"{DATA_PATH}/lieferscheine/lieferschein_{rid}.pdf"
                create_delivery_pdf(
                    kunde, material, basis, menge, einheit, gesamt, datum, uk, ul, pdf_path
                )

                # E-Mail-Adressen
                try:
                    kunde_mail = kunden[kunden["Kundenname"] == kunde]["Email"].values[0]
                except Exception:
                    kunde_mail = ""

                # Versand: Kunde + Admin (Kopie zur Archivierung)
                if kunde_mail:
                    send_email(kunde_mail, "Lieferschein Biomasse", "Ihr Lieferschein im Anhang.", pdf_path)
                send_email(ADMIN_EMAIL, "Kopie Lieferschein (Admin)", "Kopie zur Datensicherung.", pdf_path)

                # Log
                log = load_csv(LIEFERSCHEINLOG_FILE, [
                    "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
                ])
                log.loc[len(log)] = [
                    rid, datum, kunde, material, basis, round(menge,3), einheit, round(gesamt,2), pdf_path, st.session_state.auth_email
                ]
                save_csv(log, LIEFERSCHEINLOG_FILE)
                st.success(f"📄 PDF erstellt & versendet. Lieferschein-ID: {rid}")

    # Archiv
    with tabs[4]:
        st.subheader("Lieferschein-Archiv")
        log = load_csv(LIEFERSCHEINLOG_FILE, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
        ])
        if log.empty:
            st.info("Noch keine Lieferscheine vorhanden.")
        else:
            st.dataframe(log.sort_values("datum", ascending=False), use_container_width=True, key="admin_arch_df")
            for i, r in log.iterrows():
                fp = r["pdf_path"]
                if os.path.exists(fp):
                    with open(fp, "rb") as f:
                        st.download_button(
                            f"Download {os.path.basename(fp)}",
                            f,
                            file_name=os.path.basename(fp),
                            key=f"admin_dl_{i}"
                        )

    # KI-Wunschliste (Demo)
    with tabs[5]:
        st.subheader("🤖 KI-Wunschliste (nur Admin)")
        wunsch = st.text_area("Beschreibe die gewünschte Änderung/Erweiterung", key="admin_ki_wunsch")
        pin = st.text_input("Admin-Code bestätigen", type="password", key="admin_ki_pin")
        if st.button("Änderungsplan prüfen & anwenden (Simulation)", key="admin_ki_apply"):
            if pin != ADMIN_PIN:
                st.error("Falscher Code.")
            elif not wunsch.strip():
                st.warning("Bitte Wunsch beschreiben.")
            else:
                st.info("Änderungsplan:")
                st.code(
                    f"- Analyse: '{wunsch}'\n"
                    f"- Betroffene Module: UI, Daten, PDF\n"
                    f"- Vorgehen: Backup → Änderung → Test → Speichern\n"
                    f"- Vorteile: bessere Bedienbarkeit\n"
                    f"- Risiken: Validierung & Layout"
                )
                st.success("Änderung angewendet & getestet (Simulation). ✅ gespeichert.")

    # Datenschutz
    with tabs[6]:
        st.subheader("🔒 Datenschutz – Privatperson Otmar Riedl")
        st.markdown("""
**Verantwortlich:** Privatperson Otmar Riedl  
**Zweck:** Abrechnung von Biomasse-Lieferungen (Kunden-, Material- und Mengen-/Preis-Daten).  
**Rechtsgrundlage:** Vertrag/Anbahnung.  
**Speicherung:** CSV-Dateien & erzeugte PDFs im Ordner `data/`.  
**Weitergabe:** Keine Weitergabe an Dritte; E-Mail-Versand nur an Beteiligte (Kunde, Lieferant/Admin).  
**Sicherheit:** Login; Lieferanten-Passwörter als Hash; Admin-Code; SMTP-Zugang über Streamlit-Secrets.  
**Rechte:** Auskunft, Berichtigung, Löschung auf Anfrage an die Admin-E-Mail.
        """)

# ------------------ Lieferanten-Ansicht ------------------
def supplier_view():
    st.success(f"Angemeldet als Lieferant: {st.session_state.auth_email}")
    tabs = st.tabs(["🧮 Lieferschein", "📚 Archiv", "🔒 Datenschutz"])

    # Lieferschein erfassen (Lieferant)
    with tabs[0]:
        kunden = load_csv(KUNDEN_FILE, ["Kundenname","Email"])
        mats = load_csv(MATERIAL_FILE, ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3"])
        if kunden.empty or mats.empty:
            st.info("Bitte Admin um Anlage von Kunden & Materialien.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                kunde = st.selectbox("Kunde", kunden["Kundenname"].sort_values().tolist(), key="sup_ls_kunde")
                material = st.selectbox("Material", mats["Material"].sort_values().tolist(), key="sup_ls_material")
            with c2:
                basis = st.radio("Preis-Basis", ["pro kg", "pro t", "pro m³"], key="sup_ls_basis")

            if basis in ["pro kg", "pro t"]:
                c3, c4 = st.columns(2)
                with c3: voll = st.number_input("Gewicht voll (kg)", min_value=0.0, format="%.3f", key="sup_ls_voll")
                with c4: leer = st.number_input("Gewicht leer (kg)", min_value=0.0, format="%.3f", key="sup_ls_leer")
                netto = max(0.0, voll - leer)
                menge = netto if basis == "pro kg" else netto/1000.0
                einheit = "kg" if basis == "pro kg" else "t"
            else:
                menge = st.number_input("Volumen (m³)", min_value=0.0, format="%.3f", key="sup_ls_vol_m3")
                einheit = "m³"

            row = mats[mats["Material"] == material]
            pkg = float(row["Preis_pro_kg"].values[0]) if not row.empty else 0.0
            pt  = float(row["Preis_pro_t"].values[0]) if not row.empty else 0.0
            pm3 = float(float(row["Preis_pro_m3"].values[0])) if not row.empty else 0.0

            if basis == "pro kg":
                gesamt = menge * pkg
            elif basis == "pro t":
                gesamt = menge * pt
            else:
                gesamt = menge * pm3

            st.metric("Menge", f"{menge:.3f} {einheit}")
            st.metric("Gesamtpreis (€)", f"{gesamt:.2f}")

            uk = st.text_input("Unterschrift Kunde (Name)", key="sup_ls_uk")
            ul = st.text_input("Unterschrift Lieferant (Name)", key="sup_ls_ul")

            if st.button("PDF erstellen & versenden", key="sup_ls_btn"):
                rid = uuid.uuid4().hex[:8]
                datum = datetime.datetime.now().strftime("%Y-%m-%d")
                pdf_path = f"{DATA_PATH}/lieferscheine/lieferschein_{rid}.pdf"
                create_delivery_pdf(
                    kunde, material, basis, menge, einheit, gesamt, datum, uk, ul, pdf_path
                )

                # Empfänger
                try:
                    kunde_mail = kunden[kunden["Kundenname"] == kunde]["Email"].values[0]
                except Exception:
                    kunde_mail = ""

                # Versand: Kunde + Lieferant + Admin-Kopie
                if kunde_mail:
                    send_email(kunde_mail, "Lieferschein Biomasse", "Ihr Lieferschein im Anhang.", pdf_path)
                send_email(st.session_state.auth_email, "Kopie Lieferschein", "Kopie zur Datensicherung.", pdf_path)
                if st.session_state.auth_email != ADMIN_EMAIL:
                    send_email(ADMIN_EMAIL, "Kopie Lieferschein (Admin)", "Kopie zur Datensicherung.", pdf_path)

                # Log
                log = load_csv(LIEFERSCHEINLOG_FILE, [
                    "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
                ])
                log.loc[len(log)] = [
                    rid, datum, kunde, material, basis, round(menge,3), einheit, round(gesamt,2), pdf_path, st.session_state.auth_email
                ]
                save_csv(log, LIEFERSCHEINLOG_FILE)
                st.success(f"📄 PDF erstellt & versendet. Lieferschein-ID: {rid}")

    # Archiv (eigene)
    with tabs[1]:
        log = load_csv(LIEFERSCHEINLOG_FILE, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
        ])
        own = log[log["lieferant_email"] == st.session_state.auth_email]
        if own.empty:
            st.info("Noch keine Lieferscheine vorhanden.")
        else:
            st.dataframe(own.sort_values("datum", ascending=False), use_container_width=True, key="sup_arch_df")
            for i, r in own.iterrows():
                fp = r["pdf_path"]
                if os.path.exists(fp):
                    with open(fp, "rb") as f:
                        st.download_button(
                            f"Download {os.path.basename(fp)}",
                            f,
                            file_name=os.path.basename(fp),
                            key=f"sup_dl_{i}"
                        )

    with tabs[2]:
        st.subheader("🔒 Datenschutz – Privatperson Otmar Riedl")
        st.markdown("""
**Zweck:** Abrechnung von Biomasse-Lieferungen.  
**Speicherung:** CSV/PDF lokal im Ordner `data/`.  
**E-Mail:** Versand nur an Beteiligte; SMTP-Zugang über Secrets.  
        """)

# ------------------ Routing ------------------
def show_topbar():
    with st.sidebar:
        st.markdown("### Navigation")
        if st.session_state.auth_role == "admin":
            st.write("• Admin-Bereich")
        elif st.session_state.auth_role == "supplier":
            st.write("• Lieferanten-Bereich")
        if st.button("Abmelden", key="logout_btn"):
            st.session_state.auth_role = None
            st.session_state.auth_email = None
            st.success("Abgemeldet.")
            st.rerun()

# Start
if st.session_state.auth_role is None:
    show_login_register()
else:
    show_topbar()
    if st.session_state.auth_role == "admin":
        admin_view()
    elif st.session_state.auth_role == "supplier":
        supplier_view()

st.markdown("---")
st.caption("© 2025 Biomasse Abrechnung – Privatperson Otmar Riedl")
