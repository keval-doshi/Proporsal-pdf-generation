from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS, cross_origin
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import base64
import os
import re
import logging
import traceback
from dotenv import load_dotenv
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables - FORCE RELOAD
load_dotenv(override=True)

app = Flask(__name__)

# Enable CORS for all origins
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": False
    }
})

# ============== CONFIGURATION ==============

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))

# CRITICAL: Check if env vars are loaded
SENDER_EMAIL = os.getenv('EMAIL_USER', '')
SENDER_PASSWORD = os.getenv('EMAIL_PASS', '')

MAX_PDF_SIZE_MB = 10

# ============== DEBUG: Print configuration on startup ==============
print("=" * 60)
print("🔧 CONFIGURATION CHECK")
print("=" * 60)
print(f"SMTP_SERVER: {SMTP_SERVER}")
print(f"SMTP_PORT: {SMTP_PORT}")
print(f"EMAIL_USER: {'SET (' + SENDER_EMAIL + ')' if SENDER_EMAIL else 'NOT SET - EMAIL WILL FAIL!'}")
print(f"EMAIL_PASS: {'SET (' + '*' * len(SENDER_PASSWORD) + ')' if SENDER_PASSWORD else 'NOT SET - EMAIL WILL FAIL!'}")
print(f"MAX_PDF_SIZE_MB: {MAX_PDF_SIZE_MB}")
print("=" * 60)

if not SENDER_EMAIL or not SENDER_PASSWORD:
    print("❌ ERROR: Email credentials not configured!")
    print("   Create a .env file with:")
    print("   EMAIL_USER=your_email@gmail.com")
    print("   EMAIL_PASS=your_16_char_app_password")
    print("=" * 60)
else:
    print("✅ Email credentials configured successfully")
    print("=" * 60)

# ============== STATIC FILE SERVING ==============

@app.route('/')
def serve_index():
    """Serve the main HTML file"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files (images, css, js, pdf)"""
    if '..' in filename or filename.startswith('/'):
        return "Invalid path", 400
    
    if not os.path.exists(filename):
        return f"File not found: {filename}", 404
        
    return send_from_directory('.', filename)

# ============== HELPER FUNCTIONS ==============

def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_pdf_size(pdf_base64):
    try:
        size_mb = (len(pdf_base64) * 3 / 4) / (1024 * 1024)
        return size_mb <= MAX_PDF_SIZE_MB
    except Exception:
        return False

# ============== EMAIL FUNCTION ==============

def send_email_with_attachment(recipient_email, subject, body, pdf_base64, filename="ActLocal_Proposal.pdf"):
    """
    Send email with PDF attachment using SMTP
    """
    # Check if credentials are configured
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        logger.error("❌ Email credentials not configured!")
        return False, "Email credentials not configured. Check .env file with EMAIL_USER and EMAIL_PASS"
    
    try:
        # Validate inputs
        if not is_valid_email(recipient_email):
            return False, "Invalid recipient email address"
        
        if not validate_pdf_size(pdf_base64):
            return False, f"PDF too large. Maximum size is {MAX_PDF_SIZE_MB}MB"
        
        # Decode base64 PDF
        try:
            pdf_data = base64.b64decode(pdf_base64)
            logger.info(f"📄 PDF decoded successfully, size: {len(pdf_data)} bytes")
        except Exception as e:
            logger.error(f"❌ PDF decode error: {str(e)}")
            return False, "Invalid PDF data format"
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = subject
        msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')
        
        # Attach body text
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Attach PDF
        part = MIMEBase('application', 'pdf')
        part.set_payload(pdf_data)
        encoders.encode_base64(part)
        
        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        part.add_header('Content-Type', 'application/pdf; name="{}"'.format(filename))
        
        msg.attach(part)
        
        logger.info(f"📧 Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")
        
        # Connect to SMTP server and send
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.set_debuglevel(1)  # Enable debug output
        server.starttls()
        
        logger.info(f"🔐 Logging in as: {SENDER_EMAIL}")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        text = msg.as_string()
        logger.info(f"📤 Sending email to: {recipient_email}")
        server.sendmail(SENDER_EMAIL, recipient_email, text)
        server.quit()
        
        logger.info(f"✅ Email sent successfully to {recipient_email}")
        return True, "Email sent successfully!"
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication failed: {str(e)}")
        return False, "Email authentication failed. Check your email and app password. Make sure you're using a 16-character App Password, not your regular Gmail password."
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"❌ Recipient refused: {str(e)}")
        return False, "Recipient email address was refused by the server."
    except smtplib.SMTPSenderRefused as e:
        logger.error(f"❌ Sender refused: {str(e)}")
        return False, "Sender email address was refused by the server."
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP Error: {str(e)}")
        return False, f"SMTP Error: {str(e)}"
    except Exception as e:
        logger.error(f"❌ Unexpected email error: {str(e)}")
        logger.error(traceback.format_exc())
        return False, f"Failed to send email: {str(e)}"

