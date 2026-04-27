import aioboto3
from botocore.exceptions import ClientError
from app.config.settings import settings
from app.config.logger import logger
import html

class SESEmailService:
    def __init__(self):
        self.session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        self.sender = settings.SES_SENDER_EMAIL

    async def send_otp_email(self, recipient: str, code: str):
        subject = "Your Login Code"
        body_text = f"Your one-time login code is: {code}\nThis code will expire in {settings.OTP_EXPIRATION_MINUTES} minutes."
        body_html = f"""
        <html>
        <head></head>
        <body>
          <h2>Your Login Code</h2>
          <p>Your one-time login code is: <strong>{code}</strong></p>
          <p>This code will expire in {settings.OTP_EXPIRATION_MINUTES} minutes.</p>
        </body>
        </html>
        """
        
        try:
            async with self.session.client("ses") as ses_client:
                response = await ses_client.send_email(
                    Source=self.sender,
                    Destination={'ToAddresses': [recipient]},
                    Message={
                        'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                        'Body': {
                            'Text': {'Data': body_text, 'Charset': 'UTF-8'},
                            'Html': {'Data': body_html, 'Charset': 'UTF-8'}
                        }
                    }
                )
            logger.info(f"OTP Email sent to {recipient}! Message ID: {response['MessageId']}")
        except ClientError as e:
            logger.error(f"Failed to send SES email to {recipient}: {e.response['Error']['Message']}")
            raise

    async def send_support_issue_email(
        self,
        support_email: str,
        user_email: str,
        issue_id: int,
        status: str,
        description: str,
    ):
        subject = f"Support Issue #{issue_id} ({status})"
        safe_user_email = html.escape(user_email)
        safe_description = html.escape(description)
        body_text = (
            f"New support issue submitted.\n\n"
            f"User: {user_email}\n"
            f"Issue ID: {issue_id}\n"
            f"Status: {status}\n\n"
            f"Description:\n{description}\n"
        )
        body_html = f"""
        <html>
        <head></head>
        <body>
          <h2>New Support Issue</h2>
          <p><strong>User:</strong> {safe_user_email}</p>
          <p><strong>Issue ID:</strong> {issue_id}</p>
          <p><strong>Status:</strong> {status}</p>
          <h3>Description</h3>
          <pre style="white-space: pre-wrap;">{safe_description}</pre>
        </body>
        </html>
        """

        try:
            async with self.session.client("ses") as ses_client:
                response = await ses_client.send_email(
                    Source=self.sender,
                    Destination={"ToAddresses": [support_email]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    },
                )
            logger.info(
                f"Support issue email sent to {support_email}! Message ID: {response['MessageId']}"
            )
        except ClientError as e:
            logger.error(f"Failed to send support issue email to {support_email}: {e.response['Error']['Message']}")
            raise

email_service = SESEmailService()
