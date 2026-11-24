"""An email backend that writes each email to the log instead of sending it.

Used in production when no EMAIL_HOST is configured, so notifications never
fail for lack of a mail server and their content still shows up in the
Render (or Docker) logs.
"""

import logging

from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class LoggingEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        for message in email_messages:
            logger.info(
                "Email not sent (no EMAIL_HOST set). To: %s | Subject: %s | Body: %s",
                ", ".join(message.recipients()),
                message.subject,
                message.body,
            )
        return len(email_messages)
