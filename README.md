# Radio Automation Pipeline

Automated workflow for community radio: monitors email for notifications, downloads audio from FTP, transcodes WAV → MP2, and uploads/publishes to PRX.

## Requirements

- **Python 3.10+**
- **FFmpeg** (for audio transcoding)
- **PRX account** with OAuth2 app credentials

## Quick Start

### 1. Install dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate    # Mac/Linux
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 2. Install FFmpeg

```bash
# Mac
brew install ffmpeg

# Windows
winget install ffmpeg
# Or download from https://ffmpeg.org/download.html

# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
```

### 3. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your credentials and settings
```

### 4. Test manually

```bash
python main.py
```

### 5. Schedule it

**Mac/Linux (cron):**
```bash
crontab -e
# Add this line — runs every 15 min from 11am-7:45pm ET (UTC offset: subtract 4/5 hrs)
*/15 15-23 * * * cd /path/to/radio-automation && /path/to/venv/bin/python main.py
```

**Windows (Task Scheduler):**
1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, repeat every 15 minutes for 9 hours
3. Action: Start a program
   - Program: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\path\to\radio-automation`

## How It Works

```
Cron/Scheduler (every 15 min, afternoon ET)
  │
  ├─ Check IMAP inbox for notification email
  │   └─ No email? → exit quietly
  │
  ├─ Download latest WAV from FTP
  │
  ├─ Transcode WAV → MP2 (44.1kHz via FFmpeg)
  │
  ├─ Upload to PRX (OAuth2 → create story → S3 upload)
  │
  └─ Mark email as processed, log result
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | Orchestrator — runs the full pipeline |
| `config_loader.py` | Loads and validates config.yaml |
| `email_watcher.py` | IMAP inbox monitoring |
| `ftp_downloader.py` | FTP file download |
| `transcoder.py` | WAV → MP2 via FFmpeg |
| `prx_uploader.py` | PRX API client (OAuth2, upload, publish) |
| `state.py` | Tracks processed items (avoids duplicates) |
| `config.example.yaml` | Template config file |

## Error Handling

- If any step fails, the email is **not** marked as processed — next run will retry
- All errors are logged to `radio-automation.log`
- The script exits cleanly even on failure (safe for cron)

## PRX Setup

1. Register an OAuth2 application at [id.prx.org](https://id.prx.org)
2. Note your `client_id` and `client_secret`
3. Get your PRX account ID (visible in your account URL)
4. Add all credentials to `config.yaml`

## Gmail Notes

If using Gmail, you'll need an **App Password** (not your regular password):
1. Enable 2-Factor Authentication on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate a password for "Mail"
4. Use that in `config.yaml`
