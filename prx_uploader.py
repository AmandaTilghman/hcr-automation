"""
PRX Uploader
=============
Handles OAuth2 authentication and story creation/upload via the PRX CMS API.

PRX API docs:
  - API root: https://cms.prx.org/api/v1
  - HAL browser: https://cms.prx.org/browser/index.html
  - OAuth: https://id.prx.org

NOTE: PRX's upload flow uses signed S3 uploads. The workflow is:
  1. Authenticate via OAuth2 (id.prx.org)
  2. Create a story via the CMS API
  3. Get a signed upload URL from the upload service
  4. Upload audio directly to S3 using the signed URL
  5. Attach the uploaded audio to the story
  6. Optionally publish the story

This module handles all of that. You'll need to register an OAuth app
with PRX to get client_id/client_secret.
"""

import logging
from pathlib import Path

import requests

logger = logging.getLogger("radio-automation.prx")

# PRX API endpoints
PRX_ID_URL = "https://id.prx.org"
PRX_CMS_URL = "https://cms.prx.org/api/v1"
PRX_UPLOAD_URL = "https://upload.prx.org"


class PRXClient:
    """Client for the PRX CMS API."""

    def __init__(self, config: dict):
        self.client_id = config["client_id"]
        self.client_secret = config["client_secret"]
        self.username = config["username"]
        self.password = config["password"]
        self.account_id = config.get("account_id", "")
        self.series_id = config.get("series_id", "")
        self.default_tags = config.get("default_tags", [])
        self.default_description = config.get("default_description", "")
        self.access_token = None
        self.session = requests.Session()

    def authenticate(self):
        """
        Obtain OAuth2 access token via Resource Owner Password grant.

        If PRX supports a different grant type for your use case,
        adjust accordingly. Check id.prx.org for available grant types.
        """
        logger.info("Authenticating with PRX...")

        token_url = f"{PRX_ID_URL}/oauth/token"
        payload = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }

        resp = requests.post(token_url, data=payload)
        resp.raise_for_status()

        data = resp.json()
        self.access_token = data["access_token"]
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/hal+json",
        })

        logger.info("Authenticated successfully.")

    def _get(self, url: str, **kwargs) -> dict:
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, **kwargs) -> dict:
        resp = self.session.post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _put(self, url: str, **kwargs) -> dict:
        resp = self.session.put(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_account(self) -> dict:
        """Get the authenticated user's account info."""
        auth_info = self._get(f"{PRX_CMS_URL}/authorization")
        # Follow the account link
        account_link = auth_info.get("_links", {}).get("prx:default-account", {})
        if account_link:
            return self._get(account_link["href"])
        return auth_info

    def create_story(self, title: str, description: str = "",
                     tags: list = None, series_id: str = None) -> dict:
        """
        Create a new story (piece) on PRX.

        Returns the created story resource (HAL JSON).
        """
        all_tags = list(set((tags or []) + self.default_tags))
        desc = description or self.default_description

        story_data = {
            "title": title,
            "shortDescription": desc[:200] if desc else title,
            "description": desc or title,
            "tags": all_tags,
            "length": 0,  # Will be updated after audio upload
        }

        # Determine where to create the story
        target_series = series_id or self.series_id
        if target_series:
            url = f"{PRX_CMS_URL}/series/{target_series}/stories"
        elif self.account_id:
            url = f"{PRX_CMS_URL}/accounts/{self.account_id}/stories"
        else:
            url = f"{PRX_CMS_URL}/stories"

        logger.info(f"Creating story: '{title}'")
        story = self._post(url, json=story_data)
        story_id = story.get("id", "unknown")
        logger.info(f"Created story ID: {story_id}")
        return story

    def upload_audio(self, story: dict, audio_path: Path) -> dict:
        """
        Upload audio file for a story.

        PRX uses signed S3 uploads. The flow:
        1. POST to the story's audio endpoint to get an upload ticket
        2. Upload the file to S3 using the signed URL
        3. Return the audio resource
        """
        audio_path = Path(audio_path)
        file_size = audio_path.stat().st_size
        filename = audio_path.name

        # Get the story's audio upload link
        links = story.get("_links", {})
        audio_link = links.get("prx:audio", links.get("prx:audio-versions", {}))

        if isinstance(audio_link, list):
            audio_link = audio_link[0]

        audio_url = audio_link.get("href", "")
        if not audio_url:
            # Fallback: construct from story ID
            story_id = story.get("id")
            audio_url = f"{PRX_CMS_URL}/stories/{story_id}/audio_versions"

        # Create audio version
        logger.info(f"Creating audio version for: {filename} ({file_size} bytes)")
        audio_data = {
            "label": filename,
            "files": [{
                "filename": filename,
                "size": file_size,
                "contentType": "audio/mpeg",  # MP2 uses audio/mpeg MIME type
            }]
        }

        audio_version = self._post(audio_url, json=audio_data)

        # Get the upload URL from the response
        # PRX returns a signed S3 upload URL in the audio file resource
        files_info = audio_version.get("_embedded", {}).get("prx:audio-files", [])

        if not files_info:
            # Try direct upload endpoint
            logger.warning("No signed upload URL found — trying direct upload")
            return self._direct_upload(story, audio_path)

        for file_info in files_info:
            upload_links = file_info.get("_links", {})
            upload_url = upload_links.get("prx:upload", {}).get("href", "")

            if upload_url:
                logger.info(f"Uploading to signed URL...")
                with open(audio_path, "rb") as f:
                    upload_resp = requests.put(
                        upload_url,
                        data=f,
                        headers={"Content-Type": "audio/mpeg"},
                    )
                    upload_resp.raise_for_status()
                logger.info("Audio uploaded successfully.")

        return audio_version

    def _direct_upload(self, story: dict, audio_path: Path) -> dict:
        """
        Fallback: try uploading audio directly if signed URL flow
        doesn't work. Some PRX setups may differ.
        """
        story_id = story.get("id")
        url = f"{PRX_CMS_URL}/stories/{story_id}/audio_files"

        with open(audio_path, "rb") as f:
            resp = self.session.post(
                url,
                files={"file": (audio_path.name, f, "audio/mpeg")},
            )
            resp.raise_for_status()

        return resp.json()

    def publish_story(self, story: dict) -> str:
        """
        Publish a story. Returns the public URL.
        """
        links = story.get("_links", {})
        publish_link = links.get("prx:publish", {})

        if publish_link:
            url = publish_link.get("href", "")
            if url:
                self._put(url)
                logger.info("Story published!")
        else:
            # Try updating the story status
            story_id = story.get("id")
            self._put(
                f"{PRX_CMS_URL}/stories/{story_id}",
                json={"published": True}
            )
            logger.info("Story published via status update.")

        # Return a link to the story
        self_link = links.get("self", {}).get("href", "")
        public_link = links.get("alternate", {}).get("href", "")
        return public_link or self_link or f"Story ID: {story.get('id')}"

    def create_and_upload_story(
        self,
        audio_path: Path | str,
        title: str,
        description: str = "",
        tags: list = None,
        publish: bool = False,
    ) -> str:
        """
        Full workflow: create story → upload audio → optionally publish.
        Returns the story URL.
        """
        audio_path = Path(audio_path)

        # Create the story
        story = self.create_story(
            title=title,
            description=description,
            tags=tags,
        )

        # Upload audio
        self.upload_audio(story, audio_path)

        # Publish if requested
        if publish:
            return self.publish_story(story)

        # Return draft URL
        self_link = story.get("_links", {}).get("self", {}).get("href", "")
        return self_link or f"Draft story ID: {story.get('id')}"
