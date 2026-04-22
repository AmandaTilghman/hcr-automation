"""
PRX Uploader (Browser Automation)
==================================
Uses Playwright to automate the PRX Exchange multi-tab upload workflow.

Tab flow: Basics → Details → Permissions → Publish
Each section within a tab has its own Save button that must be clicked.

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
    """Browser-based PRX uploader using Playwright."""

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
        """Launch browser and log into PRX Exchange."""
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
                'input[type="submit"], button[type="submit"], '
                'button:has-text("Log in"), button:has-text("Sign in")'
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

    def _screenshot(self, name: str):
        try:
            self.page.screenshot(path=f"prx-{name}.png")
            logger.info(f"Screenshot: prx-{name}.png")
        except Exception:
            pass

    def _click_save_and_continue(self):
        logger.info("Clicking Save and Continue...")
        btn = self.page.locator(
            'input[value*="Save and Continue"], '
            'button:has-text("Save and Continue")'
        ).first
        btn.click()
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
            logger.warning(f"Could not extract date from filename: {e}")
        return datetime.now().strftime("%B %d, %Y")

    # =========================================================================
    # TAB 1: BASICS
    # =========================================================================
    def _fill_basics_tab(self, audio_path: Path, title: str, description: str):
        logger.info("=== BASICS TAB ===")

        # Upload audio
        logger.info(f"Uploading audio: {audio_path.name}")
        try:
            file_input = self.page.locator('input[type="file"]').first
            file_input.set_input_files(str(audio_path))
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

        # Series — use JavaScript
        if self.series_names:
            logger.info("Adding to series...")
            try:
                result = self.page.evaluate("""
                    () => {
                        const labels = document.querySelectorAll('label');
                        for (const label of labels) {
                            if (label.textContent.includes('Add this piece to a series')) {
                                label.click();
                                return 'clicked';
                            }
                        }
                        return 'not found';
                    }
                """)
                logger.info(f"Series checkbox: {result}")
                time.sleep(3)

                # Make dropdown visible and select
                for name in self.series_names:
                    logger.info(f"Selecting series: {name}")
                    selected = self.page.evaluate("""
                        (name) => {
                            const sel = document.querySelector('#piece_series_id');
                            if (!sel) return 'no select found';
                            // Unhide
                            let el = sel;
                            while (el) {
                                el.style.display = '';
                                el.style.visibility = 'visible';
                                el.hidden = false;
                                el = el.parentElement;
                            }
                            sel.style.display = 'block';
                            const opts = Array.from(sel.options);
                            const match = opts.find(o => o.text.trim().includes(name));
                            if (match) {
                                sel.value = match.value;
                                sel.dispatchEvent(new Event('change', {bubbles: true}));
                                return 'selected: ' + match.text;
                            }
                            return 'no match for: ' + name;
                        }
                    """, self.series_names[0])
                    logger.info(f"Series result: {selected}")
                    time.sleep(1)
            except Exception as e:
                logger.warning(f"Series failed: {e}")

        # Title
        logger.info(f"Setting title: {title}")
        try:
            self.page.locator('input[name*="title"], input#piece_title').first.fill(title)
        except Exception as e:
            logger.warning(f"Title failed: {e}")

        # Short Description
        logger.info("Setting short description...")
        try:
            self.page.locator(
                'textarea[name*="short_description"], textarea[name*="description"]'
            ).first.fill(description[:200])
        except Exception as e:
            logger.warning(f"Description failed: {e}")

        logger.info("Skipping content advisory for now...")

        self._screenshot("basics-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 2: DETAILS
    # =========================================================================
    def _fill_details_tab(self, tags: list):
        logger.info("=== DETAILS TAB ===")

        # --- Producer: fill "Add Producer Name" input, click "Add Producer" ---
        if self.producer_name:
            logger.info(f"Adding producer: {self.producer_name}")
            try:
                # The producer input is near the "Add Producer" button
                # Use JS to find the text input in the producers section
                self.page.evaluate("""
                    (name) => {
                        // Find all text inputs
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (const inp of inputs) {
                            // Check if this input is near "Producer" text
                            const parent = inp.closest('div, fieldset, section, p');
                            if (parent && parent.textContent.includes('Producer')) {
                                inp.value = name;
                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                return 'filled';
                            }
                        }
                        // Fallback: look for input near "Add Producer" button
                        const btn = Array.from(document.querySelectorAll('input[type="submit"], button'))
                            .find(b => b.value?.includes('Add Producer') || b.textContent?.includes('Add Producer'));
                        if (btn) {
                            const container = btn.closest('div, fieldset, section');
                            if (container) {
                                const inp = container.querySelector('input[type="text"]');
                                if (inp) {
                                    inp.value = name;
                                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                                    return 'filled via button neighbor';
                                }
                            }
                        }
                        return 'not found';
                    }
                """, self.producer_name)
                time.sleep(1)

                # Click "Add Producer" button
                add_btn = self.page.locator(
                    'input[value*="Add Producer"], button:has-text("Add Producer")'
                )
                if add_btn.count() > 0:
                    add_btn.first.click()
                    time.sleep(2)
                    logger.info("Producer added.")
                else:
                    logger.warning("Add Producer button not found")
            except Exception as e:
                logger.warning(f"Producer failed: {e}")

        # --- Image: choose file, fill caption/credit, click Save Image ---
        if self.image_path and Path(self.image_path).exists():
            logger.info(f"Uploading image: {self.image_path}")
            try:
                # Check "I want to use an image to upload" or similar checkbox
                upload_checkbox = self.page.locator('text=want to use an image')
                if upload_checkbox.count() > 0:
                    upload_checkbox.first.click()
                    time.sleep(1)

                # Find the image file input (Choose File button)
                file_inputs = self.page.locator('input[type="file"]').all()
                for inp in file_inputs:
                    # Skip the audio file input at top
                    name_attr = inp.get_attribute("name") or ""
                    accept_attr = inp.get_attribute("accept") or ""
                    if "image" in name_attr.lower() or "image" in accept_attr.lower():
                        inp.set_input_files(str(Path(self.image_path).resolve()))
                        logger.info("Image file selected.")
                        time.sleep(2)
                        break
                else:
                    # Try any file input that's not the first one (audio)
                    if len(file_inputs) > 1:
                        file_inputs[1].set_input_files(str(Path(self.image_path).resolve()))
                        logger.info("Image file selected (second file input).")
                        time.sleep(2)

                # Click "Save Image"
                save_img = self.page.locator(
                    'input[value*="Save Image"], button:has-text("Save Image")'
                )
                if save_img.count() > 0:
                    save_img.first.click()
                    time.sleep(2)
                    logger.info("Image saved.")
            except Exception as e:
                logger.warning(f"Image upload failed: {e}")

        # --- Tags: fill Additional Tags field, click Save Your Tags ---
        if tags:
            tag_string = ", ".join(tags)
            logger.info(f"Setting additional tags: {tag_string}")
            try:
                # Find the "Additional Tags" input
                # It's a text input near "Save Your Tags" button
                self.page.evaluate("""
                    (tagStr) => {
                        // Find the Save Your Tags button
                        const btns = Array.from(document.querySelectorAll('input[type="submit"], button'));
                        const saveBtn = btns.find(b =>
                            (b.value || b.textContent || '').includes('Save Your Tags')
                        );
                        if (saveBtn) {
                            const container = saveBtn.closest('div, fieldset, section');
                            if (container) {
                                const inp = container.querySelector('input[type="text"], textarea');
                                if (inp) {
                                    inp.value = tagStr;
                                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                                    return 'filled';
                                }
                            }
                        }
                        return 'not found';
                    }
                """, tag_string)
                time.sleep(1)

                # Click "Save Your Tags"
                save_tags = self.page.locator(
                    'input[value*="Save Your Tags"], button:has-text("Save Your Tags")'
                )
                if save_tags.count() > 0:
                    save_tags.first.click()
                    time.sleep(2)
                    logger.info("Tags saved.")
            except Exception as e:
                logger.warning(f"Tags failed: {e}")

        # --- Production Date ---
        try:
            date_input = self.page.locator(
                'input[name*="produced_on"], input[name*="production_date"], '
                'input[id*="produced"], input[id*="production_date"]'
            )
            if date_input.count() > 0:
                today = datetime.now().strftime("%m/%d/%Y")
                date_input.first.fill(today)
                logger.info(f"Production date set: {today}")
        except Exception as e:
            logger.warning(f"Production date failed: {e}")

        self._screenshot("details-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 3: PERMISSIONS
    # =========================================================================
    def _fill_permissions_tab(self):
        logger.info("=== PERMISSIONS TAB ===")

        # Pricing: keep default (0 points) — no action needed
        logger.info("Pricing: keeping default (0 points)")

        # Webcast: "only with permission"
        logger.info("Setting webcast to 'only with permission'...")
        try:
            # Use JavaScript to find and click the right radio button
            self.page.evaluate("""
                () => {
                    // Find all radio buttons
                    const radios = document.querySelectorAll('input[type="radio"]');
                    for (const radio of radios) {
                        // Get the associated label
                        const label = radio.closest('label') ||
                            document.querySelector(`label[for="${radio.id}"]`);
                        const text = label?.textContent || '';
                        // Match "only with permission" for webcast (first occurrence)
                        if (text.includes('only with permission') &&
                            (radio.name.includes('offer') || radio.name.includes('webcast') ||
                             radio.name.includes('listen'))) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.click();
                            return 'webcast set';
                        }
                    }
                    // Fallback: just click any "only with permission" radio
                    const labels = document.querySelectorAll('label');
                    for (const label of labels) {
                        if (label.textContent.trim() === 'only with permission') {
                            label.click();
                            return 'clicked label';
                        }
                    }
                    return 'not found';
                }
            """)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Webcast permission failed: {e}")

        # Edit/excerpt: "never"
        logger.info("Setting edit/excerpt to 'never'...")
        try:
            self.page.evaluate("""
                () => {
                    const radios = document.querySelectorAll('input[type="radio"]');
                    for (const radio of radios) {
                        const label = radio.closest('label') ||
                            document.querySelector(`label[for="${radio.id}"]`);
                        const text = label?.textContent?.trim() || '';
                        if (text.toLowerCase() === 'never' ||
                            (text.includes('never') && 
                             (radio.name.includes('edit') || radio.name.includes('excerpt')))) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            radio.click();
                            return 'excerpt set to never';
                        }
                    }
                    // Fallback
                    const labels = document.querySelectorAll('label');
                    for (const label of labels) {
                        if (label.textContent.trim().toLowerCase() === 'never') {
                            label.click();
                            return 'clicked never label';
                        }
                    }
                    return 'not found';
                }
            """)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Edit/excerpt failed: {e}")

        self._screenshot("permissions-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 4: PUBLISH
    # =========================================================================
    def _publish(self) -> str:
        logger.info("=== PUBLISH TAB ===")

        if self.auto_publish:
            logger.info("Publishing piece...")
            try:
                publish_btn = self.page.locator(
                    'input[value*="Publish"], button:has-text("Publish"), '
                    'a:has-text("Publish")'
                ).first
                publish_btn.click()
                self.page.wait_for_load_state("networkidle")
                time.sleep(3)
                logger.info("Piece published!")
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
