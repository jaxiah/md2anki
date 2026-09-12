from pathlib import Path


def test_windows_launcher_keeps_verbose_output_opt_in():
    launcher = Path(__file__).resolve().parents[2] / "md2anki.cmd"
    command_line = next(
        line
        for line in launcher.read_text(encoding="utf-8").splitlines()
        if "-m md2anki" in line and not line.lstrip().upper().startswith("REM ")
    )

    assert "--apply-anki-changes" in command_line
    assert "--verbose" not in command_line
