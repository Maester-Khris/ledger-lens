"""Crash-resumable JSONL checkpointing for long-running evaluation stages."""
import json
import os
from pathlib import Path


class Checkpoint:
    def __init__(self, final_path: Path, key: str = "id") -> None:
        self.final_path = Path(final_path)
        self.partial_path = self.final_path.with_suffix(".partial.jsonl")
        self.key = key

    def done(self) -> set[str]:
        return {str(row[self.key]) for row in self.rows() if self.key in row}

    def append(self, row: dict) -> None:
        self.partial_path.parent.mkdir(parents=True, exist_ok=True)
        with self.partial_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row) + "\n")
            out.flush()
            os.fsync(out.fileno())

    def rows(self) -> list[dict]:
        if not self.partial_path.exists():
            return []
        lines = self.partial_path.read_text(encoding="utf-8").splitlines()
        parsed: list[dict] = []
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                if idx == len(lines) - 1:
                    break
                raise
        return parsed

    def finish(self) -> Path:
        complete = self.rows()
        self.final_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.final_path.with_suffix(".tmp.jsonl")
        with tmp_path.open("w", encoding="utf-8") as out:
            for row in complete:
                out.write(json.dumps(row) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_path, self.final_path)
        self.partial_path.unlink(missing_ok=True)
        return self.final_path


def summary_line(stage: str, **counts: object) -> str:
    return json.dumps({"stage": stage, **counts})
