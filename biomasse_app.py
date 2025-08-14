# biomasse_app.py
import streamlit as st
import pandas as pd
import os, uuid, hashlib, datetime, shutil, re
from fpdf import FPDF
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# ------------------ Grund-Setup ------------------
st.set_page_config(page_title="Biomasse Abrechnung", page_icon="🌿", layout="wide")

# Admin-Daten (fest)
ADMIN_EMAIL = "riedlotmar0@gmail.com"
ADMIN_PIN = "8319"

# Pfade
DATA_PATH = "data"
LOGO_PATH = "logo.png"

# Basis-Ordner
os.makedirs(f"{DATA_PATH}", exist_ok=True)
os.makedirs(f"{DATA_PATH}/user", exist_ok=True)
os.makedirs(f"{DATA_PATH}/lieferscheine", exist_ok=True)
os.makedirs(f"{DATA_PATH}/suppliers", exist_ok=True)  # pro Lieferant eigener Ordner

# CSV-Dateien
USERS_FILE = f"{DATA_PATH}/user/users.csv"                       # email, pass_hash, status, tos_accepted_at
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

def email_slug(email: str) -> str:
    """sicherer Ordnername pro Lieferant"""
    return re.sub(r"[^a-z0-9]+", "_", email.strip().lower())

def supplier_paths(email: str) -> dict:
    slug = email_slug(email)
    base = f"{DATA_PATH}/suppliers/{slug}"
    return {
        "base": base,
        "kunden": f"{base}/kunden.csv",
        "material": f"{base}/material.csv",
        "uploads": f"{base}/uploads",
    }

def ensure_supplier_files(email: str):
    p = supplier_paths(email)
    os.makedirs(p["base"], exist_ok=True)
    os.makedirs(p["uploads"], exist_ok=True)
    # Kunden
    if not os.path.exists(p["kunden"]):
        save_csv(pd.DataFrame(columns=["Kundenname", "Email"]), p["kunden"])
    # Material
    if not os.path.exists(p["material"]):
        save_csv(pd.DataFrame(columns=["Material", "Preis_pro_kg", "Preis_pro_t", "Preis_pro_m3"]), p["material"])

def init_files():
    # Nutzerdatei
    if not os.path.exists(USERS_FILE):
        df = pd.DataFrame(columns=["email", "pass_hash", "status", "tos_accepted_at"])
        # Admin als Systemnutzer (optional)
        df.loc[len(df)] = [ADMIN_EMAIL, "", "approved_admin", ""]
        save_csv(df, USERS_FILE)
    else:
        # fehlende Spalten ergänzen
        users = load_csv(USERS_FILE, ["email", "pass_hash", "status", "tos_accepted_at"])
        save_csv(users, USERS_FILE)

    # Lieferschein-Index
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
    st.caption("Lieferanten-Login, Registrierung (mit Haftungsausschluss) & Adminlogin (PIN).")

# ------------------ Session State ------------------
if "auth_role" not in st.session_state:
    st.session_state.auth_role = None  # "admin" | "supplier"
if "auth_email" not in st.session_state:
    st.session_state.auth_email = None

