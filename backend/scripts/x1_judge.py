"""Evaluate exported evidence crops using an LLM judge on OpenAI-compatible endpoints (X1).

Run from backend/:  $PYDEV/bin/python scripts/x1_judge.py labels.csv --provider groq --model llama-3.2-11b-vision-preview --out judged.csv
Note: Judges are paid calls the owner approves first.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.contracts.verify import VisionRequest, VisionVerifier  # noqa: E402


def judge(csv_in: Path, csv_out: Path, verifier: VisionVerifier) -> None:
    """Read exported evidence crops with a vision judge and write results to csv_out.

    Inputs are already redacted. Judged values are formatted for label import.
    """
    with csv_in.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    requests: list[VisionRequest] = []
    for row in reader:
        crop_path = csv_in.parent / row["crop_file"]
        requests.append(VisionRequest(field_path=row["field_path"], image_png=crop_path.read_bytes()))

    readings = verifier.read(requests)

    fieldnames = list(reader[0].keys()) if reader else ["item", "run_id", "field_path", "crop_file", "value"]
    if "error" not in fieldnames:
        fieldnames.append("error")

    out_rows = []
    for row, reading in zip(reader, readings):
        out_row = dict(row)
        if reading.failed is not None:
            out_row["value"] = ""
            out_row["error"] = reading.failed
        else:
            out_row["error"] = ""
            if reading.value is None:
                out_row["value"] = "null"
            elif isinstance(reading.value, str):
                out_row["value"] = reading.value
            else:
                out_row["value"] = json.dumps(reading.value)
        out_rows.append(out_row)

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="input labels CSV")
    parser.add_argument("--provider", choices=["anthropic", "groq"], required=True, help="LLM provider")
    parser.add_argument("--model", "-m", required=True, help="model identifier")
    parser.add_argument("--out", type=Path, required=True, help="output CSV path")
    args = parser.parse_args()

    if args.model == config.VERIFIER_MODEL:
        raise ValueError(f"Judge model cannot be the verifier model ({config.VERIFIER_MODEL})")

    env = dotenv_values(config.BACKEND_DIR / ".env.demo")
    if args.provider == "anthropic":
        base_url = "https://api.anthropic.com/v1/"
        api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env.demo or environment")
    elif args.provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        api_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set in backend/.env.demo or environment")
    else:
        raise ValueError(f"Unsupported provider: {args.provider}")

    chat_model = ChatOpenAI(model=args.model, api_key=api_key, base_url=base_url)
    verifier = VisionVerifier(chat_model, f"judge:{args.model}")
    judge(args.csv, args.out, verifier)
    print(f"Judged {args.csv} -> {args.out} using {args.provider}/{args.model}")


if __name__ == "__main__":
    main()
