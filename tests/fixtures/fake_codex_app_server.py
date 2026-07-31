from __future__ import annotations

import json
import sys


def send(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for raw_line in sys.stdin:
    message = json.loads(raw_line)
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        continue
    if method == "initialize":
        send({"id": request_id, "result": {"codexHome": "fake"}})
    elif method == "account/read":
        send(
            {
                "id": request_id,
                "result": {
                    "account": {"type": "chatgpt", "email": "test@example.com"},
                    "requiresOpenaiAuth": True,
                },
            }
        )
    elif method == "model/list":
        send(
            {
                "id": request_id,
                "result": {
                    "data": [
                        {
                            "id": "test-codex",
                            "displayName": "Test Codex",
                            "supportedReasoningEfforts": ["low", "medium"],
                        }
                    ]
                },
            }
        )
    elif method == "thread/start":
        send(
            {
                "id": request_id,
                "result": {"thread": {"id": "thr_test", "model": "test-codex"}},
            }
        )
    elif method == "turn/start":
        send(
            {
                "id": request_id,
                "result": {
                    "turn": {
                        "id": "turn_test",
                        "status": "inProgress",
                        "items": [],
                    }
                },
            }
        )
        send(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thr_test",
                    "turnId": "turn_test",
                    "item": {"type": "agentMessage", "text": '{"answer":"ok"}'},
                },
            }
        )
        send(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thr_test",
                    "turnId": "turn_test",
                    "turn": {"id": "turn_test", "status": "completed"},
                },
            }
        )
    elif method == "account/login/start":
        send(
            {
                "id": request_id,
                "result": {
                    "type": message.get("params", {}).get("type"),
                    "loginId": "login_test",
                    "authUrl": "https://example.test/login",
                },
            }
        )
    elif method in {"account/logout", "turn/interrupt"}:
        send({"id": request_id, "result": {}})
    else:
        send(
            {
                "id": request_id,
                "error": {"code": -32601, "message": f"Unknown method {method}"},
            }
        )
