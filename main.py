import os
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image
from io import BytesIO
from datetime import datetime, timedelta
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
import requests
import logging
from flask import Flask, request, jsonify
from azure.storage.blob import ContentSettings 
import pyodbc



# Load env vars and font
load_dotenv()
pdfmetrics.registerFont(TTFont("NotoSansHebrew", "NotoSansHebrew-Regular.ttf"))

logging.basicConfig(
    filename="invoice_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

def format_date_with_leading_zeros(date_str):
    date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    return f"{date.day:02d}.{date.month:02d}.{date.year}"

def get_connection_string():
    return (
        "DRIVER={FreeTDS};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"PORT={os.getenv('DB_PORT','1433')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASS')};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )


def fetch_from_db(query, params):
    conn = pyodbc.connect(get_connection_string())
    cursor = conn.cursor()
    cursor.execute(query, params)
    columns = [col[0] for col in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return results


def upload_to_azure_and_get_relative_sas_download(blob_name, local_file_path, expires_minutes=60):
    from urllib.parse import quote
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    container_name = "invoices"
    blob_name = os.path.basename(blob_name)
    blob_service_client = BlobServiceClient(
        f"https://{account_name}.blob.core.windows.net", credential=account_key
    )
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)
    with open(local_file_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True)
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=expires_minutes),
    )
    encoded_blob_name = quote(blob_name)
    relative_path = f"{encoded_blob_name}?{sas_token}"
    logging.debug(f"Generated relative SAS path: {relative_path}")
    return relative_path

def upload_to_azure_and_get_relative_sas(blob_name, local_file_path, expires_minutes=60):
    from urllib.parse import quote
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    container_name = "invoices"
    blob_name = os.path.basename(blob_name)
    blob_service_client = BlobServiceClient(
        f"https://{account_name}.blob.core.windows.net", credential=account_key
    )
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    with open(local_file_path, "rb") as data:
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(
                content_type='application/pdf',
                content_disposition='inline; filename="invoice.pdf"'
            )
        )

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=expires_minutes),
    )
    encoded_blob_name = quote(blob_name)
    relative_path = f"{encoded_blob_name}?{sas_token}"
    logging.debug(f"Generated relative SAS path: {relative_path}")
    return relative_path

def send_whatsapp_invoice(to, customer_name, pancheria_name, relative_sas_path, relative_sas_path_download):
    access_token = os.getenv("ACCESS_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID")
    if not access_token or not phone_number_id:
        logging.error("❌ Missing WhatsApp credentials.")
        return

    preview_url = relative_sas_path.replace("?", "?disposition=inline&")
    download_url = relative_sas_path_download

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "invoice_whatsapp_delivery",  
            "language": {"code": "en"},
            "components": [
                {"type": "body", "parameters": [
                    {"type": "text", "text": customer_name},
                    {"type": "text", "text": pancheria_name}
                ]},
                {"type": "button", "sub_type": "url", "index": "0",
                 "parameters": [{"type": "text", "text": preview_url}]},
                {"type": "button", "sub_type": "url", "index": "1",
                 "parameters": [{"type": "text", "text": download_url}]}
            ],
        },
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.ok:
        logging.info("✅ WhatsApp message sent.")
    else:
        logging.error(f"❌ WhatsApp send failed: {response.status_code} {response.text}")



