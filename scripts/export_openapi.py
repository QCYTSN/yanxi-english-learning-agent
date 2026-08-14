"""Export the local API contract snapshot for frontend type generation.

The FastAPI docs UI is disabled at runtime, but the OpenAPI document remains
the authoritative API contract. Dump it to frontend/openapi.snapshot.json and
generate TypeScript types with openapi-typescript:

    python scripts/export_openapi.py
    cd frontend && npx openapi-typescript openapi.snapshot.json -o src/api/schema.d.ts
"""

from __future__ import annotations

import json
from pathlib import Path

from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def main() -> None:
    app = create_app(
        home=None,
        auth=AuthState(launch_token="openapi-export-token-long-enough"),
        allowed_origin="http://127.0.0.1:0",
        test_mode=True,
    )
    schema = app.openapi()
    target = Path(__file__).resolve().parents[1] / "frontend" / "openapi.snapshot.json"
    target.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"OpenAPI snapshot written: {target} ({len(json.dumps(schema))} bytes)")


if __name__ == "__main__":
    main()
