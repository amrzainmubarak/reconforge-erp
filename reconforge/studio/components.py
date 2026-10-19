"""Studio rendering helpers."""

from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import quote

import pandas as pd

from reconforge.review.state import ALLOWED_STATUSES


def _layout(title: str, body: str, *, auth_nav: str = "", locale: str = "en") -> str:
    is_rtl = locale.strip().lower().startswith("ar")
    direction = "rtl" if is_rtl else "ltr"
    lang = escape(locale.strip()) or "en"

    if is_rtl:
        nav_html = """
    <nav aria-label="التنقل الرئيسي">
      <a href="/">نظرة عامة</a>
      <a href="/health">سلامة البيانات</a>
      <a href="/validation">التحقق</a>
      <a href="/reconciliation">المطابقة</a>
      <a href="/rule-results">نتائج القواعد</a>
      <a href="/exceptions">الاستثناءات</a>
      <a href="/close">الإقفال</a>
      <a href="/variance">الفروقات</a>
      <a href="/control-matrix">مصفوفة الرقابة</a>
      <a href="/risk-matrix">مصفوفة المخاطر</a>
      <a href="/wip">أعمار قيد التشغيل</a>
      <a href="/control-packs">حزم الرقابة</a>
      <a href="/evidence">الأدلة</a>
      <a href="/db/accounts">حسابات DB</a>
      <a href="/db/close">إقفال DB</a>
      <a href="/db/evidence">أدلة DB</a>
      <a href="/db/exceptions">استثناءات DB</a>
      <a href="/db/metrics">مقاييس DB</a>
      <a href="/downloads">التنزيلات</a>
      <a href="/docs">التوثيق</a>
      AUTH_NAV
    </nav>
    """
    else:
        nav_html = """
    <nav aria-label="Main Navigation">
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
    """
    nav = nav_html.replace("AUTH_NAV", auth_nav)
    return f"""<!doctype html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, -apple-system, Arial, sans-serif; background: #f5f7fa; color: #182230; line-height: 1.5; }}
    header {{ background: #16324f; color: #ffffff; padding-block: 22px; padding-inline: 32px; text-align: start; }}
    header h1 {{ margin: 0; font-size: 24px; font-weight: 700; color: #ffffff; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; padding-block: 12px; padding-inline: 32px; background: #e7edf4; border-block-end: 1px solid #d5dde8; text-align: start; }}
    nav a {{ color: #16324f; text-decoration: none; padding-block: 6px; padding-inline: 10px; border-radius: 6px; font-weight: 500; font-size: 14px; }}
    nav a:hover {{ background: #d5dde8; }}
    nav a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible {{ outline: 2px solid #16324f; outline-offset: 2px; }}
    .nav-spacer {{ flex: 1 1 auto; }}
    .nav-button {{ border: 0; border-radius: 6px; padding-block: 6px; padding-inline: 12px; background: #16324f; color: #ffffff; cursor: pointer; font-size: 14px; font-weight: 500; }}
    main {{ max-width: 1180px; margin-inline: auto; padding-block: 24px; padding-inline: 24px; text-align: start; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card {{ background: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; padding-block: 14px; padding-inline: 14px; text-align: start; }}
    .card span {{ display: block; color: #344054; font-size: 13px; font-weight: 500; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 23px; color: #182230; }}
    .badge {{ border-radius: 999px; padding-block: 3px; padding-inline: 8px; font-size: 12px; font-weight: 600; background: #e8eef5; color: #16324f; }}
    .high, .critical {{ background: #fee4e2; color: #7a1710; }}
    .medium {{ background: #fff4cc; color: #593800; }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; align-items: end; margin-block-end: 14px; text-align: start; }}
    .review-action {{ background: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; padding-block: 14px; padding-inline: 14px; margin-block-end: 16px; text-align: start; }}
    .review-action summary {{ cursor: pointer; font-weight: 700; color: #16324f; }}
    .review-form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: end; margin-top: 12px; text-align: start; }}
    .filters label, .review-form label {{ display: grid; gap: 4px; font-size: 12px; color: #344054; font-weight: 500; text-align: start; }}
    .filters input, .filters select, .review-form input, .review-form select {{ min-height: 34px; border: 1px solid #ccd6e0; border-radius: 6px; padding-block: 6px; padding-inline: 8px; background: #ffffff; color: #182230; text-align: start; }}
    .filters button, .review-form button {{ min-height: 34px; border: 0; border-radius: 6px; padding-block: 6px; padding-inline: 12px; background: #16324f; color: #ffffff; cursor: pointer; font-weight: 500; }}
    .message {{ padding-block: 10px; padding-inline: 12px; border-radius: 6px; margin-block-end: 14px; border: 1px solid; text-align: start; }}
    .success {{ background: #ecfdf3; color: #02542d; border-color: #abefc6; }}
    .error {{ background: #fef3f2; color: #7a1710; border-color: #fecdca; }}
    .login-panel {{ max-width: 390px; background: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; padding-block: 18px; padding-inline: 18px; margin-inline: auto; text-align: start; }}
    .login-form {{ display: grid; gap: 12px; text-align: start; }}
    .login-form label {{ display: grid; gap: 5px; font-size: 13px; color: #344054; font-weight: 500; text-align: start; }}
    .login-form input {{ min-height: 36px; border: 1px solid #ccd6e0; border-radius: 6px; padding-block: 6px; padding-inline: 8px; background: #ffffff; color: #182230; }}
    .login-form button {{ min-height: 36px; border: 0; border-radius: 6px; padding-block: 6px; padding-inline: 12px; background: #16324f; color: #ffffff; cursor: pointer; font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #dce3ea; text-align: start; }}
    th, td {{ padding-block: 9px; padding-inline: 10px; border-block-end: 1px solid #edf1f5; text-align: start; font-size: 13px; color: #182230; }}
    th {{ background: #e8eef5; color: #16324f; font-weight: 700; text-align: start; }}
    h2 {{ margin-top: 0; color: #16324f; text-align: start; }}
  </style>
</head>
<body>
  <header style="display: flex; justify-content: space-between; align-items: center;">
    <h1>ReconForge Studio</h1>
    <div class="lang-switcher" style="font-size: 14px; font-weight: 500;">
      <a href="?lang=en" style="color: #ffffff; text-decoration: none; margin-inline-end: 8px;">English</a> |
      <a href="?lang=ar" style="color: #ffffff; text-decoration: none; margin-inline-start: 8px;">العربية</a>
    </div>
  </header>
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
    text_val = str(value)
    if text_val.strip().lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    return escape(text_val)


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
    <label for="rev-exception-id">Exception ID<input id="rev-exception-id" name="exception_id" required maxlength="80" placeholder="EXC-0001"></label>
    <label for="rev-status">Status<select id="rev-status" name="status" required>{statuses}</select></label>
    <label for="rev-reviewer">Reviewer<input id="rev-reviewer" name="reviewer" maxlength="120"></label>
    <label for="rev-note">Note<input id="rev-note" name="note" maxlength="500"></label>
    <label for="rev-decision-reason">Decision reason<input id="rev-decision-reason" name="decision_reason" maxlength="500"></label>
    <label for="rev-accepted-risk">Accepted-risk reason<input id="rev-accepted-risk" name="accepted_risk_reason" maxlength="500"></label>
    <label for="rev-escalation-owner">Escalation owner<input id="rev-escalation-owner" name="escalation_owner" maxlength="120"></label>
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
    <label for="login-username">Username<input id="login-username" name="username" autocomplete="username" required maxlength="120"></label>
    <label for="login-password">Password<input id="login-password" name="password" type="password" autocomplete="current-password" required maxlength="512"></label>
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
