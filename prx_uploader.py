"""
PRX Uploader (Browser Automation)
==================================
Uses Playwright to automate the PRX Exchange upload workflow:
  1. Log in to exchange.prx.org
  2. Navigate to My PRX → Create New Piece
  3. Upload audio file
  4. Fill in title, description, tags, producer, image, pricing, permissions
  5. Publish

This is a fallback approach until PRX provides OAuth API credentials.
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
        self.default_description = config.get("default_description", "")
        self.series_id = config.get("series_id", "")
        self.auto_publish = config.get("auto_publish", False)
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

        # Navigate to login
        self.page.goto(PRX_LOGIN_URL, wait_until="networkidle")
        self.page.wait_for_load_state("networkidle")

        try:
            # Look for email/username field
            email_field = self.page.locator(
                'input[name="login"], input[name="email"], '
                'input[type="email"], input[name="user[login]"]'
            ).first
            email_field.fill(self.username)

            # Look for password field
            password_field = self.page.locator(
                'input[name="password"], input[type="password"], '
                'input[name="user[password]"]'
            ).first
            password_field.fill(self.password)

            # Submit
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
                "Screenshot saved to prx-login-debug.png for debugging."
            )

    def _close(self):
        """Clean up browser resources."""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _extract_date_from_filename(self, filename: str) -> str:
        """
        Extract date from filename like '4999_HCR-LFA 04.22.26.wav'
        Returns formatted date string like 'April 22, 2026'
        """
        try:
            # Find the date pattern MM.DD.YY
            import re
            match = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', filename)
            if match:
                month, day, year = match.groups()
                dt = datetime(2000 + int(year), int(month), int(day))
                return dt.strftime("%B %d, %Y")
        except Exception as e:
            logger.warning(f"Could not extract date from filename: {e}")

        return datetime.now().strftime("%B %d, %Y")

    def create_and_upload_story(
        self,
        audio_path: Path | str,
        title: str = "",
        description: str = "",
        tags: list = None,
        publish: bool = False,
    ) -> str:
        """
        Full workflow: create piece → upload audio → fill details → publish.
        Returns the piece URL.
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

            # Take a screenshot to see the form
            self.page.screenshot(path="prx-form-initial.png")
            logger.info("Screenshot of initial form saved: prx-form-initial.png")

            # --- Upload audio file ---
            logger.info(f"Uploading audio: {audio_path.name}")
            file_input = self.page.locator('input[type="file"]').first
            file_input.set_input_files(str(audio_path))

            logger.info("Waiting for upload to complete...")
            time.sleep(5)

            try:
                self.page.wait_for_selector(
                    '.upload-progress, .uploading, .processing',
                    state='hidden',
                    timeout=300000,
                )
            except PlaywrightTimeout:
                logger.warning("Upload progress indicator didn't clear — continuing")

            # --- Fill in title ---
            logger.info(f"Setting title: {piece_title}")
            try:
                title_field = self.page.locator(
                    'input[name*="title"], input#piece_title, '
                    'input[placeholder*="title" i]'
                ).first
                title_field.fill(piece_title)
            except Exception as e:
                logger.warning(f"Could not find title field: {e}")

            # --- Fill in description ---
            logger.info("Setting description...")
            try:
                desc_field = self.page.locator(
                    'textarea[name*="description"], textarea#piece_description, '
                    'textarea[placeholder*="description" i], '
                    'textarea[name*="short_description"]'
                ).first
                desc_field.fill(piece_description)
            except Exception as e:
                logger.warning(f"Could not find description field: {e}")

            # --- Fill in tags ---
            if all_tags:
                logger.info(f"Setting tags: {', '.join(all_tags)}")
                try:
                    tags_field = self.page.locator(
                        'input[name*="tag"], input#piece_tags, '
                        'input[placeholder*="tag" i]'
                    ).first
                    tags_field.fill(", ".join(all_tags))
                except Exception as e:
                    logger.warning(f"Could not find tags field: {e}")

            # --- Set producer name ---
            if self.producer_name:
                logger.info(f"Setting producer: {self.producer_name}")
                try:
                    producer_field = self.page.locator(
                        'input[name*="producer"], input[name*="credit"], '
                        'input[placeholder*="producer" i]'
                    ).first
                    producer_field.fill(self.producer_name)
                except Exception as e:
                    logger.warning(f"Could not find producer field: {e}")

            # --- Upload image ---
            if self.image_path and Path(self.image_path).exists():
                logger.info(f"Uploading image: {self.image_path}")
                try:
                    # Look for image upload input (usually second file input)
                    image_inputs = self.page.locator('input[type="file"]').all()
                    for inp in image_inputs:
                        accept = inp.get_attribute("accept") or ""
                        if "image" in accept or len(image_inputs) > 1:
                            inp.set_input_files(self.image_path)
                            logger.info("Image uploaded.")
                            break
                except Exception as e:
                    logger.warning(f"Could not upload image: {e}")

            # --- Set pricing: Free, 0 points ---
            logger.info("Setting pricing to free (0 points)...")
            try:
                # Look for price/points field
                price_field = self.page.locator(
                    'input[name*="point"], input[name*="price"], '
                    'input[name*="Point"], input#piece_point_level'
                ).first
                price_field.fill("0")
            except Exception as e:
                logger.warning(f"Could not find price field: {e}")

            try:
                # Look for "free" radio button or checkbox
                free_option = self.page.locator(
                    'input[value="free"], input[value="0"], '
                    'label:has-text("Free"), label:has-text("free")'
                ).first
                free_option.click()
            except Exception as e:
                logger.warning(f"Could not find free pricing option: {e}")

            # --- Set permissions: "Only with permission" ---
            logger.info("Setting permissions...")
            try:
                permission_option = self.page.locator(
                    'label:has-text("Only with permission"), '
                    'input[value*="permission"]'
                ).first
                permission_option.click()
            except Exception as e:
                logger.warning(f"Could not find permission option: {e}")

            # --- Station License Terms ---
            try:
                license_option = self.page.locator(
                    'label:has-text("Station License Terms"), '
                    'input[value*="station_license"]'
                ).first
                license_option.click()
            except Exception as e:
                logger.warning(f"Could not find license option: {e}")

            # --- Never edit or excerpt ---
            try:
                excerpt_option = self.page.locator(
                    'label:has-text("Never"), '
                    'input[value*="never"]'
                ).first
                excerpt_option.click()
            except Exception as e:
                logger.warning(f"Could not find excerpt option: {e}")

            # --- Add to series ---
            series_names = self.config.get("series_names", [])
            if series_names or self.series_id:
                logger.info("Adding piece to series...")
                try:
                    # Check the "Add this piece to a series" checkbox
                    series_checkbox = self.page.locator(
                        'input[name*="series"], label:has-text("series"), '
                        'label:has-text("Add this piece to a series")'
                    ).first
                    series_checkbox.click()
                    time.sleep(1)

                    if series_names:
                        # Select each series by visible text
                        for name in series_names:
                            logger.info(f"Selecting series: {name}")
                            try:
                                series_select = self.page.locator(
                                    'select[name*="series"]'
                                ).first
                                series_select.select_option(label=name)
                                time.sleep(0.5)
                            except Exception as e:
                                logger.warning(f"Could not select series '{name}': {e}")
                    elif self.series_id:
                        series_select = self.page.locator(
                            'select[name*="series"]'
                        ).first
                        series_select.select_option(value=self.series_id)
                except Exception as e:
                    logger.warning(f"Could not set series: {e}")

            # Screenshot before submit
            self.page.screenshot(path="prx-form-filled.png")
            logger.info("Screenshot of filled form: prx-form-filled.png")

            # --- Publish ---
            if publish or self.auto_publish:
                logger.info("Publishing piece...")
                try:
                    publish_btn = self.page.locator(
                        'input[value*="Publish"], button:has-text("Publish"), '
                        'input[name="commit"][value*="Publish"]'
                    ).first
                    publish_btn.click()
                except Exception:
                    logger.warning("No publish button found, trying save...")
                    save_btn = self.page.locator(
                        'input[type="submit"], button[type="submit"], '
                        'input[value*="Save"], button:has-text("Save")'
                    ).first
                    save_btn.click()
            else:
                logger.info("Saving piece as draft...")
                save_btn = self.page.locator(
                    'input[type="submit"], button[type="submit"], '
                    'input[value*="Save"], button:has-text("Save")'
                ).first
                save_btn.click()

            self.page.wait_for_load_state("networkidle")

            piece_url = self.page.url
            logger.info(f"Piece saved: {piece_url}")

            self.page.screenshot(path="prx-upload-complete.png")
            logger.info("Screenshot saved: prx-upload-complete.png")

            return piece_url

        except Exception as e:
            try:
                self.page.screenshot(path="prx-upload-error.png")
                logger.error("Error screenshot saved: prx-upload-error.png")
            except Exception:
                pass
            raise RuntimeError(f"PRX upload failed: {e}")

        finally:
            self._close()
