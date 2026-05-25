"""Computer Control integrations.

Safety primitives used by `app.agents.computer_control`:
  * `safe_path`     — path-traversal and allow-listed-root enforcement
  * `file_hash`     — sha256 helpers + verify-before-execute
  * `subprocess_safe` — no shell=True, no string interpolation, structured args
  * `file_ops`      — read-only search / list / read inside allowed roots
  * `app_launcher`  — launch from AllowedApp row only
  * `script_runner` — run from AllowedScript row, hash-verified at exec time
"""
