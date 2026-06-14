"""Management simulation module.

The public surface is intentionally small: the router exposes only observable
artifacts and manager actions. Persona definitions and latent state stay inside
the module.
"""

from .router import router

__all__ = ["router"]
