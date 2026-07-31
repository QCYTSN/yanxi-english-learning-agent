from __future__ import annotations

import os


# The public product intentionally starts empty. Tests opt into the small,
# project-original fixture corpus so existing end-to-end learning assertions
# remain deterministic.
os.environ.setdefault("IELTS_COACH_INCLUDE_DEMO_CONTENT", "1")
