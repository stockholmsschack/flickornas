from __future__ import annotations

import io
from pathlib import Path
import re
import tempfile
import unittest

from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.artifact_publication import publish_generation
from flickornas_standings.web import create_app
from tests.test_artifact_publication import FakeRenderer, _result
from flickornas_standings.typst_rules import BUILT_IN_RULES_PATH, MAX_RULES_FILE_BYTES


class TypstRulesConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_directory = self.root / "state"
        self.output_directory = self.root / "output"
        save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(11,),
                contributor={"name": "Fixture", "email": "f@example.com"},
            ),
        )
        self.app = create_app(
            {
                "TESTING": True,
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": self.output_directory,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_configuration_page_has_download_and_upload_controls(self):
        body = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )

        self.assertIn('id="rules-file-tab"', body)
        self.assertIn('id="rules-file-panel"', body)
        self.assertIn("Download current rules.typ", body)
        self.assertIn("Restore original", body)
        self.assertIn("data-restore-rules-file", body)
        self.assertRegex(body, r"data-restore-rules-file\s+disabled")
        self.assertIn('accept=".typ"', body)
        self.assertIn('data-upload-rules-file', body)
        self.assertIn('src="/static/js/rules-file-editor.js"', body)

    def test_download_uses_built_in_file_until_one_is_uploaded(self):
        with self.client.get("/api/v1/configuration/rules") as initial:
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.data, BUILT_IN_RULES_PATH.read_bytes())

        replacement = b"= Updated rules\n"
        uploaded = self.client.post(
            "/api/v1/configuration/rules",
            data={"rules": (io.BytesIO(replacement), "rules.typ")},
            content_type="multipart/form-data",
        )

        self.assertEqual(uploaded.status_code, 200)
        active_body = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        restore_button = re.search(
            r"<button[^>]*data-restore-rules-file[^>]*>",
            active_body,
        )
        self.assertIsNotNone(restore_button)
        self.assertNotIn("disabled", restore_button.group())
        with self.client.get("/api/v1/configuration/rules") as current:
            self.assertEqual(current.data, replacement)

    def test_upload_rejects_files_that_cannot_be_used(self):
        cases = (
            (b"rules", "rules.txt"),
            (b"", "rules.typ"),
            (b"\xff", "rules.typ"),
            (b"x" * (MAX_RULES_FILE_BYTES + 1), "rules.typ"),
        )
        for content, filename in cases:
            with self.subTest(filename=filename, size=len(content)):
                response = self.client.post(
                    "/api/v1/configuration/rules",
                    data={"rules": (io.BytesIO(content), filename)},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error"]["message_key"],
                    "errors.rules_file.invalid",
                )

    def test_restore_removes_override_and_returns_to_built_in_file(self):
        replacement = b"= Updated rules\n"
        self.client.post(
            "/api/v1/configuration/rules",
            data={"rules": (io.BytesIO(replacement), "rules.typ")},
            content_type="multipart/form-data",
        )

        restored = self.client.delete("/api/v1/configuration/rules")

        self.assertEqual(restored.status_code, 200)
        self.assertTrue(restored.get_json()["data"]["restored"])
        with self.client.get("/api/v1/configuration/rules") as current:
            self.assertEqual(current.data, BUILT_IN_RULES_PATH.read_bytes())
        repeated = self.client.delete("/api/v1/configuration/rules")
        self.assertFalse(repeated.get_json()["data"]["restored"])

    def test_future_publications_copy_the_uploaded_rules_file(self):
        replacement = b"= Updated rules\n"
        self.client.post(
            "/api/v1/configuration/rules",
            data={"rules": (io.BytesIO(replacement), "rules.typ")},
            content_type="multipart/form-data",
        )

        published = publish_generation(
            _result(),
            self.output_directory,
            state_directory=self.state_directory,
            run_id="custom-rules",
            renderer=FakeRenderer(),
        )

        self.assertEqual(
            (published.run_directory / "rules.typ").read_bytes(),
            replacement,
        )


if __name__ == "__main__":
    unittest.main()
