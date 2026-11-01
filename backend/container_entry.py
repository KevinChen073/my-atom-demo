"""Choose the container ASGI entry from the explicitly configured environment."""

from .settings import Settings

if Settings().app_env == "azure_demo":
    from .azure_demo import app
else:
    from .api import app
