import requests
from dotenv import load_dotenv
import os

load_dotenv()

PHONE = os.getenv("AMBULANCE_PHONE", "").strip()
if not PHONE.startswith("+"):
    PHONE = "+91" + PHONE

print(f"Sending test SMS to: {PHONE}")

response = requests.post(
    "https://textbelt.com/text",
    data={
        "phone": PHONE,
        "message": "Test alert from Accident Detection System - Bangalore",
        "key": "textbelt",
    },
    timeout=10
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