# ------------------ Auth / Registrierung ------------------
def show_login_register():
    st.subheader("Anmeldung / Registrierung")
    # Reihenfolge & Bezeichnungen nach Wunsch:
    tabs = st.tabs(["🚚 Lieferanten-Login", "📝 Lieferant – Neu anmelden", "🔑 Adminlogin"])

    # 1) Lieferanten-Login
    with tabs[0]:
        email = st.text_input("E-Mail (Lieferant)", key="sup_login_email")
        pwd = st.text_input("Passwort", type="password", key="sup_login_pwd")
        if st.button("Als Lieferant anmelden", key="sup_login_btn"):
            users = load_csv(USERS_FILE, ["email", "pass_hash", "status", "tos_accepted_at"])
            row = users[users["email"] == email]
            if row.empty:
                st.error("Benutzer nicht gefunden. Bitte zuerst neu anmelden.")
            else:
                status = row["status"].values[0]
                if status != "approved":
                    st.warning("Noch nicht freigeschaltet. Bitte Admin-Freigabe abwarten.")
                elif sha256(pwd) == row["pass_hash"].values[0]:
                    st.session_state.auth_role = "supplier"
                    st.session_state.auth_email = email
                    ensure_supplier_files(email)
                    st.success("✅ Lieferant angemeldet.")
                    st.rerun()
                else:
                    st.error("❌ Passwort falsch.")

    # 2) Lieferant – Neu anmelden (mit Haftungsausschluss)
    with tabs[1]:
        st.markdown("**Registrierung für Lieferanten**")
        email = st.text_input("E-Mail (Registrierung)", key="sup_reg_email")
        pwd1 = st.text_input("Passwort", type="password", key="sup_reg_pwd1")
        pwd2 = st.text_input("Passwort wiederholen", type="password", key="sup_reg_pwd2")

        st.markdown("**Haftungsausschluss (Pflicht):**")
        st.write(
            "Ich akzeptiere, dass die App von **Privatperson Otmar Riedl** bereitgestellt wird, "
            "ohne Gewährleistung oder Haftung für Schäden, Datenverlust oder Fehlfunktionen. "
            "Die Nutzung erfolgt auf eigenes Risiko."
        )
        accept = st.checkbox("Ich habe den Haftungsausschluss gelesen und **akzeptiere** ihn.", key="sup_reg_accept")

        if st.button("Registrieren & Freigabe anfordern", key="sup_reg_btn"):
            if not email or not pwd1:
                st.error("Bitte E-Mail und Passwort eingeben.")
            elif pwd1 != pwd2:
                st.error("Passwörter stimmen nicht überein.")
            elif not accept:
                st.error("Bitte Haftungsausschluss akzeptieren.")
            else:
                users = load_csv(USERS_FILE, ["email", "pass_hash", "status", "tos_accepted_at"])
                if not users[users["email"] == email].empty:
                    st.warning("E-Mail ist bereits registriert.")
                else:
                    users.loc[len(users)] = [email, sha256(pwd1), "pending", datetime.datetime.now().isoformat()]
                    save_csv(users, USERS_FILE)
                    # Info an Admin
                    send_email(
                        ADMIN_EMAIL,
                        "Neue Lieferanten-Registrierung",
                        f"Neue Registrierung: {email}\nBitte im Adminbereich freigeben."
                    )
                    st.success("✅ Registriert. Freigabe durch Admin erforderlich.")

    # 3) Adminlogin
    with tabs[2]:
        email = st.text_input("Admin E-Mail", value=ADMIN_EMAIL, key="admin_email")
        pin = st.text_input("Admin PIN", type="password", key="admin_pin_input")
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

    # PIN für kritische Aktionen (Löschen)
    with st.expander("🔒 Kritische Aktionen (PIN erforderlich)"):
        pin_for_actions = st.text_input("Admin-PIN für Löschaktionen", type="password", key="admin_action_pin")

    tabs = st.tabs([
        "👥 Benutzer", "📦 Kunden (global)", "🪵 Materialien (global)",
        "🧮 Lieferschein", "📚 Archiv", "🤖 KI (Wunschliste)", "🔒 Datenschutz"
    ])

    # Benutzerverwaltung
    with tabs[0]:
        st.subheader("Benutzerverwaltung")
        users = load_csv(USERS_FILE, ["email", "pass_hash", "status", "tos_accepted_at"])

        st.markdown("### Ausstehende Freigaben")
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
                        # Ordner/Dateien für Lieferant anlegen
                        ensure_supplier_files(row["email"])
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
        st.markdown("### Freigeschaltete Lieferanten")
        approved = users[users["status"]=="approved"][["email","status"]].reset_index(drop=True)
        st.dataframe(approved, use_container_width=True)

        # Löschen von freigeschalteten Lieferanten (PIN-geschützt)
        if not approved.empty:
            st.info("Lieferant löschen (inkl. Datenordner).")
            del_email = st.selectbox("Lieferant wählen", approved["email"].tolist(), key="admin_del_email")
            if st.button("❌ Lieferant löschen", key="admin_del_btn"):
                if st.session_state.get("admin_action_pin") != ADMIN_PIN:
                    st.error("Falscher PIN für Löschaktion.")
                else:
                    # aus users.csv entfernen
                    users = load_csv(USERS_FILE, ["email", "pass_hash", "status", "tos_accepted_at"])
                    users = users[users["email"] != del_email]
                    save_csv(users, USERS_FILE)
                    # Lieferanten-Ordner löschen
                    sp = supplier_paths(del_email)["base"]
                    if os.path.exists(sp):
                        shutil.rmtree(sp, ignore_errors=True)
                    st.success(f"Lieferant {del_email} und Datenordner gelöscht.")
                    st.rerun()

    # Globale Kunden (optional weiter nutzbar)
    with tabs[1]:
        st.subheader("Kundenverwaltung (global, optional)")
        # Global weiter verfügbar für Admin — Lieferanten nutzen aber ihre eigenen Dateien
        global_kunden = load_csv(f"{DATA_PATH}/kunden/kunden.csv", ["Kundenname", "Email"])
        st.dataframe(global_kunden.sort_values("Kundenname"), use_container_width=True)
        c1, c2 = st.columns(2)
        with c1: kname = st.text_input("Kundenname (global)", key="admin_kname")
        with c2: kmail = st.text_input("Kunden-E-Mail (global)", key="admin_kmail")
        if st.button("Globalen Kunden hinzufügen", key="admin_k_add"):
            if not kname:
                st.error("Name fehlt.")
            else:
                global_kunden.loc[len(global_kunden)] = [kname, kmail]
                os.makedirs(f"{DATA_PATH}/kunden", exist_ok=True)
                save_csv(global_kunden, f"{DATA_PATH}/kunden/kunden.csv")
                st.success("Globaler Kunde hinzugefügt.")
                st.rerun()

    # Globale Materialien
    with tabs[2]:
        st.subheader("Materialverwaltung (global, optional)")
        mats = load_csv(f"{DATA_PATH}/materialien/material.csv", ["Material", "Preis_pro_kg", "Preis_pro_t", "Preis_pro_m3"])
        st.dataframe(mats.sort_values("Material"), use_container_width=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1: mname = st.text_input("Material (global)", key="admin_mat_name")
        with c2: mkg = st.number_input("Preis pro kg (€)", min_value=0.0, format="%.4f", key="admin_mat_kg")
        with c3: mt  = st.number_input("Preis pro t (€)",  min_value=0.0, format="%.2f",  key="admin_mat_t")
        with c4: mm3 = st.number_input("Preis pro m³ (€)", min_value=0.0, format="%.4f", key="admin_mat_m3")
        if st.button("Globales Material hinzufügen", key="admin_mat_add"):
            if not mname:
                st.error("Materialname fehlt.")
            else:
                mats.loc[len(mats)] = [mname, mkg, mt, mm3]
                os.makedirs(f"{DATA_PATH}/materialien", exist_ok=True)
                save_csv(mats, f"{DATA_PATH}/materialien/material.csv")
                st.success("Globales Material hinzugefügt.")
                st.rerun()

    # Lieferschein erstellen (Admin)
    with tabs[3]:
        st.subheader("Neuer Lieferschein (Admin)")
        # Admin kann global wählen
        kunden_global = load_csv(f"{DATA_PATH}/kunden/kunden.csv", ["Kundenname","Email"])
        mats_global = load_csv(f"{DATA_PATH}/materialien/material.csv", ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3"])
        if kunden_global.empty or mats_global.empty:
            st.info("Für Admin-Lieferschein bitte globale Kunden & Materialien anlegen (Tabs oben).")
        else:
            c1, c2 = st.columns(2)
            with c1:
                kunde = st.selectbox("Kunde (global)", kunden_global["Kundenname"].sort_values().tolist(), key="admin_ls_kunde")
                material = st.selectbox("Material (global)", mats_global["Material"].sort_values().tolist(), key="admin_ls_material")
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
                menge = st.number_input("Volumen (m³)", min_value=0.0, format="%.3f", key="admin_ls_vol_m3")
                einheit = "m³"

            row = mats_global[mats_global["Material"] == material]
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
                # Mail an Kunde (falls vorhanden) + Admin
                kunde_mail = ""
                try:
                    kunde_mail = kunden_global[kunden_global["Kundenname"] == kunde]["Email"].values[0]
                except Exception:
                    pass
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
        st.subheader("Lieferschein-Archiv (alle)")
        log = load_csv(LIEFERSCHEINLOG_FILE, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
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
                            key=f"admin_dl_{i}"
                        )

    # KI-Wunschliste (Dummy)
    with tabs[5]:
        st.subheader("🤖 KI-Wunschliste (nur Admin)")
        wunsch = st.text_area("Beschreibe die gewünschte Änderung/Erweiterung", key="admin_ki_wunsch")
        pin = st.text_input("Admin-PIN bestätigen", type="password", key="admin_ki_pin")
        if st.button("Änderungsplan prüfen (Simulation)", key="admin_ki_apply"):
            if pin != ADMIN_PIN:
                st.error("Falscher PIN.")
            elif not wunsch.strip():
                st.warning("Bitte Wunsch beschreiben.")
            else:
                st.info("Änderungsplan (Simulation):")
                st.code(
                    f"- Analyse: '{wunsch}'\n"
                    f"- Betroffene Module: UI, Daten, PDF\n"
                    f"- Vorgehen: Backup → Änderung → Test → Speichern\n"
                    f"- Vorteile: bessere Bedienbarkeit\n"
                    f"- Risiken: Validierung & Layout"
                )
                st.success("Simuliert. (Kein echter Code-Change)")

    # Datenschutz
    with tabs[6]:
        st.subheader("🔒 Datenschutz – Privatperson Otmar Riedl")
        st.markdown("""
**Verantwortlich:** Privatperson Otmar Riedl  
**Zweck:** Abrechnung von Biomasse-Lieferungen (Kunden-, Material- und Mengen-/Preis-Daten).  
**Rechtsgrundlage:** Vertrag/Anbahnung.  
**Speicherung:** CSV-Dateien & erzeugte PDFs im Ordner `data/` (pro Lieferant separater Unterordner).  
**Weitergabe:** Keine Weitergabe an Dritte; E-Mail-Versand nur an Beteiligte (Kunde, Lieferant/Admin).  
**Sicherheit:** Login; Lieferanten-Passwörter als Hash; Admin-PIN; SMTP-Zugang über Streamlit-Secrets.  
**Rechte:** Auskunft, Berichtigung, Löschung auf Anfrage an die Admin-E-Mail.
        """)

# ------------------ Lieferanten-Ansicht ------------------
def supplier_view():
    email = st.session_state.auth_email
    st.success(f"Angemeldet als Lieferant: {email}")

    # Eigene Dateien
    sp = supplier_paths(email)
    ensure_supplier_files(email)

    tabs = st.tabs(["👥 Meine Kunden", "🪵 Meine Materialien", "🧮 Lieferschein", "📚 Mein Archiv", "🔒 Datenschutz"])

    # Eigene Kunden
    with tabs[0]:
        st.subheader("Meine Kunden")
        kunden = load_csv(sp["kunden"], ["Kundenname","Email"])
        st.dataframe(kunden.sort_values("Kundenname"), use_container_width=True)
        c1, c2 = st.columns(2)
        with c1: kname = st.text_input("Kundenname", key="sup_kname")
        with c2: kmail = st.text_input("Kunden-E-Mail", key="sup_kmail")
        if st.button("Kunden hinzufügen", key="sup_k_add"):
            if not kname:
                st.error("Name fehlt.")
            else:
                kunden.loc[len(kunden)] = [kname, kmail]
                save_csv(kunden, sp["kunden"])
                st.success("Kunde hinzugefügt.")
                st.rerun()

    # Eigene Materialien
    with tabs[1]:
        st.subheader("Meine Materialien")
        mats = load_csv(sp["material"], ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3"])
        st.dataframe(mats.sort_values("Material"), use_container_width=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1: mname = st.text_input("Material", key="sup_mat_name")
        with c2: mkg = st.number_input("Preis pro kg (€)", min_value=0.0, format="%.4f", key="sup_mat_kg")
        with c3: mt  = st.number_input("Preis pro t (€)",  min_value=0.0, format="%.2f",  key="sup_mat_t")
        with c4: mm3 = st.number_input("Preis pro m³ (€)", min_value=0.0, format="%.4f", key="sup_mat_m3")
        if st.button("Material hinzufügen", key="sup_mat_add"):
            if not mname:
                st.error("Materialname fehlt.")
            else:
                mats.loc[len(mats)] = [mname, mkg, mt, mm3]
                save_csv(mats, sp["material"])
                st.success("Material hinzugefügt.")
                st.rerun()

    # Lieferschein erfassen
    with tabs[2]:
        st.subheader("Neuer Lieferschein")
        kunden = load_csv(sp["kunden"], ["Kundenname","Email"])
        mats   = load_csv(sp["material"], ["Material","Preis_pro_kg","Preis_pro_t","Preis_pro_m3"])
        if kunden.empty or mats.empty:
            st.info("Bitte zuerst eigene Kunden & Materialien anlegen.")
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
            pm3 = float(row["Preis_pro_m3"].values[0]) if not row.empty else 0.0

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
                kunde_mail = ""
                try:
                    kunde_mail = kunden[kunden["Kundenname"] == kunde]["Email"].values[0]
                except Exception:
                    pass

                if kunde_mail:
                    send_email(kunde_mail, "Lieferschein Biomasse", "Ihr Lieferschein im Anhang.", pdf_path)
                send_email(email, "Kopie Lieferschein", "Kopie zur Datensicherung.", pdf_path)
                if email != ADMIN_EMAIL:
                    send_email(ADMIN_EMAIL, "Kopie Lieferschein (Admin)", "Kopie zur Datensicherung.", pdf_path)

                # Log
                log = load_csv(LIEFERSCHEINLOG_FILE, [
                    "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
                ])
                log.loc[len(log)] = [
                    rid, datum, kunde, material, basis, round(menge,3), einheit, round(gesamt,2), pdf_path, email
                ]
                save_csv(log, LIEFERSCHEINLOG_FILE)
                st.success(f"📄 PDF erstellt & versendet. Lieferschein-ID: {rid}")

    # Archiv (eigene)
    with tabs[3]:
        st.subheader("Mein Lieferschein-Archiv")
        log = load_csv(LIEFERSCHEINLOG_FILE, [
            "id","datum","kunde","material","basis","menge","einheit","gesamtpreis_eur","pdf_path","lieferant_email"
        ])
        own = log[log["lieferant_email"] == email]
        if own.empty:
            st.info("Noch keine Lieferscheine vorhanden.")
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
                            key=f"sup_dl_{i}"
                        )

    with tabs[4]:
        st.subheader("🔒 Datenschutz – Privatperson Otmar Riedl")
        st.markdown("""
**Zweck:** Abrechnung von Biomasse-Lieferungen.  
**Speicherung:** CSV/PDF lokal im Ordner `data/` (eigener Unterordner pro Lieferant).  
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
