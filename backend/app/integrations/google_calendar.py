"""Google Calendar integration (Phase 2).

Read events into local DB; create events only after approval.
Uses google-auth + google-api-python-client. OAuth refresh token
stored in keyring under name 'google_calendar_refresh_token'.
"""

from __future__ import annotations
