"""
Email Watcher
=============
Connects to IMAP inbox, looks for unread notification emails
matching the configured filters, and returns the notification details.
"""

import imaplib
import email
from email.header import decode_header
import logging

import re

logger = logging.getLogger("radio-automation.email")


def extract_keywords(body: str) -> list:
    """
    Extract keywords from the email body.
    Looks for 'Key Words' followed by a comma-separated list.
    """
    if not body:
        return []

    # Match variations: "Key Words", "Keywords", "KEY WORDS", "key words", etc.
    # Keywords can be on the same line or the next line(s)
    match = re.search(
        r'key\s*words?\s*[:\n]\s*(.+?)(?:\n\s*\n|\n\s*-|\Z)',
        body,
        re.DOTALL | re.IGNORECASE
    )

    if not match:
        return []

    raw = match.group(1).strip()
    # Split by comma, clean up each tag
    tags = [t.strip().rstrip(',').strip() for t in raw.split(',')]
    # Remove empty strings
    tags = [t for t in tags if t]

    logger.info(f"Extracted {len(tags)} keywords from email: {', '.join(tags)}")
    return tags


def decode_subject(subject_raw) -> str:
    """Decode email subject which may be encoded."""
    decoded_parts = decode_header(subject_raw)
    subject = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            subject += part.decode(encoding or "utf-8", errors="replace")
        else:
            subject += part
    return subject


def check_for_notification(email_config: dict) -> dict | None:
    """
    Check IMAP inbox for an unprocessed notification email.

    Returns dict with email details if found, None otherwise:
    {
        "email_id": str,
        "subject": str,
        "from": str,
        "date": str,
        "body_preview": str,
    }
    """
    server = email_config["imap_server"]
    port = email_config.get("imap_port", 993)
    username = email_config["username"]
    password = email_config["password"]
    from_filter = email_config.get("from_filter", "")
    subject_filter = email_config.get("subject_filter", "")
    processed_folder = email_config.get("processed_folder", "Processed")

    try:
        # Connect
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(username, password)
        mail.select("INBOX")

        # Build search criteria
        criteria = ["UNSEEN"]
        if from_filter:
            criteria.append(f'FROM "{from_filter}"')
        if subject_filter:
            criteria.append(f'SUBJECT "{subject_filter}"')

        search_query = " ".join(criteria)
        logger.debug(f"IMAP search: {search_query}")

        status, messages = mail.search(None, *criteria)
        if status != "OK" or not messages[0]:
            logger.debug("No matching emails found.")
            mail.logout()
            return None

        # Get the most recent matching email
        email_ids = messages[0].split()
        latest_id = email_ids[-1]  # Most recent

        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        if status != "OK":
            logger.error(f"Failed to fetch email {latest_id}")
            mail.logout()
            return None

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_subject(msg["Subject"] or "")
        sender = msg["From"] or ""
        date = msg["Date"] or ""
        message_id = msg["Message-ID"] or str(latest_id)

        # Extract body preview
        body_preview = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    body_preview = part.get_payload(decode=True).decode(
                        charset, errors="replace"
                    )[:500]
                    break
        else:
            charset = msg.get_content_charset() or "utf-8"
            body_preview = msg.get_payload(decode=True).decode(
                charset, errors="replace"
            )[:500]

        # Ensure the "Processed" folder exists, then move the email there
        try:
            mail.create(processed_folder)
        except Exception:
            pass  # Folder may already exist

        mail.copy(latest_id, processed_folder)
        mail.store(latest_id, "+FLAGS", "\\Deleted")
        mail.expunge()

        mail.logout()

        # Extract keywords/tags from body
        tags = extract_keywords(body_preview)

        return {
            "email_id": message_id,
            "subject": subject,
            "from": sender,
            "date": date,
            "body_preview": body_preview.strip(),
            "tags": tags,
        }

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        return None
    except Exception as e:
        logger.error(f"Email check failed: {e}")
        return None
