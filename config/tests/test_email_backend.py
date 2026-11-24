"""config.email.LoggingEmailBackend: production without a mail server."""

from django.core.mail import send_mail


def test_logs_instead_of_sending(settings, caplog):
    settings.EMAIL_BACKEND = "config.email.LoggingEmailBackend"
    caplog.set_level("INFO", logger="config.email")
    sent = send_mail("Hello", "The body.", "from@example.com", ["a@example.com", "b@example.com"])
    assert sent == 1
    assert "Email not sent (no EMAIL_HOST set)" in caplog.text
    assert "To: a@example.com, b@example.com" in caplog.text
    assert "Subject: Hello" in caplog.text
    assert "Body: The body." in caplog.text
