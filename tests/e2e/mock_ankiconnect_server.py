from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class MockAnkiConnectState:
    decks: dict[str, int] = field(default_factory=lambda: {"Default": 1})
    notes: dict[int, dict[str, Any]] = field(default_factory=dict)
    media: dict[str, str] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    next_deck_id: int = 2
    next_note_id: int = 1001
    next_card_id: int = 5001

    def action_count(self, action: str) -> int:
        return sum(1 for request in self.requests if request.get("action") == action)

    def requests_for(self, action: str) -> list[dict[str, Any]]:
        return [request for request in self.requests if request.get("action") == action]

    def last_request_for(self, action: str) -> dict[str, Any] | None:
        matches = self.requests_for(action)
        return matches[-1] if matches else None

    def clear_requests(self) -> None:
        self.requests.clear()

    def add_deck(self, deck_name: str) -> int:
        if deck_name not in self.decks:
            self.decks[deck_name] = self.next_deck_id
            self.next_deck_id += 1
        return self.decks[deck_name]

    def add_note(
        self,
        deck_name: str,
        front: str,
        back: str,
        note_id: int | None = None,
        tags: list[str] | None = None,
    ) -> int:
        self.add_deck(deck_name)
        if note_id is None:
            note_id = self.next_note_id
            self.next_note_id += 1
        else:
            self.next_note_id = max(self.next_note_id, note_id + 1)

        card_id = self.next_card_id
        self.next_card_id += 1
        self.notes[note_id] = {
            "noteId": note_id,
            "deckName": deck_name,
            "modelName": "Basic",
            "fields": {"Front": front, "Back": back},
            "tags": list(tags or ["md2anki"]),
            "cards": [card_id],
        }
        return note_id


class MockAnkiConnectServer:
    def __init__(self):
        self.state = MockAnkiConnectState()
        self._server = _MockServer(("127.0.0.1", 0), _Handler, self.state)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "MockAnkiConnectServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _MockServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, state: MockAnkiConnectState):
        super().__init__(server_address, handler_class)
        self.state = state


class _Handler(BaseHTTPRequestHandler):
    server: _MockServer

    def log_message(self, format: str, *args) -> None:
        return

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            action = payload.get("action")
            params = payload.get("params") or {}
            self.server.state.requests.append({"action": action, "params": params})
            result = self._handle_action(action, params)
            self._send_json({"result": result, "error": None})
        except Exception as exc:
            self._send_json({"result": None, "error": str(exc)})

    def _send_json(self, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_action(self, action: str, params: dict[str, Any]) -> Any:
        state = self.server.state

        if action == "deckNamesAndIds":
            return {name: str(deck_id) for name, deck_id in state.decks.items()}

        if action == "createDeck":
            deck = params["deck"]
            return state.add_deck(deck)

        if action == "storeMediaFile":
            filename = params["filename"]
            state.media[filename] = params.get("data") or params.get("path") or ""
            return None

        if action == "retrieveMediaFile":
            return state.media.get(params["filename"], False)

        if action == "addNote":
            note = params["note"]
            options = note.get("options") or {}
            if not options.get("allowDuplicate", True):
                deck_name = note.get("deckName")
                front = note.get("fields", {}).get("Front")
                for existing in state.notes.values():
                    if existing["deckName"] == deck_name and existing["fields"].get("Front") == front:
                        raise ValueError("cannot create note because it is a duplicate")

            note_id = state.next_note_id
            state.next_note_id += 1
            state.add_note(
                deck_name=note.get("deckName"),
                front=note.get("fields", {}).get("Front", ""),
                back=note.get("fields", {}).get("Back", ""),
                note_id=note_id,
                tags=list(note.get("tags") or []),
            )
            state.notes[note_id]["modelName"] = note.get("modelName")
            return note_id

        if action == "updateNoteFields":
            note = params["note"]
            note_id = int(note["id"])
            state.notes[note_id]["fields"].update(note.get("fields") or {})
            return None

        if action == "deleteNotes":
            for note_id in params.get("notes", []):
                state.notes.pop(int(note_id), None)
            return None

        if action == "notesInfo":
            result = []
            for note_id in params.get("notes", []):
                note = state.notes.get(int(note_id))
                if note:
                    result.append({"noteId": int(note_id), "cards": note["cards"]})
            return result

        if action == "changeDeck":
            cards = {int(card_id) for card_id in params.get("cards", [])}
            deck = params["deck"]
            state.add_deck(deck)
            for note in state.notes.values():
                if any(card_id in cards for card_id in note["cards"]):
                    note["deckName"] = deck
            return None

        raise ValueError(f"unsupported action: {action}")
