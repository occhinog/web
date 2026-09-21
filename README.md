# web

Public site for **Occhino.web** at the repository root, plus static hosting for
reviewed website drafts generated from the
[`LeadScanner`](https://github.com/occhinog/LeadScanner) workflow.

- Public host: <https://web.occhino.it>
- Published paths: `https://web.occhino.it/<lead-id>/`
- Contact: `webmaster@occhino.it`

The homepage is the public Occhino.web offer page and is the only crawlable
path: `robots.txt` disallows everything and re-allows only `/$`. Draft pages
stay out of crawlers wherever they are mounted, and each is additionally marked
`noindex,nofollow,noarchive`.

The homepage does not list drafts, but this README records each generated draft
so the repository remains inspectable. That list is public, so prefer lead IDs
that do not disclose a client's name. Draft URLs are unlisted, not access
controlled: anyone with a link can open it, and all committed files are public.
Do not commit private notes, personal data that is not already intended for the
business's public contact, API keys, or source material without usage rights.

## Homepage hero

The homepage selects one optimized image on each page load from
`images/hero-studio.jpg`, `images/hero-meccanico.jpg`, and
`images/hero-fiorista.jpg`. The selection runs before the stylesheet is parsed,
so only the chosen image is requested. `hero-studio.jpg` is the CSS fallback
when JavaScript is unavailable.

## Homepage portfolio

The homepage portfolio uses optimized static captures of the four linked live
sites in `images/portfolio-*.jpg`. Refresh those captures when a featured site
changes materially so the visual card still represents the live work.

## Generated drafts

<!-- draft-index:start -->
_No website drafts generated yet._
<!-- draft-index:end -->

`tools/stage_draft.py` updates this list whenever a reviewed export is staged.

## Draft structure

Each staged draft has this shape:

```text
<lead-id>/
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

Open `http://localhost:8000/<lead-id>/` for visual review. After review,
commit and push `main`; GitHub Pages publishes the repository root using the
custom domain in `CNAME`.
