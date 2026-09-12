import sys
from typing import TextIO


class ProgressReporter:
    """Render one compact progress line or opt-in per-item details."""

    _STAGE_LABELS = {
        "parse": "Preparing",
        "media": "Uploading media",
        "sync": "Syncing",
    }

    def __init__(
        self,
        *,
        verbose: bool = False,
        stream: TextIO | None = None,
        enabled: bool | None = None,
        bar_width: int = 24,
    ) -> None:
        self.verbose = verbose
        self.stream = stream or sys.stdout
        self.enabled = self.stream.isatty() if enabled is None else enabled
        self.bar_width = bar_width
        self._active = False
        self._last_line_width = 0

    def __call__(
        self,
        stage: str,
        current: int,
        total: int,
        name: str | None = None,
        status: str | None = None,
    ) -> None:
        if self.verbose:
            details = [f"stage={stage}", f"current={current}/{total}"]
            if name:
                details.append(f"item={name}")
            if status:
                details.append(f"status={status}")
            print(f"[md2anki][verbose] {' '.join(details)}", file=self.stream)
            return

        if not self.enabled or total <= 0:
            return

        bounded_current = min(max(current, 0), total)
        filled = round(self.bar_width * bounded_current / total)
        bar = "#" * filled + "-" * (self.bar_width - filled)
        label = self._STAGE_LABELS.get(stage, stage.capitalize())
        line = f"[md2anki] {label:<15} [{bar}] {bounded_current}/{total}"
        padded_line = line.ljust(self._last_line_width)
        self.stream.write(f"\r{padded_line}")
        self.stream.flush()
        self._active = True
        self._last_line_width = len(line)

    def finish(self) -> None:
        if self._active:
            self.stream.write("\n")
            self.stream.flush()
            self._active = False
