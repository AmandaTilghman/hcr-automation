"""
PRX Uploader (Browser Automation)
==================================
Uses Playwright to automate the PRX Exchange multi-tab upload workflow.
Field IDs verified from actual PRX HTML dumps.

Tab flow: Basics → Details → Permissions → Publish

Requires: playwright (pip install playwright && playwright install chromium)
"""

import logging
import time
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("radio-automation.prx")

PRX_LOGIN_URL = "https://exchange.prx.org/login"
PRX_NEW_PIECE_URL = "https://exchange.prx.org/pieces/new"


class PRXClient:

    def __init__(self, config: dict):
        self.config = config
        self.username = config["username"]
        self.password = config["password"]
        self.default_tags = config.get("default_tags", [])
        self.series_names = config.get("series_names", [])
        self.auto_publish = config.get("auto_publish", True)
        self.headless = config.get("headless", True)
        self.producer_name = config.get("producer_name", "")
        self.image_path = config.get("image_path", "")
        self.browser = None
        self.page = None
        self.playwright = None

    def authenticate(self):
        logger.info("Launching browser and logging into PRX...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        context = self.browser.new_context()
        self.page = context.new_page()

        self.page.goto(PRX_LOGIN_URL, wait_until="networkidle")
        self.page.wait_for_load_state("networkidle")

        try:
            self.page.locator(
                'input[name="login"], input[name="email"], '
                'input[type="email"], input[name="user[login]"]'
            ).first.fill(self.username)
            self.page.locator(
                'input[name="password"], input[type="password"], '
                'input[name="user[password]"]'
            ).first.fill(self.password)
            self.page.locator(
                'input[type="submit"], button[type="submit"]'
            ).first.click()
            self.page.wait_for_load_state("networkidle")
            logger.info("Logged in successfully.")
        except PlaywrightTimeout:
            self.page.screenshot(path="prx-login-debug.png")
            raise RuntimeError("Could not find login form on PRX.")

    def _close(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _send_tag_failure_email(self, tags: str, error: str):
        """Send notification to Amanda that tags didn't work."""
        import smtplib
        from email.mime.text import MIMEText

        try:
            # Use the same IMAP credentials for sending
            import yaml
            with open('config.yaml') as f:
                cfg = yaml.safe_load(f)
            email_cfg = cfg.get('email', {})

            msg = MIMEText(
                f"The automated PRX upload completed but tags could not be saved.\n\n"
                f"Tags attempted:\n{tags}\n\n"
                f"Error: {error}\n\n"
                f"Please add tags manually in PRX."
            )
            msg['Subject'] = 'HCR Automation: Tags failed — manual entry needed'
            msg['From'] = email_cfg['username']
            msg['To'] = 'amanda@whcp.org'

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(email_cfg['username'], email_cfg['password'])
                server.send_message(msg)

            logger.info("Tag failure notification sent to amanda@whcp.org")
        except Exception as e:
            logger.warning(f"Could not send tag failure email: {e}")

    def _screenshot(self, name: str):
        try:
            self.page.screenshot(path=f"prx-{name}.png")
            logger.info(f"Screenshot: prx-{name}.png")
        except Exception:
            pass

    def _click_save_and_continue(self):
        logger.info("Clicking Save and Continue...")
        self.page.locator('input[value="Save and Continue"]').click()
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)

    def _extract_date_from_filename(self, filename: str) -> str:
        try:
            import re
            match = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', filename)
            if match:
                month, day, year = match.groups()
                dt = datetime(2000 + int(year), int(month), int(day))
                return dt.strftime("%B %d, %Y")
        except Exception as e:
            logger.warning(f"Could not extract date: {e}")
        return datetime.now().strftime("%B %d, %Y")

    # =========================================================================
    # TAB 1: BASICS
    # =========================================================================
    def _fill_basics_tab(self, audio_path: Path, title: str, description: str):
        logger.info("=== BASICS TAB ===")

        # Upload audio — input#evaporate_files accepts .mp2
        logger.info(f"Uploading audio: {audio_path.name}")
        try:
            self.page.locator('#evaporate_files').set_input_files(str(audio_path))
            logger.info("Audio file selected, waiting for upload...")
            time.sleep(5)
            try:
                self.page.wait_for_selector(
                    '.upload-progress, .uploading, .processing',
                    state='hidden', timeout=300000,
                )
            except PlaywrightTimeout:
                logger.warning("Upload progress didn't clear — continuing")
        except Exception as e:
            logger.error(f"Audio upload failed: {e}")

        # Series — checkbox #add_to_series toggles #select_series
        if self.series_names:
            logger.info("Adding to series...")
            try:
                # Click the checkbox via JS (it uses onclick to toggle)
                self.page.evaluate("""
                    () => {
                        const cb = document.querySelector('#add_to_series');
                        if (cb && !cb.checked) {
                            cb.click();
                        }
                    }
                """)
                time.sleep(2)

                # Select series from #piece_series_id
                name = self.series_names[0]
                logger.info(f"Selecting series: {name}")
                self.page.evaluate("""
                    (name) => {
                        const sel = document.querySelector('#piece_series_id');
                        if (!sel) return;
                        // Make visible
                        sel.style.display = 'block';
                        let el = sel.parentElement;
                        while (el) {
                            el.style.display = '';
                            el.hidden = false;
                            el = el.parentElement;
                        }
                        const opts = Array.from(sel.options);
                        const match = opts.find(o => o.text.trim().includes(name));
                        if (match) {
                            sel.value = match.value;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }
                """, name)
                logger.info(f"Selected series: {name}")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Series failed: {e}")

        # Title — #piece_title
        logger.info(f"Setting title: {title}")
        try:
            self.page.locator('#piece_title').fill(title)
        except Exception as e:
            logger.warning(f"Title failed: {e}")

        # Short Description — #piece_short_description
        logger.info("Setting short description...")
        try:
            self.page.locator('#piece_short_description').fill(description[:200])
        except Exception as e:
            logger.warning(f"Description failed: {e}")

        # Content Advisory — skip for now, can be set manually
        # The dynamic checkbox/radio interaction is unreliable in automation
        logger.info("Skipping content advisory (set manually if needed).")

        self._screenshot("basics-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 2: DETAILS
    # =========================================================================
    def _fill_details_tab(self, tags: list):
        logger.info("=== DETAILS TAB ===")

        # Producer — #producer_name input + "Add Producer" submit via AJAX
        if self.producer_name:
            logger.info(f"Adding producer: {self.producer_name}")
            try:
                self.page.locator('#producer_name').fill(self.producer_name, timeout=5000)
                time.sleep(1)
                self.page.locator('input[value="Add Producer"]').click(timeout=5000)
                time.sleep(5)
                logger.info("Producer added.")
            except Exception as e:
                logger.warning(f"Producer failed: {e} — skipping")

        # Image — the image upload section is visible by default
        #        #add_images checkbox HIDES it ("I don't have an image")
        #        So do NOT click the checkbox — just upload directly
        if self.image_path and Path(self.image_path).exists():
            logger.info(f"Uploading image: {self.image_path}")
            try:
                # Make sure the checkbox is NOT checked (unchecked = image section visible)
                self.page.evaluate("""
                    () => {
                        const cb = document.querySelector('#add_images');
                        if (cb && cb.checked) cb.click();
                    }
                """)
                time.sleep(1)

                # Upload image file
                self.page.locator('#piece_image_uploaded_data').set_input_files(
                    str(Path(self.image_path).resolve())
                )
                time.sleep(2)

                # Click Save Image
                self.page.locator('#piece_image_submit').click()
                time.sleep(3)
                logger.info("Image saved.")
            except Exception as e:
                logger.warning(f"Image upload failed: {e}")

        # Tags — #piece_tag_list + submit form via AJAX (same as PRX does)
        if tags:
            tag_string = ", ".join(tags)
            logger.info(f"Setting tags: {tag_string}")
            try:
                # Fill the field and submit the form the same way PRX does
                result = self.page.evaluate("""
                    (tagStr) => {
                        const input = document.querySelector('#piece_tag_list');
                        if (!input) return 'input not found';
                        input.value = tagStr;
                        
                        // Find and submit the form containing this input
                        const form = input.closest('form');
                        if (!form) return 'form not found';
                        
                        // Trigger the form's onsubmit (which does the AJAX call)
                        if (form.onsubmit) {
                            form.onsubmit();
                            return 'submitted via onsubmit';
                        }
                        
                        // Fallback: submit normally
                        form.submit();
                        return 'submitted normally';
                    }
                """, tag_string)
                logger.info(f"Tags submit result: {result}")
                time.sleep(3)
                logger.info("Tags saved.")
            except Exception as e:
                logger.warning(f"Tags failed: {e} — clearing and notifying")
                try:
                    self.page.evaluate("() => { const el = document.querySelector('#piece_tag_list'); if (el) { el.value = ''; el.closest('form')?.onsubmit?.(); }}")
                    time.sleep(2)
                except Exception:
                    pass
                self._send_tag_failure_email(tag_string, str(e))

        # Topics — check "Politics" and "News" as defaults for HCR
        logger.info("Setting topics: Politics, News")
        try:
            self.page.evaluate("""
                () => {
                    const politics = document.querySelector('#topics_Politics_name');
                    const news = document.querySelector('#topics_News_name');
                    if (politics && !politics.checked) politics.click();
                    if (news && !news.checked) news.click();
                }
            """)
            time.sleep(1)
            self.page.locator('input[value="Save Topics"]').click()
            time.sleep(2)
            logger.info("Topics saved.")
        except Exception as e:
            logger.warning(f"Topics failed: {e}")

        self._screenshot("details-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 3: PERMISSIONS
    # =========================================================================
    def _fill_permissions_tab(self):
        logger.info("=== PERMISSIONS TAB ===")

        # Pricing — #piece_point_level select, keep default (0 points)
        logger.info("Pricing: keeping default (0 points)")

        # Webcast — #license_website_usage_only_with_permission radio
        logger.info("Setting webcast to 'only with permission'...")
        try:
            self.page.locator('#license_website_usage_only_with_permission').click(force=True)
            time.sleep(1)
            logger.info("Webcast permission set.")
        except Exception as e:
            logger.warning(f"Webcast permission failed: {e}")

        # Edit/excerpt — #license_allow_edit_never radio
        logger.info("Setting edit/excerpt to 'never'...")
        try:
            self.page.locator('#license_allow_edit_never').click(force=True)
            time.sleep(1)
            logger.info("Edit/excerpt set to never.")
        except Exception as e:
            logger.warning(f"Edit/excerpt failed: {e}")

        self._screenshot("permissions-filled")

        # Save and Continue (saves permissions, may go to wrong tab)
        self._click_save_and_continue()

        # Navigate directly to the Publish step via URL
        logger.info("Navigating to Publish tab...")
        # Extract the piece slug from the current URL
        current_url = self.page.url
        # URL looks like: /pieces/616232-untitled-april-22-2026/edit...
        import re
        piece_match = re.search(r'/pieces/([^/]+)', current_url)
        if piece_match:
            piece_slug = piece_match.group(1)
            publish_url = f"https://exchange.prx.org/pieces/{piece_slug}/edit?step=preview"
            logger.info(f"Going to: {publish_url}")
            self.page.goto(publish_url, wait_until="networkidle")
            time.sleep(3)
        else:
            logger.warning(f"Could not extract piece slug from URL: {current_url}")

    # =========================================================================
    # TAB 4: PUBLISH
    # =========================================================================
    def _publish(self) -> str:
        logger.info("=== PUBLISH TAB ===")

        # Wait 30 seconds for audio processing to complete
        logger.info("Waiting 30 seconds for audio processing...")
        time.sleep(30)
        # Reload to get fresh page state
        self.page.reload(wait_until="networkidle")
        time.sleep(3)

        if self.auto_publish:
            logger.info("Publishing piece...")

            # Wait for publish button to appear (AJAX-loaded content)
            for wait in range(10):
                found = self.page.evaluate("""
                    () => {
                        const inputs = document.querySelectorAll('input[type="submit"]');
                        for (const inp of inputs) {
                            if (inp.value === 'Publish') return 'found';
                        }
                        // Also check for a publish link/button
                        const links = document.querySelectorAll('a, button');
                        for (const el of links) {
                            const text = el.textContent.trim();
                            if (text === 'Publish' && !el.closest('.create-piece-step')) {
                                return 'found-link';
                            }
                            if (text === 'Publish!') return 'found-link';
                        }
                        return 'not found';
                    }
                """)
                logger.info(f"Publish button search: {found}")
                if found.startswith('found'):
                    break
                time.sleep(3)

            try:
                result = self.page.evaluate("""
                    () => {
                        // Try input submit first
                        const inputs = document.querySelectorAll('input[type="submit"]');
                        for (const inp of inputs) {
                            if (inp.value === 'Publish') {
                                inp.click();
                                return 'clicked input';
                            }
                        }
                        // Try any non-nav Publish link/button
                        const els = document.querySelectorAll('a, button');
                        for (const el of els) {
                            const text = el.textContent.trim();
                            if ((text === 'Publish' || text === 'Publish!') && 
                                !el.closest('.create-piece-step')) {
                                el.click();
                                return 'clicked ' + el.tagName + ': ' + text;
                            }
                        }
                        return 'not found';
                    }
                """)
                logger.info(f"Publish result: {result}")
                time.sleep(5)
                self.page.wait_for_load_state("networkidle")
                time.sleep(2)
                if result != 'not found':
                    logger.info("Piece published!")
                else:
                    logger.warning("Could not find publish button")
            except Exception as e:
                logger.warning(f"Publish failed: {e}")
        else:
            logger.info("Auto-publish disabled — leaving as draft.")

        piece_url = self.page.url
        self._screenshot("published")
        logger.info(f"Piece URL: {piece_url}")
        return piece_url

    # =========================================================================
    # MAIN WORKFLOW
    # =========================================================================
    def create_and_upload_story(
        self,
        audio_path: Path | str,
        title: str = "",
        description: str = "",
        tags: list = None,
        publish: bool = False,
    ) -> str:
        audio_path = Path(audio_path)
        all_tags = list(set((tags or []) + self.default_tags))

        date_str = self._extract_date_from_filename(audio_path.name)
        piece_title = f"Heather Cox Richardson - Letters From An American {date_str}"
        piece_description = piece_title

        try:
            logger.info("Navigating to Create New Piece...")
            self.page.goto(PRX_NEW_PIECE_URL, wait_until="networkidle")
            time.sleep(2)

            self._fill_basics_tab(audio_path, piece_title, piece_description)
            self._fill_details_tab(all_tags)
            self._fill_permissions_tab()
            return self._publish()

        except Exception as e:
            self._screenshot("error")
            raise RuntimeError(f"PRX upload failed: {e}")

        finally:
            self._close()
