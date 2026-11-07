"""Package imports must coexist with other tools' modules of the same name.

A fresh interpreter prevents cached imports from hiding namespace collisions.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ARTIFACTS = PROJECT_ROOT / "reference-artifacts"
GOLDEN_TYPST = REFERENCE_ARTIFACTS / "2026-standings-golden.typ"

# The top-level module names Flickornas used to install.
FORMER_NAMES = (
    "active_configuration", "artifact_publication", "atomic_write", "calendar_year",
    "flickornas_cli", "flickornas_web", "generation_core", "generation_orchestrator",
    "generation_progress", "generation_rules", "klass_naming", "member_system_client",
    "numeric_validation", "points", "run_state", "typst_rules",
)


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=cwd, capture_output=True, text=True, check=False,
    )


class ModuleNamespaceTests(unittest.TestCase):
    def test_no_module_is_importable_under_a_former_top_level_name(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run(f"""
                import importlib.util
                found = [name for name in {FORMER_NAMES!r} if importlib.util.find_spec(name)]
                assert found == [], found
            """, cwd=Path(directory))

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_generation_beside_stand_ins_for_the_former_names_reproduces_the_golden_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stand_ins = root / "other-tool"
            stand_ins.mkdir()
            for name in FORMER_NAMES:
                (stand_ins / f"{name}.py").write_text(f"OWNER = 'other {name}'\n")
            working_directory = root / "cwd"
            working_directory.mkdir()

            result = _run(f"""
                import sys
                sys.path.insert(0, {str(stand_ins)!r})
                names = {FORMER_NAMES!r}
                for name in names:
                    __import__(name)

                from pathlib import Path
                import zipfile
                from flickornas_standings.artifact_publication import publish_generation
                from flickornas_standings.generation_core import generate_standings, load_archived_inputs

                inputs = Path({str(root / "inputs")!r})
                with zipfile.ZipFile({str(REFERENCE_ARTIFACTS / "2026-intermediate-inputs.zip")!r}) as archive:
                    archive.extractall(inputs)
                tournaments, players, stats = load_archived_inputs(inputs)
                result = generate_standings(
                    effective_year=2026,
                    tournaments=tournaments,
                    player_list=players,
                    tournament_stats=stats,
                    contributor={{"name": "Ganesh Srinivasson", "email": "bganesh@gmail.com"}},
                )

                class CheckingRenderer:
                    def render(self, source, destination, *, root, font_directory):
                        assert (root / "lib.typ").is_file() and (root / "rules.typ").is_file(), root
                        assert any(font_directory.glob("*.ttf")), font_directory
                        Path({str(root / "source.typ")!r}).write_bytes(source.read_bytes())
                        destination.write_bytes(b"%PDF-")

                publish_generation(
                    result,
                    Path({str(root / "output")!r}),
                    state_directory=Path({str(root / "state")!r}),
                    renderer=CheckingRenderer(),
                )
                for name in names:
                    assert sys.modules[name].OWNER == f"other {{name}}", name
            """, cwd=working_directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "source.typ").read_bytes(), GOLDEN_TYPST.read_bytes()
            )
            self.assertEqual(list(working_directory.iterdir()), [])

    def test_importing_the_manifest_touches_no_files_and_starts_no_services(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run(f"""
                import os, sys, threading
                accessed = []
                def audit(event, arguments):
                    if event in ("socket.connect", "subprocess.Popen"):
                        accessed.append(event)
                    elif event == "open" and isinstance(arguments[0], str) and not arguments[0].endswith((".py", ".pyc", ".so")):
                        # Installed packages may read their own metadata; the checkout itself must stay untouched.
                        if not os.path.isabs(arguments[0]) or (
                            arguments[0].startswith({str(PROJECT_ROOT)!r}) and not arguments[0].startswith(sys.prefix)
                        ):
                            accessed.append(arguments[0])
                sys.addaudithook(audit)

                from flickornas_standings.web import MANIFEST
                assert MANIFEST["url_prefix"] == "/tools/flickornas"
                assert accessed == [] and threading.active_count() == 1, (accessed, threading.enumerate())
            """, cwd=Path(directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
