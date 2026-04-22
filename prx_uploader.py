"""
PRX Uploader (Browser Automation)
==================================
Uses Playwright to automate the PRX Exchange multi-tab upload workflow:
  1. Log in to exchange.prx.org
  2. Basics tab: series, title, description, content advisory
  3. Details tab: producer, image, tags
  4. Permissions tab: pricing, license terms, edit/excerpt
  5. Publish tab: publish the piece

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
            email_field = self.page.locator(
                'input[name="login"], input[name="email"], '
                'input[type="email"], input[name="user[login]"]'
            ).first
            email_field.fill(self.username)

            password_field = self.page.locator(
                'input[name="password"], input[type="password"], '
                'input[name="user[password]"]'
            ).first
            password_field.fill(self.password)

            submit_btn = self.page.locator(
                'input[type="submit"], button[type="submit"], '
                'button:has-text("Log in"), button:has-text("Sign in")'
            ).first
            submit_btn.click()

            self.page.wait_for_load_state("networkidle")
            logger.info("Logged in successfully.")

        except PlaywrightTimeout:
            self.page.screenshot(path="prx-login-debug.png")
            raise RuntimeError(
                "Could not find login form on PRX. "
                "Screenshot saved to prx-login-debug.png"
            )

    def _close(self):
        """Clean up browser resources."""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _screenshot(self, name: str):
        """Save a debug screenshot."""
        path = f"prx-{name}.png"
        try:
            self.page.screenshot(path=path)
            logger.info(f"Screenshot: {path}")
        except Exception:
            pass

    def _click_save_and_continue(self):
        """Click 'Save and Continue' to advance to the next tab."""
        logger.info("Clicking Save and Continue...")
        btn = self.page.locator(
            'input[value*="Save and Continue"], '
            'button:has-text("Save and Continue"), '
            'input[value*="save and continue"]'
        ).first
        btn.click()
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)

    def _extract_date_from_filename(self, filename: str) -> str:
        """
        Extract date from filename like '4999_HCR-LFA 04.22.26.wav'
        Returns formatted date string like 'April 22, 2026'
        """
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
        """Fill the Basics tab: upload audio, series, title, description."""
        logger.info("=== BASICS TAB ===")

        # --- Upload audio file ---
        logger.info(f"Uploading audio: {audio_path.name}")
        try:
            file_input = self.page.locator('input[type="file"]').first
            file_input.set_input_files(str(audio_path))
            logger.info("Audio file selected, waiting for upload...")
            time.sleep(5)

            # Wait for upload to finish
            try:
                self.page.wait_for_selector(
                    '.upload-progress, .uploading, .processing',
                    state='hidden',
                    timeout=300000,
                )
            except PlaywrightTimeout:
                logger.warning("Upload progress indicator didn't clear — continuing")
        except Exception as e:
            logger.error(f"Audio upload failed: {e}")

        # --- Add to series ---
        if self.series_names:
            logger.info("Adding to series...")
            try:
                # Use JavaScript to check the checkbox and show the dropdown
                # This is more reliable than trying to click through Playwright
                result = self.page.evaluate("""
                    () => {
                        // Find all checkboxes and labels
                        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                        let found = false;
                        
                        // Try to find series checkbox by nearby label text
                        const labels = document.querySelectorAll('label');
                        for (const label of labels) {
                            if (label.textContent.includes('Add this piece to a series')) {
                                // Click the label
                                label.click();
                                found = true;
                                break;
                            }
                        }
                        
                        if (!found) {
                            // Try finding checkbox by ID patterns
                            const cb = document.querySelector(
                                '[id*="series"][type="checkbox"], ' +
                                '[name*="series"][type="checkbox"]'
                            );
                            if (cb) {
                                cb.checked = true;
                                cb.dispatchEvent(new Event('change', {bubbles: true}));
                                cb.dispatchEvent(new Event('click', {bubbles: true}));
                                found = true;
                            }
                        }
                        
                        return found ? 'checkbox clicked' : 'checkbox not found';
                    }
                """)
                logger.info(f"Series checkbox: {result}")
                time.sleep(3)
                self._screenshot("series-after-checkbox")

                # Now try to select the series
                # First, make sure the dropdown is visible
                self.page.evaluate("""
                    () => {
                        const sel = document.querySelector('#piece_series_id');
                        if (sel) {
                            // Walk up and unhide any hidden parents
                            let el = sel;
                            while (el) {
                                el.style.display = '';
                                el.style.visibility = 'visible';
                                el.hidden = false;
                                if (el.classList) el.classList.remove('hidden', 'hide', 'd-none');
                                el = el.parentElement;
                            }
                            sel.style.display = 'block';
                        }
                    }
                """)
                time.sleep(1)

                for name in self.series_names:
                    logger.info(f"Selecting series: {name}")
                    # Use JavaScript to set the value directly
                    selected = self.page.evaluate(f"""
                        () => {{
                            const sel = document.querySelector('#piece_series_id');
                            if (!sel) return 'no select found';
                            const opts = Array.from(sel.options);
                            const match = opts.find(o => 
                                o.text.trim().includes("{name.replace('"', '\\"')}")
                            );
                            if (match) {{
                                sel.value = match.value;
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                sel.dispatchEvent(new Event('input', {{bubbles: true}}));
                                return 'selected: ' + match.text;
                            }}
                            return 'no matching option for: {name.replace('"', '\\"')}';
                        }}
                    """)
                    logger.info(f"Series result: {selected}")
                    time.sleep(1)
                    break  # Single select — only one series

                self._screenshot("series-selected")

            except Exception as e:
                logger.warning(f"Series selection failed: {e}")

        # --- Title ---
        logger.info(f"Setting title: {title}")
        try:
            title_field = self.page.locator(
                'input[name*="title"], input#piece_title'
            ).first
            title_field.fill(title)
        except Exception as e:
            logger.warning(f"Could not set title: {e}")

        # --- Short Description ---
        logger.info("Setting short description...")
        try:
            desc_field = self.page.locator(
                'textarea[name*="short_description"], '
                'textarea[name*="description"]'
            ).first
            desc_field.fill(description[:200])
        except Exception as e:
            logger.warning(f"Could not set description: {e}")

        # --- Content Advisory (sensitive language) ---
        logger.info("Checking content advisory...")
        try:
            advisory_label = self.page.locator('text=Include content advisory')
            if advisory_label.count() > 0:
                advisory_label.first.click()
                time.sleep(1)
                # Select "Explicit" if available
                explicit = self.page.locator(
                    'label:has-text("Explicit"), input[value*="explicit"]'
                )
                if explicit.count() > 0:
                    explicit.first.click()
        except Exception as e:
            logger.warning(f"Could not set content advisory: {e}")

        self._screenshot("basics-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 2: DETAILS
    # =========================================================================
    def _fill_details_tab(self, tags: list):
        """Fill the Details tab: producer, image, tags."""
        logger.info("=== DETAILS TAB ===")

        # --- Producer ---
        if self.producer_name:
            logger.info(f"Adding producer: {self.producer_name}")
            try:
                producer_input = self.page.locator(
                    'input[name*="producer"], input[placeholder*="producer" i], '
                    'input[placeholder*="Producer"]'
                ).first
                producer_input.fill(self.producer_name)
                time.sleep(0.5)

                # Click "Add Producer" button
                add_producer = self.page.locator(
                    'button:has-text("Add Producer"), '
                    'input[value*="Add Producer"], '
                    'a:has-text("Add Producer")'
                )
                if add_producer.count() > 0:
                    add_producer.first.click()
                    time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not add producer: {e}")

        # --- Image ---
        if self.image_path and Path(self.image_path).exists():
            logger.info(f"Uploading image: {self.image_path}")
            try:
                # Find image file input
                file_inputs = self.page.locator('input[type="file"]').all()
                for inp in file_inputs:
                    accept = inp.get_attribute("accept") or ""
                    name = inp.get_attribute("name") or ""
                    if "image" in accept.lower() or "image" in name.lower():
                        inp.set_input_files(str(Path(self.image_path).resolve()))
                        time.sleep(2)
                        # Click Save Image if there's a button
                        save_img = self.page.locator(
                            'button:has-text("Save Image"), '
                            'input[value*="Save Image"]'
                        )
                        if save_img.count() > 0:
                            save_img.first.click()
                            time.sleep(2)
                        logger.info("Image uploaded.")
                        break
                else:
                    # If no image-specific input, try the last file input
                    if len(file_inputs) > 1:
                        file_inputs[-1].set_input_files(
                            str(Path(self.image_path).resolve())
                        )
                        time.sleep(2)
            except Exception as e:
                logger.warning(f"Could not upload image: {e}")

        # --- Tags ---
        if tags:
            tag_string = ", ".join(tags)
            logger.info(f"Setting tags: {tag_string}")
            try:
                # Look for the additional tags textarea/input
                tags_input = self.page.locator(
                    'textarea[name*="tag"], input[name*="tag"], '
                    'textarea[placeholder*="tag" i], input[placeholder*="tag" i]'
                )
                # Try to find the "Additional Tags" or "Your Tags" field
                additional = self.page.locator(
                    'textarea[name*="user_tag"], input[name*="user_tag"], '
                    'textarea[name*="additional"], input[name*="additional"]'
                )
                if additional.count() > 0:
                    additional.first.fill(tag_string)
                elif tags_input.count() > 0:
                    tags_input.first.fill(tag_string)
                time.sleep(0.5)

                # Click "Save Your Tags" or "Add" button if present
                save_tags = self.page.locator(
                    'button:has-text("Save"), input[value*="Save Your Tags"], '
                    'button:has-text("Add")'
                )
                if save_tags.count() > 0:
                    save_tags.first.click()
                    time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not set tags: {e}")

        self._screenshot("details-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 3: PERMISSIONS
    # =========================================================================
    def _fill_permissions_tab(self):
        """Fill the Permissions tab: pricing, license, edit/excerpt."""
        logger.info("=== PERMISSIONS TAB ===")

        # --- Pricing: keep default (0 points) ---
        # The default is already "Default (0 points/min)" so we don't need
        # to change it, but verify if needed
        logger.info("Pricing: keeping default (0 points)")

        # --- Webcast: "only with permission" ---
        logger.info("Setting webcast to 'only with permission'...")
        try:
            permission_radio = self.page.locator(
                'label:has-text("only with permission")'
            )
            # There may be multiple "only with permission" labels
            # The first one should be for webcast
            if permission_radio.count() > 0:
                permission_radio.first.click()
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Could not set webcast permission: {e}")

        # --- Edit/excerpt: "never" ---
        logger.info("Setting edit/excerpt to 'never'...")
        try:
            never_radio = self.page.locator('label:has-text("never")')
            if never_radio.count() > 0:
                never_radio.first.click()
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Could not set edit/excerpt: {e}")

        self._screenshot("permissions-filled")
        self._click_save_and_continue()

    # =========================================================================
    # TAB 4: PUBLISH
    # =========================================================================
    def _publish(self) -> str:
        """Click Publish on the Publish tab. Returns the piece URL."""
        logger.info("=== PUBLISH TAB ===")

        if self.auto_publish:
            logger.info("Publishing piece...")
            try:
                publish_btn = self.page.locator(
                    'input[value*="Publish"], button:has-text("Publish"), '
                    'input[value*="Publish!"], a:has-text("Publish")'
                ).first
                publish_btn.click()
                self.page.wait_for_load_state("networkidle")
                time.sleep(3)
                logger.info("Piece published!")
            except Exception as e:
                logger.warning(f"Could not click publish: {e}")
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
        """
        Full multi-tab workflow:
        Basics → Details → Permissions → Publish
        """
        audio_path = Path(audio_path)
        all_tags = list(set((tags or []) + self.default_tags))

        # Build title and description from filename date
        date_str = self._extract_date_from_filename(audio_path.name)
        piece_title = f"Heather Cox Richardson - Letters From An American {date_str}"
        piece_description = piece_title

        try:
            # Navigate to create new piece
            logger.info("Navigating to Create New Piece...")
            self.page.goto(PRX_NEW_PIECE_URL, wait_until="networkidle")
            time.sleep(2)

            # Tab 1: Basics
            self._fill_basics_tab(audio_path, piece_title, piece_description)

            # Tab 2: Details
            self._fill_details_tab(all_tags)

            # Tab 3: Permissions
            self._fill_permissions_tab()

            # Tab 4: Publish
            piece_url = self._publish()

            return piece_url

        except Exception as e:
            self._screenshot("error")
            raise RuntimeError(f"PRX upload failed: {e}")

        finally:
            self._close()
