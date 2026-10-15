"""Render a BoardView to a standalone HTML page.

No templating engine: the view model has already made every decision,
so this file only loops and substitutes. Swapping in Jinja or a React
page later means replacing this one module.
"""

from __future__ import annotations

from html import escape

from .viewmodel import BoardView, CurrencyView

# Layout: a ranked summary strip over expanded per-currency rows — the
# order a trader scans in, summary before detail.
STYLE = """
:root{
  --bg:#0b0f14; --surface:#121820; --raised:#19212c; --line:#243041;
  --fg:#e6edf5; --muted:#8a99ad; --faint:#5d6b7e;
  --accent:#4cc3d9;
  --bull:#2fbf71; --bull-dim:#1d7a48; --bear:#e5484d; --bear-dim:#8f2b2e;
  --flat:#6b7a8d; --warn:#f2a03d;
  color-scheme:dark;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    --bg:#f4f6f9; --surface:#ffffff; --raised:#eef2f7; --line:#d6dee9;
    --fg:#14202e; --muted:#5a6a7d; --faint:#8696a8;
    --accent:#0f7c91;
    --bull:#157f4c; --bull-dim:#9fd8bb; --bear:#c0272c; --bear-dim:#f0b4b6;
    --flat:#7a8899; --warn:#9a6212;
    color-scheme:light;
  }
}
:root[data-theme="light"]{
  --bg:#f4f6f9; --surface:#ffffff; --raised:#eef2f7; --line:#d6dee9;
  --fg:#14202e; --muted:#5a6a7d; --faint:#8696a8;
  --accent:#0f7c91;
  --bull:#157f4c; --bull-dim:#9fd8bb; --bear:#c0272c; --bear-dim:#f0b4b6;
  --flat:#7a8899; --warn:#9a6212;
  color-scheme:light;
}

*{box-sizing:border-box}
body{
  background:var(--bg); color:var(--fg); margin:0;
  font-family:"Archivo","Helvetica Neue",Arial,sans-serif;
  font-size:15px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
}
.wrap{
  max-width:1100px; margin:0 auto;
  padding-left:max(16px, env(safe-area-inset-left, 0px));
  padding-right:max(16px, env(safe-area-inset-right, 0px));
  padding-block:28px 56px;
}
.mono{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
      font-variant-numeric:tabular-nums}

/* ---- header ---- */
header{display:flex; flex-wrap:wrap; gap:14px 24px; align-items:baseline;
       padding-bottom:18px; border-bottom:1px solid var(--line)}
h1{font-size:clamp(22px,3.4vw,30px); font-weight:700; letter-spacing:-.015em;
   margin:0; text-wrap:balance}
.sub{color:var(--muted); font-size:13px; margin:0}
.meta{margin-left:auto; display:flex; gap:18px; flex-wrap:wrap;
      font-size:12px; color:var(--faint)}
.meta b{color:var(--muted); font-weight:500}

/* ---- banner ---- */
.banner{margin:20px 0 0; padding:13px 16px; border-radius:6px;
        border:1px solid var(--warn); background:color-mix(in srgb,var(--warn) 12%,transparent);
        color:var(--fg); font-size:13.5px; display:flex; gap:11px; align-items:flex-start}
.banner .tag{color:var(--warn); font-weight:700; letter-spacing:.07em;
             font-size:11px; padding-top:2px; white-space:nowrap}

/* ---- ranked strip ---- */
.strip{display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr));
       gap:9px; margin:22px 0 30px}
.chip{background:var(--surface); border:1px solid var(--line); border-radius:7px;
      padding:12px 13px 11px; display:flex; flex-direction:column; gap:7px;
      border-left:3px solid var(--flat)}
.chip.strong-bull{border-left-color:var(--bull)}
.chip.bull{border-left-color:var(--bull-dim)}
.chip.bear{border-left-color:var(--bear-dim)}
.chip.strong-bear{border-left-color:var(--bear)}
.chip .code{font-weight:700; font-size:17px; letter-spacing:.02em}
.chip .score{font-size:25px; font-weight:600; line-height:1}
.chip.strong-bull .score,.chip.bull .score{color:var(--bull)}
.chip.strong-bear .score,.chip.bear .score{color:var(--bear)}
.chip.neutral .score{color:var(--flat)}
.chip .band{font-size:10px; letter-spacing:.09em; color:var(--muted)}

/* ---- rows ---- */
.row{background:var(--surface); border:1px solid var(--line); border-radius:8px;
     margin-bottom:11px; overflow:hidden}
.row > .head{display:flex; align-items:center; gap:14px; padding:14px 16px;
             flex-wrap:wrap}
.row .code{font-size:19px; font-weight:700; min-width:52px; letter-spacing:.02em}
.pill{font-size:10.5px; letter-spacing:.09em; font-weight:600; padding:4px 9px;
      border-radius:999px; border:1px solid var(--line); color:var(--muted);
      white-space:nowrap}
.pill.strong-bull,.pill.bull{color:var(--bull); border-color:var(--bull-dim)}
.pill.strong-bear,.pill.bear{color:var(--bear); border-color:var(--bear-dim)}
.flag{font-size:10.5px; letter-spacing:.06em; color:var(--warn);
      border:1px solid var(--warn); border-radius:999px; padding:3px 8px}
.total{margin-left:auto; font-size:27px; font-weight:600; line-height:1}
.total.up{color:var(--bull)} .total.down{color:var(--bear)}
.total.mid{color:var(--flat)}

.gauge{height:3px; background:var(--raised); position:relative}
.gauge i{position:absolute; top:0; bottom:0; width:2px; background:var(--accent)}
.gauge u{position:absolute; top:0; bottom:0; left:50%; width:1px;
         background:var(--line); text-decoration:none}

.components{display:grid; grid-template-columns:repeat(auto-fit,minmax(248px,1fr));
            gap:1px; background:var(--line)}
.cmp{background:var(--surface); padding:13px 16px 15px; min-width:0}
.cmp .top{display:flex; align-items:baseline; gap:9px; margin-bottom:5px}
.cmp .name{font-size:11px; letter-spacing:.08em; color:var(--muted); font-weight:600}
.cmp .val{font-size:15px; font-weight:600; margin-left:auto}
.cmp .val.up{color:var(--bull)} .cmp .val.down{color:var(--bear)}
.cmp .val.mid{color:var(--flat)}
.cmp .blurb{font-size:11.5px; color:var(--faint); margin:0 0 7px}
.cmp .reason{font-size:12.5px; color:var(--muted); margin:0}
.cmp .stale{display:inline-block; margin-top:7px; font-size:10px;
            letter-spacing:.06em; color:var(--warn)}
.note{padding:0 16px 14px; font-size:12.5px; color:var(--muted)}
.note b{color:var(--faint); font-weight:600; letter-spacing:.06em; font-size:10.5px}

/* ---- sources ---- */
.sources{margin-top:34px; padding-top:18px; border-top:1px solid var(--line)}
.sources h2{font-size:11px; letter-spacing:.1em; color:var(--muted);
            font-weight:600; margin:0 0 12px}
.src{display:flex; gap:12px; flex-wrap:wrap; align-items:baseline;
     font-size:12.5px; padding:7px 0; border-bottom:1px solid var(--line)}
.src .nm{font-weight:600; min-width:84px}
.src .st{font-size:10.5px; letter-spacing:.07em; padding:2px 7px;
         border-radius:999px; border:1px solid var(--line); color:var(--muted)}
.src .st.bad{color:var(--bear); border-color:var(--bear-dim)}
.src .dt{color:var(--faint); min-width:0; flex:1}
.foot{margin-top:22px; font-size:12px; color:var(--faint); max-width:68ch}
.foot p{margin:0 0 7px}
@media (max-width:460px){
  .total{margin-left:0; width:100%}
  .row .code{min-width:0}
}
"""


