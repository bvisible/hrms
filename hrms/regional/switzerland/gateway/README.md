<!-- //// Neoffice — added file (no upstream equivalent): how to deploy the Swissdec Gateway on the -->
<!-- //// SwissDecTX Windows VM. -->
# Swissdec Gateway

Lightweight Flask service running directly on the SwissDecTX Windows VM.
Executes SwissDecTX CLI commands locally and exposes a REST API for HRMS instances.

## Architecture

```
HRMS Instance(s) ── HTTP POST ──> Swissdec Gateway (VM Windows:8745) ──> SwissDecTX (local)
```

## Prerequisites

- Windows 10/11 with SwissDecTX 5.09 installed and configured
- Python 3.10+ (`winget install Python.Python.3.12`)

## Setup

```powershell
# Install dependencies
pip install -r requirements.txt

# Create directories
mkdir C:\SwissDec\tx
mkdir C:\SwissDec\transmissions

# Copy and edit configuration
copy .env.example .env
# Edit .env with your API keys

# Open firewall port
New-NetFirewallRule -DisplayName "Swissdec Gateway" -Direction Inbound -Port 8745 -Protocol TCP -Action Allow

# Run (development)
python app.py

# Run (production)
waitress-serve --host=0.0.0.0 --port=8745 app:app
```

## Running as a Windows Service (optional)

Use NSSM (Non-Sucking Service Manager) to auto-start the gateway:

```powershell
# Download nssm from https://nssm.cc/download
nssm install SwissdecGateway "C:\Python312\python.exe" "-m waitress --host=0.0.0.0 --port=8745 app:app"
nssm set SwissdecGateway AppDirectory "C:\SwissDec\gateway"
nssm set SwissdecGateway AppEnvironmentExtra "SWISSDEC_API_KEYS=your-key"
nssm start SwissdecGateway
```

## API Reference

All endpoints except `/api/v1/health` require an `X-API-Key` header.

### GET /api/v1/health
Health check. Returns gateway status.

### POST /api/v1/ping
Test SwissDecTX connectivity (PING command).

### POST /api/v1/transmit
Transmit a salary declaration XML.

**Form data:**
- `xml_file` (file, required): ELM 5.0 XML file
- `instance_id` (string, optional): HRMS instance identifier
- `declaration_name` (string, optional): Swissdec Declaration name

**Response:**
```json
{
  "tx_id": "a1b2c3d4e5f6",
  "exit_code": 0,
  "output": "...",
  "result_xml": "...",
  "answer_xml": "...",
  "has_job": false
}
```

### GET /api/v1/status/\<tx_id\>
Check async job status (for pending transmissions).

### GET /api/v1/result/\<tx_id\>
Retrieve stored result files for a transmission.

## Multi-Instance Support

Each HRMS instance gets its own API key. The gateway serializes TX command execution to prevent conflicts. Transmissions are isolated in per-UUID directories.
