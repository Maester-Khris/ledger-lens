"""Download single-fund EDGAR advisory agreements, render them to PDF (the canonical file, so every
citation has a page), and optionally upload them plus the synthetic client agreement.
Run from backend/:  SEC_USER_AGENT="Name email" $PYDEV/bin/python scripts/prepare_samples.py [--upload http://127.0.0.1:8000]"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND_DIR / "var" / "samples"
CHROME = "google-chrome"
SYNTHETIC = BACKEND_DIR / "tests" / "fixtures" / "documents" / "client_agreement.pdf"
SAMPLES = [
    {"key": "nomura-tax-free-colorado-ima", "title": "Voyageur Mutual Funds II / Delaware Management — IMA (2025)",
     "url": "https://www.sec.gov/Archives/edgar/data/809872/000113322825014217/vmfii-efp21465_ex99d1.htm"},
    {"key": "aim-global-trends-advisory", "title": "AIM Global Trends Fund — Master Investment Advisory Agreement",
     "url": "https://www.sec.gov/Archives/edgar/data/1021453/000095012902002087/h95945ex99-d.txt"},
    {"key": "calamos-emerging-market-equity", "title": "Calamos Emerging Market Equity Fund — Management Agreement notice",
     "url": "https://www.sec.gov/Archives/edgar/data/826732/000119312513480695/d640945dex99d15.htm"},
]
TIMEOUT_SECONDS = 60
# Same derivation as scripts/seed_demo.py, so the synthetic agreement links to the seeded Tremblay household.
TREMBLAY_HOUSEHOLD_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "ledger-lens-demo/hh_tremblay"))


def fetch(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})  # SEC requires a named agent
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def render_pdf(source: Path, pdf: Path) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", source.as_uri()],
        check=True, timeout=TIMEOUT_SECONDS, capture_output=True,
    )


def upload(base_url: str, key: str, title: str, pdf: Path, source_url: str | None, household_id: str | None = None) -> None:
    data = {"document_key": key, "title": title} | ({"source_url": source_url} if source_url else {})
    data |= {"household_id": household_id} if household_id else {}
    response = httpx.post(f"{base_url}/documents", data=data,
                          files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    print(f"uploaded {key}: {response.status_code} {response.json()['status_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", metavar="BASE_URL", help="also POST each PDF to the running API")
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        sys.exit("Set SEC_USER_AGENT to 'Your Name your.email@example.com' (SEC fair-access policy).")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for sample in SAMPLES:
        suffix = ".txt" if sample["url"].endswith(".txt") else ".html"
        source = OUT_DIR / f"{sample['key']}{suffix}"
        pdf = OUT_DIR / f"{sample['key']}.pdf"
        source.write_bytes(fetch(sample["url"], user_agent))
        render_pdf(source, pdf)
        manifest.append(sample | {"pdf": pdf.name})
        if args.upload:
            upload(args.upload, sample["key"], sample["title"], pdf, sample["url"])
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if args.upload:
        upload(args.upload, "tremblay-ima", "Tremblay household — Investment Management Agreement (synthetic)",
               SYNTHETIC, None, TREMBLAY_HOUSEHOLD_ID)


if __name__ == "__main__":
    main()
