"""Print the FastAPI OpenAPI schema to stdout (no DB needed: lifespan is not started)."""

import json

from app.main import app

print(json.dumps(app.openapi(), indent=2))
