"""
PRX Uploader (Browser Automation)
==================================
Uses Playwright to automate the PRX Exchange upload workflow:
  1. Log in to exchange.prx.org
  2. Navigate to My PRX → Create New Piece
  3. Upload audio file
  4. Fill in title, description, tags
  5. Publish

This is a fallback approach until PRX provides OAuth API credentials.
Requires: playwright (pip install playwright && playwright install chromium)
"""

import logging
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("radio-automation.prx")

PRX_LOGIN_URL = "https://exchange.prx.org/login"
PRX_NEW_PIECE_URL = "https://exchange.prx.org/pieces/new"
PRX_MY_URL = "https://exchange.prx.org/my"


class PRXClient:
    """Browser-based PRX uploader using Playwright."""

    def __init__(self, config: dict):
        self.username = config["username"]
        self.password = config["password"]
        self.default_tags = config.get("default_tags", [])
        self.default_description = config.get("default_description", "")
        self.series_id = config.get("series_id", "")
        self.auto_publish = config.get("auto_publish", False)
        self.headless = config.get("headless", True)
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

        # Fill login form
        # PRX uses id.prx.org for auth — may redirect there
        self.page.wait_for_load_state("networkidle")

        # Try to find login fields (may be on id.prx.org after redirect)
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
            # Take a screenshot for debugging
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

    def create_and_upload_story(
        self,
        audio_path: Path | str,
        title: str,
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
        desc = description or self.default_description or title

        try:
            # Navigate to create new piece
            logger.info("Navigating to Create New Piece...")
            self.page.goto(PRX_NEW_PIECE_URL, wait_until="networkidle")

            # --- Upload audio file ---
            logger.info(f"Uploading audio: {audio_path.name}")

            # Look for file input (may be hidden, used by the browse button)
            file_input = self.page.locator('input[type="file"]').first
            file_input.set_input_files(str(audio_path))

            # Wait for upload to process (this can take a while for large files)
            logger.info("Waiting for upload to complete...")
            time.sleep(5)  # Initial wait for upload to start

            # Wait for any upload progress indicators to finish
            try:
                # Wait for upload/processing indicators to disappear
                self.page.wait_for_selector(
                    '.upload-progress, .uploading, .processing',
                    state='hidden',
                    timeout=300000,  # 5 min timeout for large files
                )
            except PlaywrightTimeout:
                logger.warning("Upload progress indicator didn't clear — continuing anyway")

            # --- Fill in title ---
            logger.info(f"Setting title: {title}")
            try:
                title_field = self.page.locator(
                    'input[name*="title"], input#piece_title, '
                    'input[placeholder*="title" i]'
                ).first
                title_field.fill(title)
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
                desc_field.fill(desc[:500])
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

            # --- Add to series if configured ---
            if self.series_id:
                logger.info(f"Adding to series: {self.series_id}")
                try:
                    series_checkbox = self.page.locator(
                        'input[name*="series"], label:has-text("series")'
                    ).first
                    series_checkbox.click()
                    time.sleep(1)

                    series_select = self.page.locator(
                        'select[name*="series"]'
                    ).first
                    series_select.select_option(value=self.series_id)
                except Exception as e:
                    logger.warning(f"Could not set series: {e}")

            # --- Save / Publish ---
            if publish or self.auto_publish:
                logger.info("Publishing piece...")
                try:
                    publish_btn = self.page.locator(
                        'input[value*="Publish"], button:has-text("Publish"), '
                        'input[name="commit"][value*="Publish"]'
                    ).first
                    publish_btn.click()
                except Exception:
                    # Fall back to save
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

            # Get the piece URL
            piece_url = self.page.url
            logger.info(f"Piece saved: {piece_url}")

            # Take a screenshot for confirmation
            self.page.screenshot(path="prx-upload-complete.png")
            logger.info("Screenshot saved: prx-upload-complete.png")

            return piece_url

        except Exception as e:
            # Screenshot for debugging
            try:
                self.page.screenshot(path="prx-upload-error.png")
                logger.error("Error screenshot saved: prx-upload-error.png")
            except Exception:
                pass
            raise RuntimeError(f"PRX upload failed: {e}")

        finally:
            self._close()
