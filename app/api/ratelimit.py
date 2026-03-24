"""
app/api/ratelimit.py
Shared rate limiter instance — imported by main.py and route modules.
Kept in its own file to break the circular import between main.py and routes.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
