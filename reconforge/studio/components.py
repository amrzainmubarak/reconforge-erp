"""Studio rendering helpers."""

from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import quote

import pandas as pd

from reconforge.review.state import ALLOWED_STATUSES


def _layout(title: str, body: str, *, auth_nav: str = "") -> str:
    nav = """
    <nav>
      <a href="/">Overview</a>
      <a href="/health">Dataset Health</a>
      <a href="/validation">Validation</a>
      <a href="/reconciliation">Reconciliation</a>
      <a href="/rule-results">Rule Results</a>
      <a href="/exceptions">Exceptions</a>
      <a href="/close">Close</a>
      <a href="/variance">Variance</a>
      <a href="/control-matrix">Control Matrix</a>
      <a href="/risk-matrix">Risk Matrix</a>
      <a href="/wip">WIP Aging</a>
      <a href="/control-packs">Control Packs</a>
      <a href="/evidence">Evidence</a>
      <a href="/db/accounts">DB Accounts</a>
      <a href="/db/close">DB Close</a>
      <a href="/db/evidence">DB Evidence</a>
      <a href="/db/exceptions">DB Exceptions</a>
      <a href="/db/metrics">DB Metrics</a>
      <a href="/downloads">Downloads</a>
      <a href="/docs">Docs</a>
      AUTH_NAV
    </nav>
    """.replace("AUTH_NAV", auth_nav)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f5f7fa; color: #182230; }}
    header {{ background: #16324f; color: #fff; padding: 22px 32px; }}
    header h1 {{ margin: 0; font-size: 24px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 32px; background: #e7edf4; border-bottom: 1px solid #d5dde8; }}
    nav a {{ color: #16324f; text-decoration: none; padding: 6px 8px; border-radius: 6px; }}
    nav a:hover {{ background: #d5dde8; }}
    .nav-spacer {{ flex: 1 1 auto; }}
    .nav-button {{ border: 0; border-radius: 6px; padding: 6px 8px; background: #16324f; color: #fff; cursor: pointer; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 23px; }}
    .badge {{ border-radius: 999px; padding: 3px 8px; font-size: 12px; background: #e8eef5; }}
    .high, .critical {{ background: #fee4e2; color: #912018; }}
    .medium {{ background: #fff4cc; color: #7a4d00; }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; align-items: end; margin: 0 0 14px; }}
    .review-action {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; margin: 0 0 16px; }}
    .review-action summary {{ cursor: pointer; font-weight: 700; color: #16324f; }}
    .review-form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: end; margin-top: 12px; }}
    .filters label, .review-form label {{ display: grid; gap: 4px; font-size: 12px; color: #475467; }}
    .filters input, .filters select, .review-form input, .review-form select {{ min-height: 34px; border: 1px solid #ccd6e0; border-radius: 6px; padding: 6px 8px; background: #fff; }}
    .filters button, .review-form button {{ min-height: 34px; border: 0; border-radius: 6px; padding: 6px 10px; background: #16324f; color: #fff; }}
    .message {{ padding: 10px 12px; border-radius: 6px; margin: 0 0 14px; border: 1px solid; }}
    .success {{ background: #ecfdf3; color: #067647; border-color: #abefc6; }}
    .error {{ background: #fef3f2; color: #b42318; border-color: #fecdca; }}
    .login-panel {{ max-width: 390px; background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 18px; }}
    .login-form {{ display: grid; gap: 12px; }}
    .login-form label {{ display: grid; gap: 5px; font-size: 13px; color: #475467; }}
    .login-form input {{ min-height: 36px; border: 1px solid #ccd6e0; border-radius: 6px; padding: 6px 8px; background: #fff; }}
    .login-form button {{ min-height: 36px; border: 0; border-radius: 6px; padding: 6px 10px; background: #16324f; color: #fff; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dce3ea; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; }}
    th {{ background: #e8eef5; }}
    h2 {{ margin-top: 0; }}
  </style>
</head>
<body>
  <header><h1>ReconForge Studio</h1></header>
  {nav}
  <main>{body}</main>
</body>
</html>"""


def _table(frame: pd.DataFrame, limit: int = 50) -> str:
    if frame.empty:
        return "<p>No records found.</p>"
    visible = frame.head(limit)
    header = "".join(f"<th>{escape(str(column))}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("<tr>" + "".join(f"<td>{_html_cell(row[column])}</td>" for column in visible.columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _html_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    return escape(text)


def _search_text(row: pd.Series) -> str:
    return " ".join(_html_cell(value) for value in row.to_list()).lower()


def _options(values: list[str]) -> str:
    items = ["<option value=''></option>"]
    for value in values:
        items.append(f"<option value='{escape(value)}'>{escape(value)}</option>")
    return "".join(items)


def _review_update_form(csrf_token: str) -> str:
    statuses = "".join(f"<option value='{escape(status)}'>{escape(status)}</option>" for status in ALLOWED_STATUSES)
    return f"""
<details class="review-action" open>
  <summary>Update Review Status</summary>
  <form class="review-form" method="post" action="/exceptions/update-review">
    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
    <label>Exception ID<input name="exception_id" required maxlength="80" placeholder="EXC-0001"></label>
    <label>Status<select name="status" required>{statuses}</select></label>
    <label>Reviewer<input name="reviewer" maxlength="120"></label>
    <label>Note<input name="note" maxlength="500"></label>
    <label>Decision reason<input name="decision_reason" maxlength="500"></label>
    <label>Accepted-risk reason<input name="accepted_risk_reason" maxlength="500"></label>
    <label>Escalation owner<input name="escalation_owner" maxlength="120"></label>
    <button type="submit">Save Review Update</button>
  </form>
</details>
"""


def _message_html(message: str, message_type: str) -> str:
    if not message:
        return ""
    css_class = "success" if message_type == "success" else "error"
    return f'<div class="message {css_class}">{escape(message)}</div>'


def _login_form(csrf_token: str, *, message: str = "") -> str:
    return f"""
<section class="login-panel">
  <h2>Studio Sign In</h2>
  {_message_html(message, "error")}
  <form class="login-form" method="post" action="/login">
    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
    <label>Username<input name="username" autocomplete="username" required maxlength="120"></label>
    <label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="512"></label>
    <button type="submit">Sign In</button>
  </form>
</section>
"""


def _logout_form(csrf_token: str) -> str:
    return f"""
<section class="login-panel">
  <h2>Sign Out</h2>
  <form class="login-form" method="post" action="/logout">
    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
    <button type="submit">Sign Out</button>
  </form>
</section>
"""


def _href(path_prefix: str, key: str) -> str:
    return f"{path_prefix}/{quote(key, safe='')}"


def _evidence_href(case_id: str, filename: str) -> str:
    return f"/download/evidence/{quote(case_id, safe='')}/{quote(filename, safe='')}"


def _form_value(payload: dict[str, list[str]], key: str, *, max_length: int = 500) -> str:
    values = payload.get(key, [""])
    return values[0].strip()[:max_length] if values else ""


def _allowed_choice(value: str, allowed: list[str]) -> str:
    normalized = str(value).strip().lower()
    for item in allowed:
        item_text = str(item).strip().lower()
        if normalized and item_text and normalized == item_text:
            return str(item)
    return ""


def _bounded_search(value: str) -> str:
    return value.strip()[:120]


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
