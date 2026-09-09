"""Suite-wide environment required before importing the ASGI application."""

import os

os.environ.setdefault(
    "SESSION_SECRET", "cds-test-suite-session-secret-32-chars"
)
