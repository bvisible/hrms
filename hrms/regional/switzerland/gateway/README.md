# Swissdec Gateway

Lightweight Flask service that bridges HRMS instances to the SwissDecTX CLI on a Windows VM.

## Architecture

```
HRMS Instance(s) ── HTTP POST ──> Swissdec Gateway ── SSH/SCP ──> SwissDecTX VM (Win11)
```

## Prerequisites

- Python 3.10+ on the gateway host (e.g., Synology NAS)
- SSH key-based access from gateway host to the SwissDecTX VM
- SwissDecTX 5.09 installed and configured on the VM

## Setup

```bash
# Install dependencies
pip3 install -r requirements.txt

# Copy and edit configuration
cp .env.example .env
# Edit .env with your VM connection details and API keys

# Run (development)
source .env && python app.py

# Run (production)
source .env && gunicorn -w 2 -b 0.0.0.0:8745 app:app
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

Each HRMS instance gets its own API key. The gateway serializes TX command execution to prevent conflicts on the VM. Transmissions are isolated in per-UUID directories.
