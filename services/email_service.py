import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

class EmailService:
    """Service for sending emails via Gmail SMTP"""
    
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = os.environ.get('GMAIL_USER', '')
        self.sender_password = os.environ.get('GMAIL_APP_PASSWORD', '')
        self.admin_email = os.environ.get('ADMIN_EMAIL', self.sender_email)
        
        # Setup Jinja2 template environment
        template_dir = Path(__file__).parent.parent / 'templates'
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))
    
    def send_contact_notification(self, contact_data: dict) -> dict:
        """
        Send email notification for contact form submission
        
        Args:
            contact_data: Dictionary containing name, email, subject, message, phone
            
        Returns:
            Dictionary with status and message
        """
        try:
            # Render email templates
            admin_template = self.env.get_template('admin_notification.html')
            user_template = self.env.get_template('user_confirmation.html')
            
            admin_html = admin_template.render(
                name=contact_data['name'],
                email=contact_data['email'],
                phone=contact_data.get('phone', 'Not provided'),
                subject=contact_data['subject'],
                message=contact_data['message']
            )
            
            user_html = user_template.render(
                name=contact_data['name']
            )
            
            # Connect to Gmail SMTP server
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                
                # Send notification to admin
                self._send_html_email(
                    server,
                    self.sender_email,
                    [self.admin_email],
                    f"New Contact Form: {contact_data['subject']}",
                    admin_html
                )
                
                # Send confirmation to user
                self._send_html_email(
                    server,
                    self.sender_email,
                    [contact_data['email']],
                    "We Received Your Message - Prime Stack",
                    user_html
                )
            
            logger.info(f"Emails sent successfully for {contact_data['email']}")
            return {
                "status": "success",
                "message": "Emails sent successfully"
            }
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {str(e)}")
            return {
                "status": "error",
                "message": "Email authentication failed. Please check configuration."
            }
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {str(e)}")
            return {
                "status": "error",
                "message": f"Email service error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error sending email: {str(e)}")
            return {
                "status": "error",
                "message": "Failed to send email notification"
            }
    
    def _send_html_email(self, server, sender, recipients, subject, html_content):
        """Helper method to send HTML emails"""
        msg = MIMEMultipart('alternative')
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject
        
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        server.sendmail(sender, recipients, msg.as_string())

# Create singleton instance
email_service = EmailService()
