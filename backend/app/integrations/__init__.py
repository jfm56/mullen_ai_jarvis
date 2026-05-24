"""External integrations.

All third-party API access goes through this package. Agents must
not import third-party SDKs directly — this keeps allow-listing,
rate limiting, and audit hooks in one place.
"""
