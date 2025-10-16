# Local-First SEO Auditor Backend

This package contains the FastAPI backend service for the Local-First SEO Auditor.

## Development Setup

1. Create a virtual environment targeting Python 3.11 or newer.
2. Install dependencies: `pip install -e .[dev]`.
3. Run the API locally: `uvicorn app.main:app --reload`.
4. Execute tests: `pytest`.

The backend enforces HMAC request signing as described in the PRD/FRD. Configure the signing secret via environment variables before starting the service.
