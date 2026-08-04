"""Desktop product boundary for Empy Studio."""

from .application import DesktopApplication, DesktopDependencies
from .shell import EmpyDesktopShell, launch_desktop

__all__ = [
    "DesktopApplication",
    "DesktopDependencies",
    "EmpyDesktopShell",
    "launch_desktop",
]
