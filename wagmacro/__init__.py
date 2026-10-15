"""wagmacro — a fundamentals bias model for the seven FX majors.

Layers, strictly one-directional:

    ingest  ->  model  ->  store / render

`ingest` knows about HTTP and file formats and nothing about scoring.
`model` is pure functions over typed data — no I/O, no clock, no
globals. `render` knows about colour and layout and nothing about where
numbers came from.

That separation is the point: the same `model` runs behind a daily
script today and behind a web request later, unchanged.
"""

__version__ = "1.0.0"
