"""Remote access layer: profile-aware browse/search over storage sources.

- filebrowser_client: SSRF-safe FileBrowser REST client with JWT caching
- browser: unified browse/search dispatch by profile protocol (dual-path aware)
"""

from app.services.remote_access.browser import browse_profile, search_profile
from app.services.remote_access.filebrowser_client import (
    FileBrowserClient,
    FileBrowserError,
    clear_filebrowser_token_cache,
)

__all__ = [
    "browse_profile",
    "search_profile",
    "FileBrowserClient",
    "FileBrowserError",
    "clear_filebrowser_token_cache",
]
