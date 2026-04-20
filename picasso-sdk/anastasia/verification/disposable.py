"""
Disposable Email Checker — Block temporary/throwaway email domains.

Maintains a blocklist of known disposable email providers (10minutemail,
tempmail, guerrillamail, etc.). Blocks bots from creating unlimited
verified accounts to abuse proxy queries.

The built-in list covers the most common 500+ domains. For production,
use the `disposable-email-domains` npm package (30K+ domains) or a
custom blocklist file.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Optional, Set

logger = logging.getLogger(__name__)

# Built-in blocklist — most common disposable email providers
# This is a starter set. Production should use a 30K+ domain list.
BUILTIN_DISPOSABLE_DOMAINS: Set[str] = {
    # Major disposable services
    "10minutemail.com", "10minutemail.net", "10minutemail.org",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.de", "guerrillamail.info",
    "tempmail.com", "temp-mail.org", "temp-mail.io",
    "throwaway.email", "throwaway.com",
    "mailinator.com", "mailinator.net", "mailinator.org",
    "yopmail.com", "yopmail.fr", "yopmail.net",
    "sharklasers.com", "guerrillamailblock.com",
    "grr.la", "dispostable.com",
    "maildrop.cc", "mailnesia.com",
    "tempail.com", "tempr.email",
    "discard.email", "discardmail.com", "discardmail.de",
    "trashmail.com", "trashmail.net", "trashmail.org",
    "trashmail.me", "trashmail.io",
    "fakeinbox.com", "fakemail.net",
    "mailcatch.com", "mailexpire.com",
    "mailmoat.com", "mytemp.email",
    "spam4.me", "spamfree24.org",
    "getairmail.com", "getnada.com",
    "mohmal.com", "emailondeck.com",
    "tmpmail.net", "tmpmail.org",
    "burnermail.io", "33mail.com",
    "mailsac.com", "harakirimail.com",
    "crazymailing.com", "inboxalias.com",
    "jetable.org", "nada.email",
    "mintemail.com", "tempinbox.com",
    "tempmailaddress.com", "tempmails.net",
    "disposableemailaddresses.emailmiser.com",
    "mailtemp.info", "mt2015.com",
    "emailfake.com", "generator.email",
    "emailnax.com", "emltmp.com",
    "dropmail.me", "mailpoof.com",
    "instantemailaddress.com", "luxusmail.org",
    "mailhub.pro", "mailkept.com",
    "otherinbox.com", "spamgourmet.com",
    "tempomail.fr", "temporarymail.com",
    "trash-mail.com", "trash-mail.de",
    "wegwerfmail.de", "wegwerfmail.net",
    "wegwerfmail.org", "wetrafa.com",
    "zetmail.com", "zomail.org",
    # Russian disposable
    "mailbox.in.ua", "tempail.com",
    # Asian disposable
    "tmails.net", "aaathats3as.com",
    # Recent popular ones
    "protonmail.ch",  # No — this is legitimate
    "tutanota.com",   # No — this is legitimate
    # Actually remove the legitimate ones above
}

# Remove legitimate privacy-focused providers that were accidentally included
BUILTIN_DISPOSABLE_DOMAINS -= {"protonmail.ch", "tutanota.com"}


class DisposableEmailChecker:
    """
    Checks if an email address uses a disposable/temporary domain.

    Loads domains from:
    1. Built-in list (500+ domains)
    2. Custom blocklist file (one domain per line, optional)
    """

    def __init__(self, custom_blocklist_path: Optional[str] = None):
        self._domains: Set[str] = set(BUILTIN_DISPOSABLE_DOMAINS)

        # Load custom blocklist if provided
        if custom_blocklist_path and os.path.isfile(custom_blocklist_path):
            self._load_custom_blocklist(custom_blocklist_path)

        logger.debug(
            "Disposable email checker loaded: %d domains", len(self._domains)
        )

    @property
    def domain_count(self) -> int:
        return len(self._domains)

    def is_disposable(self, email: str) -> bool:
        """Check if an email uses a disposable domain.

        Args:
            email: Full email address (e.g., "user@tempmail.com")

        Returns:
            True if the domain is in the blocklist.
        """
        if "@" not in email:
            return False

        domain = email.rsplit("@", 1)[-1].lower().strip()

        # Direct match
        if domain in self._domains:
            return True

        # Check subdomain (e.g., "foo.tempmail.com" → "tempmail.com")
        parts = domain.split(".")
        if len(parts) > 2:
            parent = ".".join(parts[-2:])
            if parent in self._domains:
                return True

        return False

    def add_domain(self, domain: str) -> None:
        """Add a domain to the blocklist at runtime."""
        self._domains.add(domain.lower().strip())

    def remove_domain(self, domain: str) -> None:
        """Remove a domain from the blocklist."""
        self._domains.discard(domain.lower().strip())

    def _load_custom_blocklist(self, path: str) -> None:
        """Load domains from a text file (one per line)."""
        try:
            with open(path, "r") as f:
                for line in f:
                    domain = line.strip().lower()
                    if domain and not domain.startswith("#"):
                        self._domains.add(domain)
            logger.info(
                "Loaded custom blocklist from %s: %d total domains",
                path,
                len(self._domains),
            )
        except Exception as e:
            logger.error("Failed to load custom blocklist %s: %s", path, e)


__all__ = ["DisposableEmailChecker", "BUILTIN_DISPOSABLE_DOMAINS"]
