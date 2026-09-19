# web

Public, static hosting for reviewed website drafts generated from the
[`LeadScanner`](https://github.com/occhinog/LeadScanner) workflow.

- Public host: <https://web.occhino.it>
- Published paths: `https://web.occhino.it/drafts/<lead-id>/`
- Contact: `webmaster@occhino.it`

The root page does not list drafts, every page is marked `noindex`, and
`robots.txt` asks crawlers not to index the site. URLs are unlisted, not access
controlled: anyone with a link can open it, and all committed files are public.
Do not commit private notes, personal data that is not already intended for the
business's public contact, API keys, or source material without usage rights.

## Draft structure

Each staged draft has this shape:

```text
drafts/<lead-id>/
├── index.html       # host-owned ACCEPT / DECLINE wrapper
├── manifest.json    # minimal publication metadata
└── site/
    └── index.html   # reviewed Lovable static export
```

The wrapper displays the business draft inside an iframe and keeps a fixed top
bar with:

- `ACCEPT`: opens a pre-addressed email to `webmaster@occhino.it`.
- `DECLINE`: opens a pre-addressed email to `webmaster@occhino.it`.
- The visible `webmaster@occhino.it` contact address.

## Stage a reviewed Lovable export

The matching local `lead.json` must first have `status: draft_generated` and a
recorded `lovable_mcp` project. The export must contain `index.html`, a viewport
meta tag, and a `noindex` robots meta tag. Loaded resources must be local or
inline so the page remains portable under its draft subdirectory.

```bash
python3 tools/stage_draft.py \
  --lead ~/GitHub/LeadScanner/leads/RUN/LEAD-ID/lead.json \
  --site-dir /path/to/lovable-export
```

The command stages files but does not commit or push them. Review the page
locally at desktop and mobile widths before publication. To update an existing
draft, repeat with `--replace`.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -m http.server 8000
```

Open `http://localhost:8000/drafts/<lead-id>/` for visual review. After review,
commit and push `main`; GitHub Pages publishes the repository root using the
custom domain in `CNAME`.
