from __future__ import annotations

import base64
import fnmatch
import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


@dataclass
class MockAnkiConnectState:
    decks: dict[str, int] = field(default_factory=lambda: {"Default": 1})
    model_fields: dict[str, list[str]] = field(
        default_factory=lambda: {
            "Basic": ["Front", "Back"],
            "Cloze": ["Text", "Back Extra"],
        }
    )
    model_templates: dict[str, dict[str, dict[str, str]]] = field(
        default_factory=lambda: {
            "Basic": {
                "Card 1": {
                    "Front": "{{Front}}",
                    "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
                }
            },
            "Cloze": {
                "Cloze": {
                    "Front": "{{cloze:Text}}",
                    "Back": "{{cloze:Text}}<br>\n{{Back Extra}}",
                }
            },
        }
    )
    notes: dict[int, dict[str, Any]] = field(default_factory=dict)
    cards: dict[int, dict[str, Any]] = field(default_factory=dict)
    media: dict[str, str] = field(default_factory=dict)
    reuse_media_request_case: bool = False
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
        model_name: str,
        fields: dict[str, str],
        note_id: int | None = None,
        tags: list[str] | None = None,
    ) -> int:
        if model_name not in self.model_fields:
            raise ValueError(f"unknown model: {model_name}")
        expected_fields = set(self.model_fields[model_name])
        # Real AnkiConnect silently ignores unknown fields. This stricter mock
        # guards md2anki's outbound contract before information can be lost.
        if set(fields) != expected_fields:
            raise ValueError(f"invalid fields for {model_name}: {sorted(fields)}")
        card_ordinals = [0]
        if model_name == "Cloze":
            card_ordinals = self._cloze_ordinals(fields["Text"])
            if not card_ordinals:
                raise ValueError("cannot create cloze note without a cloze deletion")

        self.add_deck(deck_name)
        if note_id is None:
            note_id = self.next_note_id
            self.next_note_id += 1
        else:
            self.next_note_id = max(self.next_note_id, note_id + 1)

        self.notes[note_id] = {
            "noteId": note_id,
            "deckName": deck_name,
            "modelName": model_name,
            "fields": dict(fields),
            "tags": list(tags or ["md2anki"]),
            "cards": [],
            "cardByOrdinal": {},
        }
        for ordinal in card_ordinals:
            self._add_card(note_id, deck_name, ordinal)
        return note_id

    @staticmethod
    def _cloze_ordinals(text: str) -> list[int]:
        return sorted({int(match) - 1 for match in re.findall(r"\{\{c([1-9]\d*)::", text)})

    def _add_card(self, note_id: int, deck_name: str, ordinal: int) -> int:
        card_id = self.next_card_id
        self.next_card_id += 1
        self.cards[card_id] = {
            "cardId": card_id,
            "noteId": note_id,
            "deckName": deck_name,
            "ord": ordinal,
        }
        note = self.notes[note_id]
        note["cardByOrdinal"][ordinal] = card_id
        note["cards"] = [note["cardByOrdinal"][key] for key in sorted(note["cardByOrdinal"])]
        return card_id

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        note = self.notes[note_id]
        expected_fields = set(self.model_fields[note["modelName"]])
        if not set(fields).issubset(expected_fields):
            raise ValueError(f"invalid fields for {note['modelName']}: {sorted(fields)}")

        note["fields"].update(fields)
        if note["modelName"] == "Cloze" and "Text" in fields:
            for ordinal in self._cloze_ordinals(note["fields"]["Text"]):
                if ordinal not in note["cardByOrdinal"]:
                    self._add_card(note_id, note["deckName"], ordinal)

    def delete_note(self, note_id: int) -> None:
        note = self.notes.pop(note_id, None)
        if note:
            for card_id in note["cards"]:
                self.cards.pop(card_id, None)


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
            return dict(state.decks)

        if action == "modelFieldNames":
            model_name = params["modelName"]
            if model_name not in state.model_fields:
                raise ValueError(f"model was not found: {model_name}")
            return list(state.model_fields[model_name])

        if action == "modelTemplates":
            model_name = params["modelName"]
            if model_name not in state.model_templates:
                raise ValueError(f"model was not found: {model_name}")
            return state.model_templates[model_name]

        if action == "createDeck":
            deck = params["deck"]
            return state.add_deck(deck)

        if action == "storeMediaFile":
            # Optionally reproduce Anki 26.09's Windows reuse bug: the returned
            # case can differ from the actual, lowercased directory entry.
            requested = params["filename"]
            filename = requested.lower()
            if params.get("data") is not None:
                data = params["data"]
            elif params.get("path") is not None:
                data = base64.b64encode(Path(params["path"]).read_bytes()).decode("ascii")
            else:
                data = ""
            reused = filename in state.media and state.media[filename] == data
            state.media[filename] = data
            if reused and state.reuse_media_request_case:
                return requested
            return filename

        if action == "getMediaFilesNames":
            return sorted(name for name in state.media if fnmatch.fnmatchcase(name, params.get("pattern", "*")))

        if action == "retrieveMediaFile":
            return state.media.get(params["filename"], False)

        if action == "addNote":
            note = params["note"]
            options = note.get("options") or {}
            if not options.get("allowDuplicate", True):
                deck_name = note.get("deckName")
                first_field_name = "Text" if note.get("modelName") == "Cloze" else "Front"
                first_field = note.get("fields", {}).get(first_field_name)
                for existing in state.notes.values():
                    if (
                        existing["modelName"] == note.get("modelName")
                        and existing["deckName"] == deck_name
                        and existing["fields"].get(first_field_name) == first_field
                    ):
                        raise ValueError("cannot create note because it is a duplicate")

            note_id = state.next_note_id
            state.next_note_id += 1
            state.add_note(
                deck_name=note.get("deckName"),
                model_name=note.get("modelName"),
                fields=note.get("fields", {}),
                note_id=note_id,
                tags=list(note.get("tags") or []),
            )
            return note_id

        if action == "updateNoteFields":
            note = params["note"]
            note_id = int(note["id"])
            state.update_note_fields(note_id, note.get("fields") or {})
            return None

        if action == "deleteNotes":
            for note_id in params.get("notes", []):
                state.delete_note(int(note_id))
            return None

        if action == "notesInfo":
            result = []
            for note_id in params.get("notes", []):
                note = state.notes.get(int(note_id))
                if note:
                    result.append(
                        {
                            "noteId": int(note_id),
                            "modelName": note["modelName"],
                            "tags": note["tags"],
                            "fields": {
                                name: {"value": value, "order": order}
                                for order, (name, value) in enumerate(note["fields"].items())
                            },
                            "cards": note["cards"],
                        }
                    )
                else:
                    result.append({})
            return result

        if action == "changeDeck":
            cards = {int(card_id) for card_id in params.get("cards", [])}
            deck = params["deck"]
            state.add_deck(deck)
            for card_id in cards:
                if card_id in state.cards:
                    state.cards[card_id]["deckName"] = deck
            for note in state.notes.values():
                if note["cards"] and all(state.cards[card_id]["deckName"] == deck for card_id in note["cards"]):
                    note["deckName"] = deck
            return None

        raise ValueError(f"unsupported action: {action}")
