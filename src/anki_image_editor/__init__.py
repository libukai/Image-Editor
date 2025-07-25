from anki import version

# Anki 25.6+ version requirement check
try:
    major, minor, patch = version.split(".")[:3]
    version_tuple = (int(major), int(minor), int(patch))

    # Require Anki 25.6+ for modern API support
    if version_tuple < (25, 6, 0):
        raise Exception(f"This addon requires Anki 25.6+. Current version: {version}")

except ValueError:
    # Allow development/beta versions to proceed
    pass

# Import the main module to initialize the addon
from . import editor  # noqa: F401
