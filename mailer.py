import os
import smtplib
import threading
import logging
import html
from email.message import EmailMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IS_VERCEL = bool(os.environ.get('VERCEL'))
SMTP_TIMEOUT = 10

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASS = os.environ.get('SMTP_PASS')
MAIL_FROM_NAME = os.environ.get('MAIL_FROM_NAME', 'Wisata Jogja')
MAIL_FROM = f"{MAIL_FROM_NAME} <{SMTP_USER or 'noreply@wisatajogja.local'}>"

def _send_email_task(to_email, subject, text_content, html_content):
    if not SMTP_USER or not SMTP_PASS:
        logger.info(f"--- DEV MODE: Mock Sending Email ---")
        logger.info(f"To: {to_email}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Content: {text_content}")
        logger.info(f"------------------------------------")
        return

    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = MAIL_FROM
        msg['To'] = to_email
        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype='html')

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Email sent successfully to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")

def send_email_background(to_email, subject, text_content, html_content):
    if IS_VERCEL:
        # Serverless: kirim sinkron (threading tidak reliable di Vercel)
        _send_email_task(to_email, subject, text_content, html_content)
        return
    try:
        t = threading.Thread(target=_send_email_task, args=(to_email, subject, text_content, html_content), daemon=True)
        t.start()
    except Exception as e:
        logger.error(f"Failed to start background email thread: {str(e)}")

def send_booking_success(booking):
    dest_name = html.escape(booking['destination']['name'])
    name = html.escape(booking['name'])
    code = html.escape(booking['code'])
    date = html.escape(booking['visit_date'])
    qty = booking['qty']
    unit_price = booking['unit_price']
    total = booking['total']
    
    subject = f"Konfirmasi Pesanan - {code}"
    
    text = (f"Halo {name},\n\n"
            f"Pesanan Anda untuk {dest_name} berhasil.\n"
            f"Kode Booking: {code}\n"
            f"Tanggal Kunjungan: {date}\n"
            f"Jumlah Tiket: {qty}\n"
            f"Harga Satuan: Rp{unit_price:,}\n"
            f"Total: Rp{total:,}\n\n"
            f"Kebijakan Refund: 100% (>= 3 hari), 50% (1-2 hari), Hangus (Hari-H).\n")
    
    html_content = (f"<html><body>"
                    f"<p>Halo <b>{name}</b>,</p>"
                    f"<p>Pesanan Anda untuk <b>{dest_name}</b> berhasil.</p>"
                    f"<ul>"
                    f"<li><b>Kode Booking:</b> {code}</li>"
                    f"<li><b>Tanggal Kunjungan:</b> {date}</li>"
                    f"<li><b>Jumlah Tiket:</b> {qty}</li>"
                    f"<li><b>Harga Satuan:</b> Rp{unit_price:,}</li>"
                    f"<li><b>Total:</b> Rp{total:,}</li>"
                    f"</ul>"
                    f"<p><i>Kebijakan Refund: 100% (&gt;= 3 hari), 50% (1-2 hari), Hangus (Hari-H).</i></p>"
                    f"</body></html>")
    
    send_email_background(booking['email'], subject, text, html_content)

def send_booking_update(booking):
    dest_name = html.escape(booking['destination']['name'])
    name = html.escape(booking['name'])
    code = html.escape(booking['code'])
    date = html.escape(booking['visit_date'])
    qty = booking['qty']
    total = booking['total']
    
    subject = f"Pembaruan Pesanan - {code}"
    
    text = (f"Halo {name},\n\n"
            f"Pesanan Anda untuk {dest_name} telah diperbarui.\n"
            f"Kode Booking: {code}\n"
            f"Tanggal Kunjungan Baru: {date}\n"
            f"Jumlah Tiket Baru: {qty}\n"
            f"Total Baru: Rp{total:,}\n")
    
    html_content = (f"<html><body>"
                    f"<p>Halo <b>{name}</b>,</p>"
                    f"<p>Pesanan Anda untuk <b>{dest_name}</b> telah diperbarui.</p>"
                    f"<ul>"
                    f"<li><b>Kode Booking:</b> {code}</li>"
                    f"<li><b>Tanggal Kunjungan Baru:</b> {date}</li>"
                    f"<li><b>Jumlah Tiket Baru:</b> {qty}</li>"
                    f"<li><b>Total Baru:</b> Rp{total:,}</li>"
                    f"</ul>"
                    f"</body></html>")
    
    send_email_background(booking['email'], subject, text, html_content)

def send_booking_refund(booking):
    dest_name = html.escape(booking['destination']['name'])
    name = html.escape(booking['name'])
    code = html.escape(booking['code'])
    refund_amount = booking['refund_amount']
    pct = (refund_amount / booking['total'] * 100) if booking['total'] > 0 else 0
    
    subject = f"Refund Pesanan - {code}"
    
    text = (f"Halo {name},\n\n"
            f"Pesanan Anda untuk {dest_name} telah dibatalkan (Refund).\n"
            f"Kode Booking: {code}\n"
            f"Persentase Refund: {pct:g}%\n"
            f"Nominal Refund: Rp{refund_amount:,}\n")
    
    html_content = (f"<html><body>"
                    f"<p>Halo <b>{name}</b>,</p>"
                    f"<p>Pesanan Anda untuk <b>{dest_name}</b> telah dibatalkan (Refund).</p>"
                    f"<ul>"
                    f"<li><b>Kode Booking:</b> {code}</li>"
                    f"<li><b>Persentase Refund:</b> {pct:g}%</li>"
                    f"<li><b>Nominal Refund:</b> Rp{refund_amount:,}</li>"
                    f"</ul>"
                    f"</body></html>")
    
    send_email_background(booking['email'], subject, text, html_content)
