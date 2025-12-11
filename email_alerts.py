"""
Email Notification Helper
Sends alerts for scraper failures
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ALERT_EMAIL = os.getenv('ALERT_EMAIL')  # Your email
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')


def send_alert(subject, message):
    """Send email alert"""
    if not all([ALERT_EMAIL, SMTP_USER, SMTP_PASSWORD]):
        print("Email not configured - skipping alert")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = ALERT_EMAIL
        msg['Subject'] = f"🚨 Fight Schedule Alert: {subject}"
        
        msg.attach(MIMEText(message, 'plain'))
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"✓ Alert sent: {subject}")
        return True
        
    except Exception as e:
        print(f"Failed to send alert: {e}")
        return False
