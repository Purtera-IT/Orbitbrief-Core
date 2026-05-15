from __future__ import annotations

import html

from orbitbrief_core.pm_handoff.models import PMHandoff
from orbitbrief_core.pm_handoff.render_markdown import render_pm_handoff_markdown, render_portfolio_markdown

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f6f7f9; color: #17202a; }
main { max-width: 1180px; margin: 0 auto; padding: 32px; }
.card { background: white; border: 1px solid #e4e8ef; border-radius: 14px; padding: 22px; box-shadow: 0 2px 8px rgba(20,30,40,.05); }
h1, h2, h3 { line-height: 1.2; } pre { background: #0f172a; color: #e5e7eb; padding: 16px; border-radius: 10px; overflow-x: auto; }
code { background: #eef2f7; padding: 2px 5px; border-radius: 5px; } table { border-collapse: collapse; width: 100%; margin: 14px 0 22px; background: white; }
th, td { border: 1px solid #e4e8ef; padding: 8px 10px; text-align: left; vertical-align: top; } th { background: #f1f5f9; }
blockquote { border-left: 4px solid #64748b; padding-left: 14px; color: #475569; } ul { padding-left: 22px; }
"""


def render_pm_handoff_html(handoff: PMHandoff) -> str:
    return _wrap(markdown_to_simple_html(render_pm_handoff_markdown(handoff)), f"PM Handoff — {handoff.case_id}")


def render_portfolio_html(handoffs: list[PMHandoff]) -> str:
    return _wrap(markdown_to_simple_html(render_portfolio_markdown(handoffs)), "OrbitBrief PM Portfolio Dashboard")


def markdown_to_simple_html(md: str) -> str:
    out: list[str] = []
    in_pre = False
    in_ul = False
    in_table = False
    for line in md.splitlines():
        if line.startswith("```"):
            out.append("</code></pre>" if in_pre else "<pre><code>")
            in_pre = not in_pre
            continue
        if in_pre:
            out.append(html.escape(line))
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= {"-", ":"}:
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                tag = "th"
            else:
                tag = "td"
            out.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        elif in_ul:
            out.append("</ul>")
            in_ul = False
        if not line.strip():
            continue
        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    if in_ul:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    if in_pre:
        out.append("</code></pre>")
    return "\n".join(out)


def _wrap(body: str, title: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main><section class='card'>{body}</section></main></body></html>"


def _inline(text: str) -> str:
    return html.escape(text).replace("**", "")


def render_pm_executive_html(handoff: PMHandoff) -> str:
    from orbitbrief_core.pm_handoff.render_markdown import render_pm_executive_markdown
    return _wrap(markdown_to_simple_html(render_pm_executive_markdown(handoff)), f"PM Intake Readiness — {handoff.case_id}")


def render_solution_architect_html(handoff: PMHandoff) -> str:
    from orbitbrief_core.pm_handoff.render_markdown import render_solution_architect_markdown
    return _wrap(markdown_to_simple_html(render_solution_architect_markdown(handoff)), f"Solution Architect Review — {handoff.case_id}")