def _dir_class(value: int) -> str:
    return "up" if value > 0 else ("down" if value < 0 else "mid")


def _chip(c: CurrencyView) -> str:
    return (
        f'<div class="chip {c.band_class}">'
        f'<span class="code">{escape(c.code)}</span>'
        f'<span class="score mono">{escape(c.total_display)}</span>'
        f'<span class="band">{escape(c.band_label)}</span>'
        f"</div>"
    )


def _row(c: CurrencyView) -> str:
    flags = ""
    if c.derived:
        flags += '<span class="flag">DERIVED</span>'
    if c.degraded:
        flags += '<span class="flag">DEGRADED</span>'

    components = "".join(
        f'<div class="cmp">'
        f'<div class="top"><span class="name">{escape(cm.label)}</span>'
        f'<span class="val mono {_dir_class(cm.value)}">{escape(cm.display)}</span></div>'
        f'<p class="blurb">{escape(cm.blurb)}</p>'
        f'<p class="reason">{escape(cm.reason)}</p>'
        + (f'<span class="stale">{escape(cm.confidence.upper())}</span>'
           if cm.confidence else "")
        + "</div>"
        for cm in c.components
    )

    note = (f'<div class="note"><b>CONTEXT</b> &nbsp;{escape(c.note)}</div>'
            if c.note else "")

    return (
        f'<section class="row">'
        f'<div class="head">'
        f'<span class="code">{escape(c.code)}</span>'
        f'<span class="pill {c.band_class}">{escape(c.band_label)}</span>'
        f"{flags}"
        f'<span class="total mono {_dir_class(c.total)}">{escape(c.total_display)}</span>'
        f"</div>"
        f'<div class="gauge"><u></u><i style="left:{c.bar_pct:.1f}%"></i></div>'
        f'<div class="components">{components}</div>'
        f"{note}"
        f"</section>"
    )