# ============== API ENDPOINTS ==============

@app.route('/api/')
def home():
    config_status = "configured" if (SENDER_EMAIL and SENDER_PASSWORD) else "not_configured"
    return jsonify({
        'status': 'OK',
        'service': 'ActLocal Email Service',
        'version': '2.0',
        'message': 'Backend is running.',
        'email_configured': config_status,
        'endpoints': {
            'health': '/api/health',
            'send_proposal': '/api/send-proposal (POST)'
        }
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    config_status = "configured" if (SENDER_EMAIL and SENDER_PASSWORD) else "not_configured"
    
    return jsonify({
        'status': 'OK',
        'service': 'ActLocal Email Service',
        'timestamp': datetime.now().isoformat(),
        'email_configured': config_status,
        'sender_email': SENDER_EMAIL if SENDER_EMAIL else None,
        'message': 'Email configured' if config_status == 'configured' else 'Email NOT configured - check .env file'
    })

@app.route('/api/send-proposal', methods=['POST'])
@cross_origin()
def send_proposal():
    """
    API endpoint to receive PDF from frontend and send via email
    """
    logger.info("📨 Received send-proposal request")
    
    # Check if email is configured first
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        logger.error("❌ Email send attempted but credentials not configured")
        return jsonify({
            'success': False,
            'error': 'Email service not configured. Create .env file with EMAIL_USER and EMAIL_PASS'
        }), 500
    
    try:
        if not request.is_json:
            logger.error("❌ Request is not JSON")
            return jsonify({
                'success': False,
                'error': 'Content-Type must be application/json'
            }), 400
        
        data = request.get_json()
        logger.info(f"📋 Request data received for client: {data.get('client_name', 'Unknown')}")
        
        # Extract fields with validation
        recipient_email = data.get('to_email', '').strip()
        subject = data.get('subject', 'ActLocal Service Proposal').strip()
        body = data.get('message', 'Please find attached our service proposal.').strip()
        pdf_base64 = data.get('pdf_base64', '')
        client_name = data.get('client_name', 'Client').strip()
        
        # Validate required fields
        if not recipient_email:
            return jsonify({
                'success': False,
                'error': 'Recipient email is required'
            }), 400
            
        if not is_valid_email(recipient_email):
            return jsonify({
                'success': False,
                'error': 'Invalid email address format'
            }), 400
        
        if not pdf_base64:
            return jsonify({
                'success': False,
                'error': 'PDF data is required'
            }), 400
        
        # Log request (without sensitive data)
        logger.info(f"📧 Processing email request for client: {client_name}, recipient: {recipient_email}")
        
        # Send email
        success, message = send_email_with_attachment(
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            pdf_base64=pdf_base64,
            filename=f"ActLocal_Proposal_{client_name.replace(' ', '_')}.pdf"
        )
        
        if success:
            logger.info(f"✅ Email sent successfully to {recipient_email}")
            return jsonify({
                'success': True,
                'message': f'Proposal sent successfully to {recipient_email}',
                'timestamp': datetime.now().isoformat(),
                'recipient': recipient_email
            })
        else:
            logger.error(f"❌ Failed to send email: {message}")
            return jsonify({
                'success': False,
                'error': message
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Unexpected error in send_proposal: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}'
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"❌ Internal server error: {str(error)}")
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500

# ============== RUN SERVER ==============

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("🚀 Starting ActLocal Email Service v2.0")
    print("=" * 60 + "\n")
    
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("⚠️  WARNING: Email credentials not configured!")
        print("   To fix this:")
        print("   1. Create a file named '.env' in the same folder as app.py")
        print("   2. Add these lines:")
        print("      EMAIL_USER=your_email@gmail.com")
        print("      EMAIL_PASS=your_16_char_app_password")
        print("   3. Restart the server")
        print("\n   For Gmail App Password:")
        print("   - Go to https://myaccount.google.com  → Security → 2-Step Verification")
        print("   - Then App passwords → Generate")
        print("=" * 60 + "\n")
    else:
        print(f"✅ Ready to send emails from: {SENDER_EMAIL}")
        print("=" * 60 + "\n")
    
    print("🌐 Server running at: http://localhost:5000")
    print("🔗 Health check: http://localhost:5000/api/health")
    print("📨 API endpoint: http://localhost:5000/api/send-proposal")
    print("=" * 60 + "\n")
    
    # Run with threading enabled for better concurrent handling
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)