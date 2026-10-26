"""Generates the tiny offline site served inside the browser sandbox.

A local site (instead of the real web) keeps tasks deterministic and makes the
later prompt-injection experiments possible: you control every pixel of content.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

OUT = Path(os.environ.get("OUT", "/srv/site"))

NAMES = [
    "Alice Nguyen", "Bao Tran", "Chi Le", "Dung Pham", "Elena Vo",
    "Farah Ali", "Giang Ho", "Hana Sato", "Ivan Petrov", "Julia Kim",
    "Khoa Do", "Lena Muller", "Minh Bui", "Nam Hoang", "Oanh Vu",
    "Pablo Diaz", "Quyen Ngo", "Rita Sharma", "Son Dang", "Trang Ly",
    "Uyen Cao", "Victor Chen", "Wei Zhang", "Xuan Mai", "Yen Dao",
    "Zoe Park", "An Duong", "Binh Ta", "Cam Phan", "Duc Lai",
]
ROLES = ["Backend Engineer", "Frontend Engineer", "Data Engineer", "Product Designer", "Product Manager"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z]+", "-", text.lower()).strip("-")


PEOPLE = [
    {
        "id": i,
        "name": name,
        "role": ROLES[(i - 1) % len(ROLES)],
        "salary": 60000 + i * 2500,
        "email": f"{slug(name).split('-')[0]}.{slug(name).split('-')[-1]}@example.com",
    }
    for i, name in enumerate(NAMES, start=1)
]

CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #eef1f5; color: #1b1f24;
         font-family: "DejaVu Sans", -apple-system, sans-serif; }
  nav { background: #1f2937; padding: 14px 26px; }
  nav a { color: #e5e7eb; margin-right: 20px; text-decoration: none; font-size: 16px; }
  nav a:hover { color: #93c5fd; }
  main { max-width: 960px; margin: 30px auto 60px; background: #fff; padding: 28px 32px;
         border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  h1 { margin-top: 0; font-size: 28px; }
  h2 { font-size: 20px; }
  p { line-height: 1.55; font-size: 16px; }
  label { display: block; margin: 14px 0 6px; font-weight: 600; font-size: 15px; }
  input, textarea { width: 100%; padding: 10px; font-size: 16px;
                    border: 1px solid #cbd5e1; border-radius: 6px; }
  button { margin-top: 20px; padding: 12px 22px; font-size: 16px; background: #2563eb;
           color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #e5e7eb; }
  tr:nth-child(even) { background: #fafafa; }
  .hint { color: #475569; font-size: 14px; }
"""

NAV = (
    '<nav>'
    '<a href="/index.html">Home</a>'
    '<a href="/form.html">Contact</a>'
    '<a href="/list.html">Team</a>'
    "</nav>"
)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title><style>{CSS}</style></head><body>"
        f"{NAV}<main>{body}</main></body></html>"
    )


def write(path: str, html: str) -> None:
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html)


def main() -> None:
    write(
        "index.html",
        page(
            "Cua Lab Intranet",
            "<h1>Cua Lab Intranet</h1>"
            "<p>This is a small offline site used by the cua-lab sandbox. "
            "Every task in <code>tasks/browser/</code> runs against these pages.</p>"
            "<p>Start with the <a href=\"/form.html\">contact form</a> or browse the "
            "<a href=\"/list.html\">team directory</a>.</p>",
        ),
    )

    write(
        "form.html",
        page(
            "Contact",
            "<h1>Contact us</h1>"
            "<p class=\"hint\">Fields marked with a label are required by the demo task.</p>"
            '<form action="/success.html" method="get">'
            "<label for=\"name\">Name</label>"
            '<input id="name" name="name" type="text" autocomplete="off">'
            "<label for=\"email\">Email</label>"
            '<input id="email" name="email" type="email" autocomplete="off">'
            "<label for=\"message\">Message</label>"
            '<textarea id="message" name="message" rows="4"></textarea>'
            '<button type="submit">Send message</button>'
            "</form>",
        ),
    )

    write(
        "success.html",
        page(
            "Thanks",
            "<h1>Thanks!</h1>"
            '<p id="msg">Your message was received.</p>'
            "<p><a href=\"/index.html\">Back to home</a></p>"
            "<script>"
            "const p = new URLSearchParams(location.search);"
            "const n = p.get('name');"
            "if (n) document.getElementById('msg').textContent ="
            "  'Thanks, ' + n + '. Your message was received.';"
            "</script>",
        ),
    )

    rows = "".join(
        f"<tr><td>{p['name']}</td><td>{p['role']}</td><td>{p['salary']}</td>"
        f"<td><a href=\"/team/p{p['id']}.html\">Profile</a></td></tr>"
        for p in PEOPLE
    )
    write(
        "list.html",
        page(
            "Team",
            "<h1>Team directory</h1>"
            "<label for=\"q\">Search by name</label>"
            '<input id="q" type="text" placeholder="Type a name to filter" autocomplete="off">'
            "<table id=\"team\"><thead><tr><th>Name</th><th>Role</th>"
            "<th>Salary</th><th>Profile</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "<script>"
            "document.getElementById('q').addEventListener('input', (e) => {"
            "  const v = e.target.value.toLowerCase();"
            "  for (const tr of document.querySelectorAll('#team tbody tr')) {"
            "    tr.style.display = tr.textContent.toLowerCase().includes(v) ? '' : 'none';"
            "  }"
            "});"
            "</script>",
        ),
    )

    for p in PEOPLE:
        write(
            f"team/p{p['id']}.html",
            page(
                p["name"],
                f"<h1>{p['name']}</h1>"
                f"<p><strong>Role:</strong> {p['role']}</p>"
                f"<p><strong>Salary:</strong> {p['salary']}</p>"
                f"<p><strong>Email:</strong> {p['email']}</p>"
                "<p><a href=\"/list.html\">Back to team</a></p>",
            ),
        )

    print(f"site generated at {OUT} ({len(PEOPLE)} people)")


if __name__ == "__main__":
    main()
