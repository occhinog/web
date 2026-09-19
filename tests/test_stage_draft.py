import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "stage_draft.py"
SPEC = importlib.util.spec_from_file_location("stage_draft", MODULE_PATH)
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


LEAD_ID = "rossi-idraulica-a1b2c3d4e5"


def lead_payload(status="draft_generated"):
    return {
        "schema_version": 1,
        "lead_id": LEAD_ID,
        "status": status,
        "business": {"name": "Rossi & Figli"},
        "draft": {
            "generator": "lovable_mcp",
            "project_id": "project-1",
            "export_file": "public/draft/index.html",
        },
    }


def write_lead(path, status="draft_generated"):
    path.write_text(json.dumps(lead_payload(status)), encoding="utf-8")


def write_export(path, body="<h1>Rossi</h1>"):
    path.mkdir()
    (path / "index.html").write_text(
        "<!doctype html><html><head>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f"</head><body>{body}</body></html>",
        encoding="utf-8",
    )


class StageDraftTests(unittest.TestCase):
    def test_stages_export_behind_decision_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lead = root / "lead.json"
            export = root / "export"
            repo = root / "repo"
            repo.mkdir()
            (repo / "README.md").write_text(
                "# web\n\n## Generated drafts\n\n"
                "<!-- draft-index:start -->\n"
                "_No website drafts generated yet._\n"
                "<!-- draft-index:end -->\n",
                encoding="utf-8",
            )
            write_lead(lead)
            write_export(export)

            url = stage.stage_draft(lead, export, repo)
            draft = repo / LEAD_ID
            wrapper = (draft / "index.html").read_text()
            self.assertEqual(url, f"https://web.occhino.it/{LEAD_ID}/")
            self.assertIn(">ACCEPT<", wrapper)
            self.assertIn(">DECLINE<", wrapper)
            self.assertIn("webmaster@occhino.it", wrapper)
            self.assertIn("./site/index.html", wrapper)
            self.assertIn("noindex,nofollow,noarchive", wrapper)
            self.assertIn("Rossi &amp; Figli", wrapper)
            self.assertTrue((draft / "site" / "index.html").is_file())
            manifest = json.loads((draft / "manifest.json").read_text())
            self.assertEqual(manifest["generator"], "lovable_mcp")
            self.assertEqual(manifest["published_path"], f"/{LEAD_ID}/")
            readme = (repo / "README.md").read_text()
            self.assertIn("Rossi & Figli", readme)
            self.assertIn(f"https://web.occhino.it/{LEAD_ID}/", readme)
            self.assertNotIn("No website drafts generated yet", readme)

    def test_requires_recorded_lovable_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lead = root / "lead.json"
            export = root / "export"
            repo = root / "repo"
            repo.mkdir()
            write_lead(lead, status="approved_for_draft")
            write_export(export)
            with self.assertRaisesRegex(stage.StageError, "draft_generated"):
                stage.stage_draft(lead, export, repo)

    def test_rejects_nonportable_and_indexable_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "export"
            write_export(export, '<script src="/assets/app.js"></script>')
            with self.assertRaisesRegex(stage.StageError, "non-portable"):
                stage.validate_export(export)

            (export / "index.html").write_text(
                '<meta name="viewport" content="width=device-width"><h1>Rossi</h1>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(stage.StageError, "noindex"):
                stage.validate_export(export)

    def test_rejects_external_loaded_resources_but_allows_contact_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "export"
            write_export(export, '<a href="https://instagram.com/rossi">Instagram</a>')
            stage.validate_export(export)

            (export / "index.html").write_text(
                '<meta name="viewport" content="width=device-width">'
                '<meta name="robots" content="noindex">'
                '<script src="https://cdn.example/app.js"></script>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(stage.StageError, "non-portable"):
                stage.validate_export(export)

    def test_rejects_forms_and_inline_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "export"
            write_export(export, '<form><input name="email"></form>')
            with self.assertRaisesRegex(stage.StageError, "forms"):
                stage.validate_export(export)

            (export / "index.html").write_text(
                '<meta name="viewport" content="width=device-width">'
                '<meta name="robots" content="noindex">'
                '<script>fetch("https://example.com")</script>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(stage.StageError, "network requests"):
                stage.validate_export(export)

    def test_requires_replace_for_existing_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lead = root / "lead.json"
            export = root / "export"
            repo = root / "repo"
            repo.mkdir()
            write_lead(lead)
            write_export(export)
            stage.stage_draft(lead, export, repo)
            with self.assertRaisesRegex(stage.StageError, "--replace"):
                stage.stage_draft(lead, export, repo)
            stage.stage_draft(lead, export, repo, replace=True)


if __name__ == "__main__":
    unittest.main()
