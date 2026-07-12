"""Platform detection and platform-aware recommendation routing."""

from .detect import capabilities, current_platform, has_flatpak, is_raspberry_pi
from .recommend import apply_recommended_emulator, default_backend, get_recommended_emulator

__all__ = [
    "current_platform",
    "has_flatpak",
    "is_raspberry_pi",
    "capabilities",
    "get_recommended_emulator",
    "apply_recommended_emulator",
    "default_backend",
]
