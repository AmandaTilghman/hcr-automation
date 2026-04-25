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


def detect_explicit_content(body: str) -> bool:
    """
    Scan the email body for mentions of explicit content that would
    trigger PRX's content advisory checkbox.
    """
    if not body:
        return False

    explicit_patterns = [
        r'\bexplicit\s+content\b',
        r'\bexplicit\s+language\b',
        r'\bstrong\s+language\b',
        r'\badult\s+content\b',
        r'\bcontent\s+advisory\b',
        r'\bexplicit\s+material\b',
        r'\bmature\s+content\b',
        r'\bprofanity\b',
        r'\bvulgar(?:ity)?\b',
        r'\bgraphic\s+(?:content|description|violence)\b',
    ]

    body_lower = body.lower()
    for pattern in explicit_patterns:
        if re.search(pattern, body_lower):
            logger.info(f"Explicit content detected (matched: {pattern})")
            return True

    return False


def extract_keywords(body: str) -> list:
    """
    Extract keywords from the email body.
    Looks for 'Key Words' followed by a comma-separated list.
    """
    if not body:
        return []

    # Match variations: "Key Words", "Keywords", "Tags", "TAGS", etc.
    match = re.search(
        r'(?:key\s*words?|tags?)\s*[:\n]\s*(.+?)(?:\n\s*\n|\n\s*-|\Z)',
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


def move_email_to_processed(email_config: dict, message_id: str):
    """
    Move a notification email to the Processed folder AFTER the pipeline succeeds.
    Called from main.py only on successful completion.
    """
    server = email_config["imap_server"]
    port = email_config.get("imap_port", 993)
    username = email_config["username"]
    password = email_config["password"]
    from_filter = email_config.get("from_filter", "")
    subject_filter = email_config.get("subject_filter", "")
    processed_folder = email_config.get("processed_folder", "Processed")

    try:
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(username, password)
        mail.select("INBOX")

        # Search for the specific email by Message-ID
        from datetime import datetime as _dt, timedelta as _td
        since_date = (_dt.now() - _td(days=3)).strftime("%d-%b-%Y")
        criteria = [f'SINCE "{since_date}"']
        if from_filter:
            criteria.append(f'FROM "{from_filter}"')

        status, messages = mail.search(None, *criteria)
        if status != "OK" or not messages[0]:
            logger.warning("Could not find email to move to Processed.")
            mail.logout()
            return

        for eid in messages[0].split():
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            mid = msg["Message-ID"] or str(eid)
            if mid == message_id:
                try:
                    mail.create(processed_folder)
                except Exception:
                    pass
                mail.copy(eid, processed_folder)
                mail.store(eid, "+FLAGS", "\\Deleted")
                mail.expunge()
                logger.info(f"Email moved to {processed_folder}: {message_id}")
                break

        mail.logout()
    except Exception as e:
        logger.warning(f"Could not move email to Processed: {e}")


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


def check_for_notification(email_config: dict, processed_ids: set = None) -> dict | None:
    """
    Check IMAP inbox for an unprocessed notification email.

    Uses date-based search (SINCE today) instead of UNSEEN so that
    emails already read by another client (phone, webmail) are still
    picked up.  Deduplication is handled via the processed_ids set
    (from ProcessingState) passed in by the caller.

    Returns dict with email details if found, None otherwise.
    """
    server = email_config["imap_server"]
    port = email_config.get("imap_port", 993)
    username = email_config["username"]
    password = email_config["password"]
    from_filter = email_config.get("from_filter", "")
    subject_filter = email_config.get("subject_filter", "")
    processed_folder = email_config.get("processed_folder", "Processed")

    if processed_ids is None:
        processed_ids = set()

    try:
        # Connect
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(username, password)
        mail.select("INBOX")

        # Build search criteria — date-based instead of UNSEEN
        # Look back 3 days to catch any missed emails (weekends, delays)
        from datetime import datetime as _dt, timedelta as _td
        since_date = (_dt.now() - _td(days=3)).strftime("%d-%b-%Y")
        criteria = [f'SINCE "{since_date}"']
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

        # Check all matching emails, newest first
        email_ids = messages[0].split()

        for eid in reversed(email_ids):
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                logger.error(f"Failed to fetch email {eid}")
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            message_id = msg["Message-ID"] or str(eid)

            # Skip already-processed emails
            if message_id in processed_ids:
                logger.debug(f"Email {message_id} already processed, skipping.")
                continue

            subject = decode_subject(msg["Subject"] or "")
            sender = msg["From"] or ""
            date = msg["Date"] or ""

            # Extract full body text (need enough to find keywords at the end)
            body_preview = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or "utf-8"
                        body_preview = part.get_payload(decode=True).decode(
                            charset, errors="replace"
                        )[:5000]
                        break
            else:
                charset = msg.get_content_charset() or "utf-8"
                body_preview = msg.get_payload(decode=True).decode(
                    charset, errors="replace"
                )[:5000]

            # DON'T move the email yet — wait until pipeline succeeds.
            # Deduplication is handled by processed_ids (from state.json).
            # Call move_email_to_processed() after the pipeline completes.

            mail.logout()

            # Extract keywords/tags from body
            tags = extract_keywords(body_preview)

            # Check for explicit content mentions
            has_explicit = detect_explicit_content(body_preview)

            return {
                "email_id": message_id,
                "subject": subject,
                "from": sender,
                "date": date,
                "body_preview": body_preview.strip(),
                "tags": tags,
                "has_explicit_content": has_explicit,
            }

        # All matching emails were already processed
        logger.debug("All matching emails already processed.")
        mail.logout()
        return None

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        return None
    except Exception as e:
        logger.error(f"Email check failed: {e}")
        return None
