from pathlib import Path

from iteration_wallet import cli, server


def _active_html() -> str:
    return (Path(server.__file__).parent / "static" / "app.html").read_text(encoding="utf-8")


def test_browser_client_uses_relative_canonical_api_only() -> None:
    html = _active_html()
    assert "const API_BASE = '/api/v21'" in html
    assert "http://localhost:7432/api" not in html
    assert "api('GET', '/state')" in html
    assert "api('POST', '/identity/sessions'" in html
    assert "api('POST', '/ceremony/tokens'" in html
    assert "/candidates/${candidateId}/promote" in html
    assert "/labcopy/proposal" in html
    assert "/export-working-copy" in html
    assert "/results/capture" in html
    assert "/admission-proposal" in html
    assert "/results/${capsuleId}/admit" in html
    assert "/security/passkeys/authentication/options" in html
    assert "/oubliette/inspect" not in html


def test_browser_client_describes_the_bounded_product_honestly() -> None:
    html = _active_html().lower()
    assert "canonical promotion" in html
    assert "labcopy workspace" in html
    assert "candidate-only return" in html
    assert "legacy oubliette compatibility remains backend-only" in html
    assert "one-use protected-action token" in html
    assert "file watcher active" not in html
    assert "release from wallet" not in html
    assert "remove a file" not in html


def test_cli_defaults_to_canonical_api_and_exposes_only_supported_mutations() -> None:
    assert cli.VAULT_API.endswith("/api/v21")
    parser = cli.build_parser()
    subcommands = set(parser._subparsers._group_actions[0].choices)
    assert {
        "serve",
        "status",
        "open",
        "lock",
        "create-project",
        "create-section",
        "add-candidate",
        "add-raw-source",
        "start-session",
        "promote",
        "labcopy-export",
        "labcopy-reenter",
        "receipts",
        "receipt",
        "chain",
        "custody",
    } <= subcommands
    assert not ({"remove", "restore", "drives", "mark-drive", "events", "oubliette-inspect", "oubliette-quarantine", "oubliette-inspect-derivative", "oubliette-admit-derivative"} & subcommands)


def test_cli_promote_requires_explicit_scope_and_human_confirmation() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "promote",
            "project-1",
            "section-1",
            "candidate-1",
            "--actor-id",
            "josie",
            "--confirm",
            "PROMOTE",
        ]
    )
    assert args.project_id == "project-1"
    assert args.section_id == "section-1"
    assert args.candidate_id == "candidate-1"
    assert args.confirm == "PROMOTE"
