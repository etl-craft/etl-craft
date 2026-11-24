"""etl-craft: a metadata-driven ETL orchestration engine.

``__version__`` is the installed distribution version string, or ``0.0.0+unknown``
without distribution metadata; reading it raises no core.errors exception.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("etl-craft")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

# Records go nowhere until the application configures logging (see etl_craft.core.log).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["__version__"]
