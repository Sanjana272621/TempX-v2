import importlib
from pathlib import Path

import pytest


telemetry = importlib.import_module(
    "lambda.store_telemetry.lambda_function"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_required_repository_directories_exist():
    assert (PROJECT_ROOT / "infrastructure").is_dir()
    assert (PROJECT_ROOT / "lambda").is_dir()
    assert (PROJECT_ROOT / "simulator").is_dir()
    assert (PROJECT_ROOT / "tests").is_dir()


def test_required_terraform_files_exist():
    required_files = [
        "main.tf",
        "variables.tf",
        "outputs.tf",
        "versions.tf",
    ]

    for filename in required_files:
        assert (
            PROJECT_ROOT
            / "infrastructure"
            / filename
        ).is_file()


def test_missing_table_configuration_fails_clearly(
    monkeypatch,
):
    monkeypatch.delenv("TELEMETRY_TABLE", raising=False)
    monkeypatch.setattr(telemetry, "_dynamodb_table", None)

    with pytest.raises(
        RuntimeError,
        match="TELEMETRY_TABLE",
    ):
        telemetry.get_table()


def test_private_files_are_gitignored():
    gitignore = (
        PROJECT_ROOT / ".gitignore"
    ).read_text(encoding="utf-8")

    assert "certs/" in gitignore
    assert ".env" in gitignore
    assert "*.tfstate" in gitignore