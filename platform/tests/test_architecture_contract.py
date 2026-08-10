import ast
import unittest
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "src" / "a_share_platform"


class ArchitectureContractTest(unittest.TestCase):
    def test_required_modular_monolith_boundaries_exist(self) -> None:
        for package in ("domain", "application", "ports", "adapters", "api", "workers"):
            with self.subTest(package=package):
                self.assertTrue((PACKAGE_ROOT / package / "__init__.py").is_file())

    def test_domain_does_not_import_frameworks_providers_or_outer_layers(self) -> None:
        forbidden_roots = {
            "fastapi",
            "sqlalchemy",
            "pydantic",
            "psycopg",
            "futu",
            "openai",
            "a_share_platform.application",
            "a_share_platform.ports",
            "a_share_platform.adapters",
            "a_share_platform.api",
            "a_share_platform.workers",
        }
        violations: list[str] = []
        for path in sorted((PACKAGE_ROOT / "domain").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = (node.module,)
                for module in imported:
                    if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots):
                        violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual(violations, [])

    def test_local_runtime_and_ci_assets_stay_inside_platform(self) -> None:
        for relative_path in (
            "compose.yaml",
            "ci/verify.sh",
            "migrations/0001_governance_ledger.sql",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((PLATFORM_ROOT / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
