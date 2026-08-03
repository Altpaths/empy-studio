# Uninstaller

Ticket 7.5 generates uninstallers from the exact `install-state.json`
contract written by Tickets 7.3 and 7.4.

The uninstallers remove only the recorded version directory, generated command
wrapper, current-version pointer/file, install state, and empty
installer-owned directories. They validate that the version path remains
inside the configured install root and do not use elevation, Registry edits,
PATH edits, or shell-profile changes.
