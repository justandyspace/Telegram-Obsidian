"""Tests for v3 refactoring: schema versioning, stuck job recovery, code quality."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.infra.storage import SCHEMA_VERSION, StateStore


class SchemaVersioningTests(unittest.TestCase):
    """Test DB schema versioning and migration system."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite3"
        self.store = StateStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_fresh_db_gets_latest_schema_version(self) -> None:
        self.store.initialize()
        self.assertEqual(self.store.schema_version(), SCHEMA_VERSION)

    def test_reinitialize_is_idempotent(self) -> None:
        self.store.initialize()
        # Second initialize should not fail
        self.store.close()
        self.store = StateStore(self.db_path)
        self.store.initialize()
        self.assertEqual(self.store.schema_version(), SCHEMA_VERSION)

    def test_tables_exist_after_init(self) -> None:
        self.store.initialize()
        conn = sqlite3.connect(str(self.db_path))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        self.assertIn("jobs_mt", tables)
        self.assertIn("notes_mt", tables)
        self.assertIn("schema_migrations", tables)


class StuckJobRecoveryTests(unittest.TestCase):
    """Test that stuck processing jobs are recovered."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite3"
        self.store = StateStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_recover_stuck_processing_jobs(self) -> None:
        # Enqueue and acquire a job (puts it in 'processing' state)
        self.store.enqueue_job(
            idempotency_key="stuck-1",
            content_fingerprint="fp-stuck",
            tenant_id="t1",
            user_id=111,
            chat_id=222,
            message_id=333,
            payload={"text": "test"},
            max_attempts=3,
        )
        job = self.store.acquire_next_job()
        self.assertIsNotNone(job)

        # Simulate the job being stuck by backdating its processing_started_at
        conn = sqlite3.connect(str(self.db_path))
        old_time = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()
        conn.execute(
            "UPDATE jobs_mt SET processing_started_at = ?, updated_at = ? WHERE job_id = ?",
            (old_time, old_time, job.job_id),
        )
        conn.commit()
        conn.close()

        # Recover stuck jobs (600 seconds = 10 min)
        recovered = self.store.recover_stuck_jobs(max_processing_age_seconds=600)
        self.assertEqual(recovered, 1)

        # Verify the job is now in 'retry' state
        counts = self.store.status_counts()
        self.assertEqual(counts.get("retry", 0), 1)
        self.assertEqual(counts.get("processing", 0), 0)

    def test_no_recovery_for_recent_processing(self) -> None:
        # A recently acquired job should NOT be recovered
        self.store.enqueue_job(
            idempotency_key="recent-1",
            content_fingerprint="fp-recent",
            tenant_id="t1",
            user_id=111,
            chat_id=222,
            message_id=333,
            payload={"text": "test"},
            max_attempts=3,
        )
        self.store.acquire_next_job()

        # Try to recover with 600s timeout — job was just acquired
        recovered = self.store.recover_stuck_jobs(max_processing_age_seconds=600)
        self.assertEqual(recovered, 0)


class DockerfileSecurityTests(unittest.TestCase):
    """Test that Dockerfile follows security best practices."""

    def test_dockerfile_has_non_root_user(self) -> None:
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile.read_text()
        self.assertIn("USER", content, "Dockerfile should set a non-root USER")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip().startswith("USER")]
        self.assertTrue(len(lines) > 0, "Dockerfile must have a USER directive")
        for line in lines:
            self.assertNotIn("root", line.lower(), "Dockerfile should not run as root")

    def test_dockerignore_excludes_secrets(self) -> None:
        dockerignore = Path(__file__).parent.parent / ".dockerignore"
        content = dockerignore.read_text()
        self.assertIn(".env", content)
        self.assertIn(".git", content)

    def test_gitignore_excludes_backups(self) -> None:
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text()
        self.assertIn("backups/", content)


class CodeQualityTests(unittest.TestCase):
    """Test structural code quality properties."""

    def test_no_print_statements_in_src(self) -> None:
        """Production code should use logging, not print()."""
        import ast
        src_dir = Path(__file__).parent.parent / "src"
        violations = []
        for py_file in src_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == "print":
                        violations.append(f"{py_file.name}:{node.lineno}")
        self.assertEqual(violations, [], f"print() found in: {violations}")

    def test_all_modules_have_docstrings(self) -> None:
        """All Python modules should have a module docstring."""
        src_dir = Path(__file__).parent.parent / "src"
        missing = []
        for py_file in src_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text(encoding="utf-8").strip()
            if not content:
                continue
            has_docstring = False
            for line in content.split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("from __future__"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    has_docstring = True
                break
            if not has_docstring:
                missing.append(py_file.name)
        self.assertEqual(missing, [], f"Missing docstrings: {missing}")


if __name__ == "__main__":
    unittest.main()