def render(view: BoardView) -> str:
    banner = ""
    if view.banner:
        tag = "LIVE DATA UNAVAILABLE" if not view.live else "NOTICE"
        banner = (f'<div class="banner"><span class="tag">{tag}</span>'
                  f"<span>{escape(view.banner)}</span></div>")

    sources = "".join(
        f'<div class="src"><span class="nm">{escape(s.name)}</span>'
        f'<span class="st{"" if s.ok else " bad"}">{escape(s.status.upper())}</span>'
        f'<span class="dt">{escape(s.detail)}</span></div>'
        for s in view.sources
    )

    return f"""<title>FX Macro Bias Board</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  <header>
    <div>
      <h1>FX Macro Bias Board</h1>
      <p class="sub">Rates &middot; Positioning &middot; Calendar &mdash; scored &minus;9 to &plus;9</p>
    </div>
    <div class="meta">
      <span><b>As of</b> {escape(view.as_of)}</span>
      <span><b>Built</b> {escape(view.generated_at)}</span>
      <span><b>Method</b> v{escape(view.methodology_version)}</span>
    </div>
  </header>

  {banner}

  <div class="strip">{"".join(_chip(c) for c in view.currencies)}</div>

  {"".join(_row(c) for c in view.currencies)}

  <div class="sources">
    <h2>DATA PROVENANCE</h2>
    {sources}
    <div class="foot">
      <p>Each component scores &minus;3 to &plus;3 and the three are summed.
         A currency is marked STRONG at &plusmn;5 or beyond &mdash; a starting
         threshold, to be refitted once enough daily readings exist to show
         the real spread.</p>
      <p>USD carries a DERIVED flag because the CFTC publishes currency
         futures quoted against the dollar, so there is no USD contract to
         read. Its positioning is inferred from the other six.</p>
      <p>A component with no data scores zero and says so rather than
         reading as a neutral market. Context lines are judgement and never
         enter the total.</p>
    </div>
  </div>
</div>
"""
