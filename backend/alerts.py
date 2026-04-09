import smtplib
import os
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from dotenv import load_dotenv

load_dotenv()

# Fast2SMS (free Indian SMS service)
FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY")

# Recipients
AMBULANCE_PHONE = os.getenv("AMBULANCE_PHONE")
AMBULANCE_EMAIL = os.getenv("AMBULANCE_EMAIL")
OWNER_PHONE = os.getenv("OWNER_PHONE")
OWNER_EMAIL = os.getenv("OWNER_EMAIL")
EMERGENCY_PHONE = os.getenv("EMERGENCY_CONTACT_PHONE")
EMERGENCY_EMAIL = os.getenv("EMERGENCY_CONTACT_EMAIL")

# SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

LOCATION = os.getenv("LOCATION", "Unknown")


def _send_sms(to: str, body: str) -> bool:
    """Send SMS via TextBelt (free tier: 1 SMS/day, no signup needed)."""
    if not to:
        print(f"[SMS SKIP] No phone number provided")
        return False
    # TextBelt needs number with country code e.g. +917676925233
    number = to.strip()
    if not number.startswith("+"):
        number = "+91" + number  # default to India
    try:
        response = requests.post(
            "https://textbelt.com/text",
            data={
                "phone": number,
                "message": body,
                "key": "textbelt",  # free key: 1 SMS/day
            },
            timeout=10
        )
        result = response.json()
        if result.get("success"):
            print(f"[SMS SENT] to {number}")
            return True
        else:
            print(f"[SMS ERROR] {result.get('error')}")
            return False
    except Exception as e:
        print(f"[SMS ERROR] {e}")
        return False


def _send_email(to: str, subject: str, body: str, image_bytes: bytes = None) -> bool:
    if not all([SMTP_USER, SMTP_PASS, to]):
        print(f"[EMAIL SKIP] Missing config for {to}")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        if image_bytes:
            img = MIMEImage(image_bytes, name="snapshot.jpg")
            msg.attach(img)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to, msg.as_string())
        print(f"[EMAIL SENT] to {to}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def send_alerts(severity: str, confidence: float, image_bytes: bytes = None) -> list[str]:
    """
    Send multi-level email alerts based on severity.
    Returns list of sent alert descriptions.
    """
    sent = []
    loc = LOCATION
    sev_upper = severity.upper()
    email_body = f"<h2>Accident Detected</h2><p>Severity: <b>{sev_upper}</b></p><p>Confidence: {confidence}</p><p>Location: {loc}</p>"

    # Level 1: Ambulance (always)
    if _send_email(AMBULANCE_EMAIL, f"ACCIDENT ALERT - {sev_upper}", email_body, image_bytes):
        sent.append("ambulance_email")

    # Level 2: Vehicle owner (major or critical)
    if severity in ("major", "critical"):
        if _send_email(OWNER_EMAIL, f"Your Vehicle - Accident {sev_upper}", email_body, image_bytes):
            sent.append("owner_email")

    # Level 3: Emergency contact (critical only)
    if severity == "critical":
        if _send_email(EMERGENCY_EMAIL, f"CRITICAL ACCIDENT ALERT", email_body, image_bytes):
            sent.append("emergency_email")

    return sent
