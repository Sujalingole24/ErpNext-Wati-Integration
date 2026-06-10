# WATI WhatsApp Integration for ERPNext

**Version 2.0.1** — Frappe / ERPNext v16

Send WhatsApp template messages directly from ERPNext using the WATI API.

## Compatibility
- Frappe / ERPNext v14, v15, v16
- Python >= 3.10

## Installation

### Option A — from a local folder (recommended for zip installs)

```bash
# 1. Copy the app into your bench
cp -r wati_integration  ~/frappe-bench/apps/wati_integration

# 2. Install into your bench environment
cd ~/frappe-bench
./env/bin/pip install -e apps/wati_integration

# 3. Install on your site
bench --site your-site-name install-app wati_integration

# 4. Run migrations
bench migrate

# 5. Restart
bench restart
```

### Option B — from a Git repository

```bash
bench get-app https://github.com/YOUR_FORK/wati_integration --branch version-16
bench --site your-site-name install-app wati_integration
bench migrate
bench restart
```

## Configuration

1. Go to **Wati Integration** workspace → **Settings** → **Wati Setting**
2. Fill in your WATI **URL**, **WhatsApp Number** (digits only, with country code), and **API Token**
3. Create **Message Templates** matching your approved WATI templates
4. Create **Wati Message Rules** to trigger messages on document events

## License
MIT
