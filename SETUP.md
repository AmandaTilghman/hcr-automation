# HCR Automation — Linux Setup Guide

## Prerequisites

- Ubuntu/Debian Linux box (22.04+ recommended)
- Python 3.10+
- Internet access (for PRX, email, GitHub)
- No display server needed (runs headless)

## 1. System packages

```bash
sudo apt update && sudo apt install -y \
  python3 python3-pip python3-venv \
  ffmpeg \
  git \
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 \
  libpango-1.0-0 libcairo2 libasound2
```

(The lib* packages are Chromium dependencies for headless Playwright.)

## 2. Clone the repo

```bash
cd /opt
sudo mkdir -p hcr-automation
sudo chown $USER:$USER hcr-automation
git clone https://github.com/AmandaTilghman/hcr-automation.git hcr-automation
cd hcr-automation
```

## 3. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 4. Configure

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

Fill in:
- **email**: Gmail address + App Password (not regular password)
- **sftp**: Host, port, credentials for the audio server
- **prx**: PRX Exchange username/password, series names, producer, image path
- **headless**: should already be `true`

## 5. Test manually

```bash
source venv/bin/activate
python main.py
```

Watch the log:
```bash
tail -f radio-automation.log
```

## 6. Schedule with cron

```bash
crontab -e
```

Add:
```cron
# HCR automation — every 15 min, 11 AM - 8 PM Eastern (UTC-4 = 15:00-00:00 UTC)
*/15 15-23 * * * cd /opt/hcr-automation && /opt/hcr-automation/venv/bin/python main.py >> /opt/hcr-automation/cron.log 2>&1
```

## 7. Verify

```bash
# Check cron is registered
crontab -l

# Check logs after next scheduled run
tail -f /opt/hcr-automation/cron.log
tail -f /opt/hcr-automation/radio-automation.log
```

## Gmail App Password

1. Enable 2FA on the Gmail account: https://myaccount.google.com/security
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Select "Mail" → copy the 16-character password
4. Paste into `config.yaml` under `email.password`

## Troubleshooting

- **Playwright can't launch**: Missing system libs. Re-run the apt install line above.
- **SFTP fails**: Check if LAN IP is reachable; falls back to WAN automatically.
- **PRX login fails**: Check credentials. Run with `headless: false` on a machine with a display to debug visually.
- **No emails found**: Check `from_filter` and `subject_filter` in config match the actual notification emails.
