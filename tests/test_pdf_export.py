from pathlib import Path
from urllib.request import urlopen

from colloquium.export import _serve_html_for_export


def test_serve_html_for_export_serves_deck_over_loopback(tmp_path):
    html_path = tmp_path / "deck file.html"
    html_path.write_text("<!doctype html><title>Deck</title>", encoding="utf-8")

    with _serve_html_for_export(str(html_path)) as url:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/deck%20file.html")
        with urlopen(url, timeout=2) as response:
            body = response.read().decode("utf-8")

    assert "<title>Deck</title>" in body


def _run_fake_export(monkeypatch, tmp_path):
    """Drive _export_pdf_from_html with a stubbed browser; return the cmd."""
    from colloquium import export as export_mod

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # Simulate Chromium writing the PDF so the happy path completes.
        for arg in cmd:
            if arg.startswith("--print-to-pdf="):
                Path(arg.split("=", 1)[1]).write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(export_mod, "_find_browser", lambda: "/fake/chrome")
    monkeypatch.setattr(export_mod, "_compress_pdf", lambda path: None)
    monkeypatch.setattr(export_mod.subprocess, "run", fake_run)

    html_path = tmp_path / "deck.html"
    html_path.write_text("<!doctype html><title>Deck</title>", encoding="utf-8")
    output_path = str(tmp_path / "deck.pdf")

    result = export_mod._export_pdf_from_html(str(html_path), output_path)
    assert result == output_path
    return captured["cmd"]


def test_pdf_export_uses_generous_default_time_budget(monkeypatch, tmp_path):
    monkeypatch.delenv("COLLOQUIUM_PDF_TIME_BUDGET_MS", raising=False)
    cmd = _run_fake_export(monkeypatch, tmp_path)
    assert "--virtual-time-budget=30000" in cmd


def test_pdf_export_time_budget_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLOQUIUM_PDF_TIME_BUDGET_MS", "7000")
    cmd = _run_fake_export(monkeypatch, tmp_path)
    assert "--virtual-time-budget=7000" in cmd


def test_pdf_export_time_budget_ignores_bad_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLOQUIUM_PDF_TIME_BUDGET_MS", "not-a-number")
    cmd = _run_fake_export(monkeypatch, tmp_path)
    assert "--virtual-time-budget=30000" in cmd
