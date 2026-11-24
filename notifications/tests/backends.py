from django.core.mail.backends.base import BaseEmailBackend


class FailingEmailBackend(BaseEmailBackend):
    """An email backend whose server is always down."""

    def send_messages(self, email_messages):
        raise ConnectionRefusedError("SMTP server unreachable")
