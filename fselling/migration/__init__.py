"""Fail-closed Alembic coordinator for the single-file SQLite deployment.

Submodules are intentionally not imported here: schema inspection utilities
must remain usable without importing the web app or initializing Alembic.
"""
