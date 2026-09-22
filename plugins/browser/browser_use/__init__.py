"""Browser Use cloud browser plugin — retired for this deployment.

The provider module remains importable for historical tests and compat pointers.
Active discovery no longer registers it.
"""

from __future__ import annotations


def register(ctx) -> None:
    """No-op: Browser Use cloud hosting is not admitted for new sessions."""
    return
