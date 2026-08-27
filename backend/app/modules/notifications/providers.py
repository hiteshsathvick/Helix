"""Email delivery (SPEC.md §23 "email via provider"). One concrete
provider in v1 (unlike ai/providers.py's multi-provider abstraction --
SPEC only asks for "email via provider" singular here), using stdlib
smtplib wrapped in run_in_threadpool -- the exact precedent core/storage.py
already sets for boto3 (a sync-only SDK with no async equivalent worth a
new dependency for the volume of mail this module sends).
"""

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings


class EmailProvider(ABC):
    @abstractmethod
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class SMTPEmailProvider(EmailProvider):
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        from_address: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._from_address = from_address

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        def _send() -> None:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                if self._use_tls:
                    client.starttls()
                if self._username:
                    client.login(self._username, self._password)
                client.send_message(message)

        await run_in_threadpool(_send)


@lru_cache
def get_email_provider() -> EmailProvider:
    settings = get_settings()
    return SMTPEmailProvider(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_username,
        settings.smtp_password,
        settings.smtp_use_tls,
        settings.smtp_from_address,
    )
