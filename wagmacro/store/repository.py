"""Persistence for daily boards.

JSON on disk today. The interface is deliberately narrow — save, load,
history — so swapping in Postgres for a subscription service touches
this file and nothing else.

Boards are stored with their methodology version. When the bands are
recalibrated, old boards keep the version that produced them, so the
history stays honest rather than being silently restated.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ..core.types import (Band, Board, ComponentKind, ComponentScore,
                          Confidence, Currency, CurrencyReading, SourceStamp)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "history"


class BoardRepository:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or DEFAULT_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, as_of: date) -> Path:
        return self.directory / f"board-{as_of.isoformat()}.json"

    # -- write ------------------------------------------------------------

    def save(self, board: Board) -> Path:
        path = self._path(board.as_of)
        path.write_text(json.dumps(self._encode(board), indent=2),
                        encoding="utf-8")
        return path

    @staticmethod
    def _encode(board: Board) -> dict:
        return {
            "as_of": board.as_of.isoformat(),
            "generated_at": board.generated_at.isoformat(),
            "methodology_version": board.methodology_version,
            "readings": [
                {
                    "currency": r.currency.value,
                    "total": r.total,
                    "band": r.band.value,
                    "derived": r.derived,
                    "note": r.note,
                    "components": [
                        {
                            "kind": c.kind.value,
                            "value": c.value,
                            "reason": c.reason,
                            "confidence": c.confidence.value,
                            "inputs": dict(c.inputs),
                        }
                        for c in r.components
                    ],
                }
                for r in board.readings
            ],
            "sources": {
                name: {
                    "url": s.url,
                    "retrieved_at": s.retrieved_at.isoformat() if s.retrieved_at else None,
                    "data_dated": s.data_dated.isoformat() if s.data_dated else None,
                    "transport": s.transport,
                    "ok": s.ok,
                    "detail": s.detail,
                }
                for name, s in board.sources.items()
            },
        }

    # -- read -------------------------------------------------------------

    def load(self, as_of: date) -> Board | None:
        path = self._path(as_of)
        if not path.exists():
            return None
        return self._decode(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _decode(raw: dict) -> Board:
        readings = tuple(
            CurrencyReading(
                currency=Currency(r["currency"]),
                components=tuple(
                    ComponentScore(
                        kind=ComponentKind(c["kind"]),
                        value=c["value"],
                        reason=c["reason"],
                        confidence=Confidence(c["confidence"]),
                        inputs=c.get("inputs", {}),
                    )
                    for c in r["components"]
                ),
                total=r["total"],
                band=Band(r["band"]),
                derived=r.get("derived", False),
                note=r.get("note", ""),
            )
            for r in raw["readings"]
        )
        sources = {
            name: SourceStamp(
                name=name, url=s["url"],
                retrieved_at=datetime.fromisoformat(s["retrieved_at"]) if s["retrieved_at"] else None,
                data_dated=date.fromisoformat(s["data_dated"]) if s["data_dated"] else None,
                transport=s["transport"], ok=s["ok"], detail=s.get("detail", ""),
            )
            for name, s in raw.get("sources", {}).items()
        }
        return Board(
            as_of=date.fromisoformat(raw["as_of"]),
            generated_at=datetime.fromisoformat(raw["generated_at"]),
            methodology_version=raw["methodology_version"],
            readings=readings,
            sources=sources,
        )

    def history(self, currency: Currency, limit: int = 90) -> list[tuple[date, int]]:
        """(date, total) for one currency, oldest first.

        This is what eventually answers the only question that matters:
        does a green fundamental actually improve the win rate?
        """
        out: list[tuple[date, int]] = []
        for path in sorted(self.directory.glob("board-*.json"))[-limit:]:
            try:
                board = self._decode(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue        # one corrupt day must not break the series
            reading = board.reading(currency)
            if reading is not None:
                out.append((board.as_of, reading.total))
        return out
