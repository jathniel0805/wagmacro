"""Turn a Board into something a template can render without thinking.

Kept separate from the HTML so the same view model can feed a Jinja
template, a React page or a JSON API later. The template should contain
no logic beyond loops and substitution — every decision about wording,
colour class and ordering is made here, where it can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.types import (Band, Board, ComponentKind, Confidence,
                          CurrencyReading)

BAND_LABEL = {
    Band.STRONG_BULL: "STRONG BULL",
    Band.BULL: "BULL",
    Band.NEUTRAL: "NEUTRAL",
    Band.BEAR: "BEAR",
    Band.STRONG_BEAR: "STRONG BEAR",
}

COMPONENT_LABEL = {
    ComponentKind.RATES: "Rates",
    ComponentKind.POSITIONING: "Positioning",
    ComponentKind.CALENDAR: "Calendar",
}

COMPONENT_BLURB = {
    ComponentKind.RATES: "2y yield differential and its repricing",
    ComponentKind.POSITIONING: "CFTC leveraged-fund net position",
    ComponentKind.CALENDAR: "scheduled high/medium impact releases",
}

CONFIDENCE_LABEL = {
    Confidence.OK: "",
    Confidence.STALE: "stale",
    Confidence.PARTIAL: "partial",
    Confidence.UNAVAILABLE: "no data",
}


@dataclass(frozen=True, slots=True)
class ComponentView:
    label: str
    blurb: str
    value: int
    display: str
    reason: str
    confidence: str
    degraded: bool


@dataclass(frozen=True, slots=True)
class CurrencyView:
    code: str
    total: int
    total_display: str
    band_class: str
    band_label: str
    derived: bool
    note: str
    components: tuple[ComponentView, ...]
    degraded: bool
    bar_pct: float          # 0..100, where the total sits on the -9..+9 scale


@dataclass(frozen=True, slots=True)
class SourceView:
    name: str
    url: str
    status: str
    detail: str
    ok: bool


@dataclass(frozen=True, slots=True)
class BoardView:
    as_of: str
    generated_at: str
    methodology_version: str
    currencies: tuple[CurrencyView, ...]
    sources: tuple[SourceView, ...]
    live: bool
    banner: str


def _component_view(reading: CurrencyReading, kind: ComponentKind) -> ComponentView:
    score = reading.component(kind)
    if score is None:
        return ComponentView(
            label=COMPONENT_LABEL[kind], blurb=COMPONENT_BLURB[kind],
            value=0, display="—", reason="Component not run.",
            confidence="no data", degraded=True,
        )
    return ComponentView(
        label=COMPONENT_LABEL[kind],
        blurb=COMPONENT_BLURB[kind],
        value=score.value,
        display=f"{score.value:+d}" if score.confidence is not Confidence.UNAVAILABLE else "—",
        reason=score.reason,
        confidence=CONFIDENCE_LABEL[score.confidence],
        degraded=score.confidence is not Confidence.OK,
    )


def build(board: Board, *, live: bool, banner: str = "") -> BoardView:
    currencies = tuple(
        CurrencyView(
            code=r.currency.value,
            total=r.total,
            total_display=f"{r.total:+d}",
            band_class=r.band.value.replace("_", "-"),
            band_label=BAND_LABEL[r.band],
            derived=r.derived,
            note=r.note,
            components=tuple(
                _component_view(r, k) for k in
                (ComponentKind.RATES, ComponentKind.POSITIONING,
                 ComponentKind.CALENDAR)
            ),
            degraded=r.weakest_link is not Confidence.OK,
            bar_pct=max(0.0, min(100.0, (r.total + 9) / 18 * 100)),
        )
        for r in board.ranked()
    )

    sources = tuple(
        SourceView(
            name=name,
            url=stamp.url,
            status=stamp.transport,
            detail=stamp.detail or ("live" if stamp.ok else "unavailable"),
            ok=stamp.ok,
        )
        for name, stamp in sorted(board.sources.items())
    )

    return BoardView(
        as_of=board.as_of.strftime("%d %B %Y"),
        generated_at=board.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        methodology_version=board.methodology_version,
        currencies=currencies,
        sources=sources,
        live=live,
        banner=banner,
    )
