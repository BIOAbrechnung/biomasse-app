import os
import io
import streamlit as st
from fpdf import FPDF
from PIL import Image

# --- Logo Pfad ---
LOGO_PATH = "logo.png"

# --- PDF Helper ---
def _pdf_bytes(pdf):
    """PDF in Bytes umwandeln, mit Zeichensatz-Fix."""
    try:
        return pdf.output(dest="S").encode("latin-1", "replace")
    except Exception as e:
        st.error(f"PDF-Erstellung fehlgeschlagen: {e}")
        return b""

# --- PDF mit Signatur ---
def export_pdf_with_signature(pdf, sig_img, out_path):
    if sig_img:
        sig_tmp = os.path.join("tmp_sig.png")
        sig_img.save(sig_tmp)
        try:
            pdf.ln(6)
            pdf.cell(0, 8, "Unterschrift:", ln=True)
            pdf.image(sig_tmp, x=20, y=pdf.get_y() + 2, w=70)
            pdf.ln(35)
        except Exception:
            pass
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)

# --- App Header ---
def app_header():
    st.markdown("<h1 style='text-align: center;'>Biomasse App</h1>", unsafe_allow_html=True)
    if os.path.exists(LOGO_PATH):
        try:
            st.image(LOGO_PATH, use_container_width=True)
        except Exception as e:
            st.warning(f"Logo konnte nicht geladen werden: {e}")
    else:
        st.info("Logo-Datei nicht gefunden. Bitte 'logo.png' hochladen.")

# --- Login/Registrierung ---
def auth_tabs():
    tabs = st.tabs(["Login", "Registrieren"])
    with tabs[0]:
        st.subheader("Login")
        username = st.text_input("Benutzername", key="login_user")
        password = st.text_input("Passwort", type="password", key="login_pass")
        if st.button("Einloggen"):
            st.success("Login erfolgreich (Demo).")

    with tabs[1]:
        st.subheader("Registrieren")
        reg_user = st.text_input("Benutzername", key="reg_user")
        reg_pw1 = st.text_input("Passwort", type="password", key="reg_pw1")
        reg_pw2 = st.text_input("Passwort wiederholen", type="password", key="reg_pw2")
        if st.button("Registrieren"):
            if reg_pw1 == reg_pw2:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.cell(200, 10, f"Neuer Benutzer: {reg_user}", ln=True)
                reg_pdf_bytes = _pdf_bytes(pdf)
                st.download_button("Bestätigung herunterladen", reg_pdf_bytes, file_name="registrierung.pdf")
                st.success("Registrierung erfolgreich!")
            else:
                st.error("Passwörter stimmen nicht überein.")

# --- Lieferantenbereich ---
def supplier_area():
    st.subheader("Lieferschein erstellen")
    liefer_datum = st.date_input("Datum")
    kunde = st.text_input("Kunde")
    material = st.selectbox("Material", ["Holz", "Pellets", "Hackschnitzel", "Sonstiges", "M³-Test"])
    
    if "M³" in material:
        menge = st.number_input("Menge (m³)", min_value=0.0)
    else:
        voll = st.number_input("Gewicht Voll (kg)", min_value=0.0)
        leer = st.number_input("Gewicht Leer (kg)", min_value=0.0)
        menge = voll - leer
    
    if st.button("PDF erzeugen"):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 10, f"Lieferschein - {liefer_datum}", ln=True)
        pdf.cell(0, 10, f"Kunde: {kunde}", ln=True)
        pdf.cell(0, 10, f"Material: {material}", ln=True)
        pdf.cell(0, 10, f"Menge: {menge}", ln=True)
        pdf_bytes = _pdf_bytes(pdf)
        st.download_button("Lieferschein herunterladen", pdf_bytes, file_name="lieferschein.pdf")

# --- Main App ---
def main():
    st.set_page_config(page_title="Biomasse App", layout="centered")
    app_header()
    
    st.sidebar.title("Navigation")
    auswahl = st.sidebar.radio("Gehe zu", ["Start", "Lieferantenbereich"])
    
    if auswahl == "Start":
        auth_tabs()
    elif auswahl == "Lieferantenbereich":
        supplier_area()

if __name__ == "__main__":
    main()