def generate_invoice_pdf(client_id, invoice_id):
    invoice = fetch_from_db("SELECT * FROM InvoiceMain WHERE InvoiceID = ?", (invoice_id,))[0]
    rows = fetch_from_db("SELECT * FROM InvoiceResipt WHERE InvoiceID = ?", (invoice_id,))
    client = fetch_from_db("SELECT * FROM ClientsList WHERE ClientID = ?", (client_id,))[0]
    payments = fetch_from_db("SELECT * FROM Payments WHERE InvoiceID = ? AND ClientID = ?", (invoice_id, client_id))
    customer_name = invoice.get("CostomerName", "לקוח")
    pancheria_name = client.get("ClientName", "פנצ׳ריה")
    payment = payments[0] if payments else {}
    items = [
        {
            "description": row["GenerlDes"] or "",
            "quantity": row["Quntities"] or "",
            "itemPrice": f"{row['Price']:.2f}" if row["Price"] else "",
            "totalPrice": f"{row['TotalPrice']:.2f}" if row["TotalPrice"] else "",
        }
        for row in rows
    ]
    vat_rate = 0.18
    raw_total = sum(float(i["totalPrice"]) for i in items if i["totalPrice"])
    total_with_vat = round(raw_total * (1 + vat_rate), 0)
    total = round(total_with_vat / (1 + vat_rate), 2)
    vat_amount = round(total_with_vat - total, 2)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("NotoSansHebrew", 12)
    logo = Image.open("example.jpg")
    c.drawInlineImage(logo, x=138, y=750, width=240, height=90)

    def draw_he(text, x, y, size=12):
        if text:
            reshaped = arabic_reshaper.reshape(str(text))
            bidi_text = get_display(reshaped)
            c.setFont("NotoSansHebrew", size)
            for dx, dy in [(0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2)]:
                c.drawRightString(x + dx, y + dy, bidi_text)

    draw_he(invoice["InvoiceID"], 125, 733)
    draw_he(client["ClientName"], 320, 710)
    draw_he(invoice["TypeOfCar"], 224, 689)
    draw_he(invoice["CarNum"], 320, 688)
    draw_he(invoice["Kil"], 69, 688)
    draw_he(invoice["PhoneN"], 172, 418, 10)
    draw_he(format_date_with_leading_zeros(str(invoice["Date"])), 338, 302, 11)
    draw_he(f"{total:.2f}", 64, 420)
    draw_he("18", 87, 395)
    draw_he(f"{vat_amount:.2f}", 64, 395)
    draw_he(f"{total_with_vat:.2f}", 64, 370)
    draw_he(invoice["Time"], 273, 302, 11)
    row_positions = [642, 619, 595, 570, 545, 520, 497, 472]
    for i, item in enumerate(items[:len(row_positions)]):
        y = row_positions[i]
        draw_he(item["description"][:34], 330, y, 11)
        draw_he(item["quantity"], 366, y)
        draw_he(item["itemPrice"], 150, y)
        draw_he(item["totalPrice"], 64, y)
    if payment:
        pt = payment.get("PaymentType")
        if pt == 3:
            draw_he(payment.get("CreditCardName", ""), 238, 392, 11)
            draw_he(str(payment.get("NumPayCredit", "")), 140, 392, 11)
            c.setLineWidth(1)
            c.ellipse(242, 390, 316, 410)
        elif pt == 1:
            c.setLineWidth(1)
            c.ellipse(342, 390, 374, 410)
        elif pt == 2:
            draw_he(payment.get("CheckNum", ""), 335, 370, 8)
            draw_he(str(payment.get("BankID", "")), 270, 370, 8)
            draw_he(format_date_with_leading_zeros(str(payment.get("ZP", ""))), 182, 370, 8)
            c.setLineWidth(1)
            c.ellipse(341.5, 366, 370, 382)
    c.showPage()
    c.save()
    buffer.seek(0)
    template = PdfReader("Templates/template.pdf")
    overlay = PdfReader(buffer)
    writer = PdfWriter()
    base_page = template.pages[0]
    overlay_page = overlay.pages[0]
    base_page.merge_page(overlay_page)
    writer.add_page(base_page)
    output_path = f"Invoices/invoice_{invoice_id}.pdf"
    with open(output_path, "wb") as f:
        writer.write(f)
    logging.info(f"✅ PDF saved: {output_path}")
    return output_path, customer_name, pancheria_name

@app.route("/generate_invoice", methods=["POST"])
def handle_generate_invoice():
    try:
        data = request.get_json()
        client_id = data["client_id"]
        invoice_id = data["invoice_id"]
        to_phone = data["to_phone"]

        # הפקת החשבונית והחזרת שם הלקוח ושם הפנצ׳ריה
        output_path, customer_name, pancheria_name = generate_invoice_pdf(client_id, invoice_id)

        # שני קישורים – אחד לצפייה ואחד להורדה
        relative_sas = upload_to_azure_and_get_relative_sas(f"invoice_{invoice_id}_preview.pdf", output_path)
        relative_sas_download = upload_to_azure_and_get_relative_sas_download(f"invoice_{invoice_id}_download.pdf", output_path)

        send_whatsapp_invoice(
            to=to_phone,
            customer_name=customer_name,      
            pancheria_name=pancheria_name,   
            relative_sas_path=relative_sas,
            relative_sas_path_download=relative_sas_download
        )

        return jsonify({"status": "success", "invoice": f"invoice_{invoice_id}.pdf", "url": relative_sas})
    except Exception as e:
        logging.error(f"❌ API call failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
