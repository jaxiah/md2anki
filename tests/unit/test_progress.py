from io import StringIO

from md2anki.progress import ProgressReporter


def test_compact_progress_reuses_one_terminal_line():
    output = StringIO()
    progress = ProgressReporter(stream=output, enabled=True, bar_width=10)

    progress("parse", 1, 2, "first.md", "parsed")
    progress("sync", 2, 2, "Question", "updated")
    progress.finish()

    rendered = output.getvalue()
    assert rendered.count("\r") == 2
    assert rendered.endswith("\n")
    assert "Preparing" in rendered
    assert "Syncing" in rendered
    assert "first.md" not in rendered
    assert "Question" not in rendered
    assert "status=" not in rendered


def test_verbose_progress_prints_per_item_details_without_bar():
    output = StringIO()
    progress = ProgressReporter(verbose=True, stream=output, enabled=True)

    progress("sync", 1, 3, "Question", "updated")
    progress.finish()

    assert output.getvalue() == (
        "[md2anki][verbose] stage=sync current=1/3 item=Question status=updated\n"
    )


def test_compact_progress_is_hidden_for_noninteractive_output():
    output = StringIO()
    progress = ProgressReporter(stream=output)

    progress("parse", 1, 1, "first.md", "parsed")
    progress.finish()

    assert output.getvalue() == ""
