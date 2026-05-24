"""RQ queue + scheduler for reminders, inbox polling, summaries.

Phase 1 sets up the connection and a worker entrypoint;
Phase 2+ register actual jobs.
"""

from __future__ import annotations
