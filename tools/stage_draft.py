#!/usr/bin/env python3
"""Stage a reviewed Lovable static export behind the shared decision bar."""

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple


CONTACT_EMAIL = "webmaster@occhino.it"
BASE_URL = "https://web.occhino.it"
INDEX_START = "<!-- draft-index:start -->"
INDEX_END = "<!-- draft-index:end -->"
LEAD_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{6,80}$")
RESOURCE_ATTRIBUTES = {
    "a": ("href",),
    "audio": ("src",),
    "embed": ("src",),
    "form": ("action",),
    "iframe": ("src",),
    "img": ("src", "srcset"),
    "input": ("src",),
    "link": ("href",),
    "object": ("data",),
    "script": ("src",),
    "source": ("src", "srcset"),
    "track": ("src",),
    "video": ("poster", "src"),
}
MAX_EXPORT_BYTES = 20 * 1024 * 1024


class StageError(RuntimeError):
    """A user-facing staging error."""


class ExportInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.resource_references: List[Tuple[str, str, str]] = []
        self.has_noindex = False
        self.has_viewport = False
        self.has_form = False
        self.has_meta_refresh = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        normalized_tag = tag.lower()
        if normalized_tag == "form":
            self.has_form = True
        if normalized_tag == "meta":
            name = values.get("name", "").lower()
            content = values.get("content", "").lower()
            if values.get("http-equiv", "").lower() == "refresh":
                self.has_meta_refresh = True
            if name == "robots" and "noindex" in content:
                self.has_noindex = True
            if name == "viewport":
                self.has_viewport = True
        for attribute in RESOURCE_ATTRIBUTES.get(normalized_tag, ()):
            value = values.get(attribute)
            if value:
                self.resource_references.append((normalized_tag, attribute, value.strip()))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_lead(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise StageError(f"Lead file does not exist: {path}")
    try:
        lead = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageError(f"Invalid lead JSON: {path}") from exc
    lead_id = str(lead.get("lead_id") or "")
    if not LEAD_ID_PATTERN.fullmatch(lead_id):
        raise StageError("Lead file contains an invalid lead_id")
    if lead.get("status") != "draft_generated":
        raise StageError("Lead must have status draft_generated before staging")
    draft = lead.get("draft") or {}
    if not isinstance(draft, dict) or draft.get("generator") != "lovable_mcp":
        raise StageError("Lead does not contain a recorded Lovable MCP draft")
    return lead


def is_forbidden_reference(tag: str, attribute: str, value: str) -> bool:
    candidates = [part.strip().split()[0] for part in value.split(",")] if attribute == "srcset" else [value]
    for candidate in candidates:
        lowered = candidate.lower()
        if lowered.startswith(("data:", "mailto:", "tel:", "sms:", "#")):
            continue
        parsed = urllib.parse.urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            # A normal anchor may point to a verified social/contact page. Loaded
            # resources and form submissions must remain inside the static export.
            if tag == "a" and attribute == "href":
                continue
            return True
        if parsed.scheme or candidate.startswith(("/", "//", "\\")):
            return True
    return False


def validate_export(site_dir: Path) -> None:
    if not site_dir.is_dir():
        raise StageError(f"Static export directory does not exist: {site_dir}")
    index = site_dir / "index.html"
    if not index.is_file():
        raise StageError("Static export must contain index.html")
    total_bytes = 0
    for path in site_dir.rglob("*"):
        if path.is_symlink():
            raise StageError(f"Symlinks are not allowed in a draft export: {path}")
        if any(part in {".git", "node_modules"} or part.startswith(".env") for part in path.parts):
            raise StageError(f"Development or secret file is not allowed: {path}")
        if path.is_file():
            total_bytes += path.stat().st_size
    if total_bytes > MAX_EXPORT_BYTES:
        raise StageError(f"Static export exceeds {MAX_EXPORT_BYTES // (1024 * 1024)} MB")

    source = index.read_text(encoding="utf-8")
    inspector = ExportInspector()
    inspector.feed(source)
    if not inspector.has_noindex:
        raise StageError("Export index.html must contain a noindex robots meta tag")
    if not inspector.has_viewport:
        raise StageError("Export index.html must contain a viewport meta tag")
    if inspector.has_form:
        raise StageError("Draft exports must not contain forms")
    if inspector.has_meta_refresh:
        raise StageError("Draft exports must not contain meta refresh redirects")
    forbidden = [
        (tag, attribute, value)
        for tag, attribute, value in inspector.resource_references
        if is_forbidden_reference(tag, attribute, value)
    ]
    if forbidden:
        tag, attribute, value = forbidden[0]
        raise StageError(f"Export contains a non-portable {tag} {attribute}: {value}")
    if re.search(r"@import\s+(?:url\()?\s*['\"]?(?:https?:)?//", source, re.IGNORECASE):
        raise StageError("Export CSS must not load an external stylesheet")
    if re.search(r"url\(\s*['\"]?(?:https?:)?//", source, re.IGNORECASE):
        raise StageError("Export CSS must not load external assets")
    if re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(|navigator\.sendBeacon\s*\(", source):
        raise StageError("Draft exports must not make network requests")


def decision_mailto(decision: str, lead_id: str, business_name: str, public_url: str) -> str:
    subject = f"{decision} — bozza sito {business_name}"
    body = "\n".join([
        f"Decisione: {decision}",
        f"Attività: {business_name}",
        f"Riferimento: {lead_id}",
        f"Bozza: {public_url}",
        "",
        "Scrivi qui eventuali note:",
    ])
    query = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{CONTACT_EMAIL}?{query}"


def render_wrapper(lead_id: str, business_name: str) -> str:
    public_url = f"{BASE_URL}/{lead_id}/"
    accept_url = decision_mailto("ACCEPT", lead_id, business_name, public_url)
    decline_url = decision_mailto("DECLINE", lead_id, business_name, public_url)
    title = html.escape(f"Bozza sito — {business_name}")
    business = html.escape(business_name)
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta name="referrer" content="no-referrer">
  <title>{title}</title>
  <style>
    :root {{ --bar-height: 72px; --ink: #151515; --paper: #f7f4ee; --line: #d8d2c8; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; height: 100%; overflow: hidden; background: var(--paper); color: var(--ink); }}
    body {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .decision-bar {{ position: fixed; inset: 0 0 auto 0; z-index: 1000; min-height: var(--bar-height); padding: 12px 18px; display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 14px; border-bottom: 1px solid var(--line); background: rgba(247,244,238,.97); box-shadow: 0 8px 28px rgba(25,22,18,.12); backdrop-filter: blur(12px); }}
    .identity {{ min-width: 0; }}
    .eyebrow {{ display: block; margin-bottom: 3px; color: #6d675f; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    .business {{ display: block; overflow: hidden; font-size: 16px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }}
    .actions {{ display: flex; gap: 8px; }}
    .button {{ min-height: 42px; padding: 11px 16px; border: 1px solid var(--ink); border-radius: 999px; color: var(--ink); font-size: 13px; font-weight: 850; letter-spacing: .04em; text-decoration: none; }}
    .button.accept {{ background: var(--ink); color: #fff; }}
    .contact {{ color: var(--ink); font-size: 13px; font-weight: 650; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .preview {{ position: fixed; inset: var(--bar-height) 0 0 0; }}
    iframe {{ display: block; width: 100%; height: 100%; border: 0; background: #fff; }}
    @media (max-width: 720px) {{
      :root {{ --bar-height: 132px; }}
      .decision-bar {{ grid-template-columns: 1fr auto; grid-template-rows: auto auto; gap: 9px 12px; padding: 10px 12px; }}
      .actions {{ grid-column: 2; grid-row: 1 / span 2; flex-direction: column; }}
      .button {{ min-width: 102px; min-height: 40px; padding: 10px 13px; text-align: center; }}
      .contact {{ align-self: start; font-size: 12px; }}
    }}
  </style>
</head>
<body>
  <header class="decision-bar" aria-label="Decisione sulla bozza">
    <div class="identity">
      <span class="eyebrow">Bozza sito</span>
      <span class="business">{business}</span>
    </div>
    <div class="actions" aria-label="Azioni">
      <a class="button accept" href="{html.escape(accept_url, quote=True)}">ACCEPT</a>
      <a class="button" href="{html.escape(decline_url, quote=True)}">DECLINE</a>
    </div>
    <a class="contact" href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>
  </header>
  <main class="preview">
    <iframe src="./site/index.html" title="Anteprima del sito per {business}" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"></iframe>
  </main>
</body>
</html>
"""


def markdown_cell(value: object) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|")


def draft_manifests(repo_root: Path) -> List[Dict[str, object]]:
    manifests: List[Dict[str, object]] = []
    for path in repo_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageError(f"Cannot read draft manifest: {path}") from exc
        lead_id = str(manifest.get("lead_id") or "")
        if path.parent.name != lead_id or not LEAD_ID_PATTERN.fullmatch(lead_id):
            raise StageError(f"Draft manifest identity mismatch: {path}")
        if manifest.get("published_path") != f"/{lead_id}/":
            raise StageError(f"Draft manifest path mismatch: {path}")
        manifests.append(manifest)
    return sorted(manifests, key=lambda item: (
        str(item.get("business_name") or "").casefold(),
        str(item.get("lead_id") or ""),
    ))


def render_draft_index(manifests: List[Dict[str, object]]) -> str:
    lines = [INDEX_START]
    if not manifests:
        lines.append("_No website drafts generated yet._")
    else:
        lines.extend([
            "| Business | Draft | Generator | Updated (UTC) |",
            "| --- | --- | --- | --- |",
        ])
        generator_names = {"lovable_mcp": "Lovable", "codex_sites": "Codex Sites"}
        for manifest in manifests:
            lead_id = str(manifest["lead_id"])
            name = markdown_cell(manifest.get("business_name") or lead_id)
            generator = generator_names.get(str(manifest.get("generator") or ""), markdown_cell(manifest.get("generator")))
            updated = markdown_cell(manifest.get("staged_at_utc"))
            url = f"{BASE_URL}/{lead_id}/"
            lines.append(f"| {name} | [Open draft]({url}) | {generator} | {updated} |")
    lines.append(INDEX_END)
    return "\n".join(lines)


def update_readme_index(repo_root: Path) -> None:
    readme = repo_root / "README.md"
    index = render_draft_index(draft_manifests(repo_root))
    if readme.exists():
        content = readme.read_text(encoding="utf-8")
    else:
        content = "# web\n"
    has_start = INDEX_START in content
    has_end = INDEX_END in content
    if has_start != has_end:
        raise StageError("README.md contains an incomplete draft-index marker pair")
    if has_start:
        prefix, remainder = content.split(INDEX_START, 1)
        _, suffix = remainder.split(INDEX_END, 1)
        content = prefix + index + suffix
    else:
        content = content.rstrip() + "\n\n## Generated drafts\n\n" + index + "\n"
    atomic_write(readme, content)


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def stage_draft(lead_path: Path, site_dir: Path, repo_root: Path, replace: bool = False) -> str:
    lead = load_lead(lead_path)
    validate_export(site_dir)
    lead_id = str(lead["lead_id"])
    business_name = str((lead.get("business") or {}).get("name") or "Attività")
    destination = repo_root / lead_id
    if destination.exists() and not replace:
        raise StageError(f"Draft already exists: {destination}; pass --replace to update it")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{lead_id}-", dir=destination.parent) as temporary_dir:
        staging = Path(temporary_dir) / lead_id
        staging.mkdir()
        shutil.copytree(site_dir, staging / "site")
        atomic_write(staging / "index.html", render_wrapper(lead_id, business_name))
        manifest = {
            "schema_version": 1,
            "lead_id": lead_id,
            "business_name": business_name,
            "generator": "lovable_mcp",
            "published_path": f"/{lead_id}/",
            "staged_at_utc": utc_now(),
        }
        atomic_write(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        if destination.exists():
            backup = destination.with_name(destination.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            destination.replace(backup)
            try:
                staging.replace(destination)
            except Exception:
                backup.replace(destination)
                raise
            shutil.rmtree(backup)
        else:
            staging.replace(destination)
    update_readme_index(repo_root)
    return f"{BASE_URL}/{lead_id}/"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage a reviewed Lovable export in the websites repository.")
    parser.add_argument("--lead", type=Path, required=True, help="Path to the local lead.json")
    parser.add_argument("--site-dir", type=Path, required=True, help="Directory containing the static index.html export")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--replace", action="store_true", help="Replace an existing staged draft")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        public_url = stage_draft(args.lead, args.site_dir, args.repo_root.resolve(), args.replace)
        print(f"Staged draft: {public_url}")
        print("Review the local diff and preview before committing and pushing.")
        return 0
    except (StageError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
