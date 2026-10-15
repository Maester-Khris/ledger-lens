"""Download single-fund EDGAR advisory agreements, render them to PDF (the canonical file, so every
citation has a page), and optionally upload them plus the synthetic client agreement.
Run from backend/:  SEC_USER_AGENT="Name email" $PYDEV/bin/python scripts/prepare_samples.py [--upload http://127.0.0.1:8000]
--discover N adds N more agreements found with EDGAR full-text search (one per fund family, newest first). The list
is cached in var/samples/discovered.json and files already on disk are reused, so a re-run uploads the same bytes."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
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

DISCOVERED = OUT_DIR / "discovered.json"
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEARCH_QUERY = {"q": '"investment advisory agreement"', "forms": "485BPOS", "dateRange": "custom",
                "startdt": "2020-01-01", "enddt": "2026-10-15"}  # fixed window, so a re-run finds the same filings
SEARCH_PAGES = 50  # 100 hits a page
ADVISORY_EXHIBIT = re.compile(r"EX-99\.(28)?\(?D", re.I)  # exhibit (d) of Form N-1A: the advisory contract
NOT_AN_AGREEMENT = re.compile(r"amend|amd|supplement|consent|schedule|appendix", re.I)
SEC_PAUSE_SECONDS = 0.15  # SEC fair access: at most 10 requests a second
# One fee schedule, not a multi-fund rate table: 1 to 12 percentages in the text (calibrated on 63 filings, 2026-10-15;
# the trial's multi-fund tables had 28 and 54). ponytail: a count, not a parse; extraction routing catches the rest.
RATE = re.compile(r"\d+(?:\.\d+)?\s*%")
MAX_RATES = 12


def fetch(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})  # SEC requires a named agent
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        time.sleep(SEC_PAUSE_SECONDS)
        return response.read()


def pick_agreements(hits: list[dict], count: int | None = None) -> list[dict]:
    """One exhibit (d) per fund family, newest filing first; amendments and fee-schedule-only exhibits dropped.
    ponytail: filename heuristics; the 5-document trial and the extraction status catch what slips through."""
    chosen: dict[str, dict] = {}
    for hit in sorted(hits, key=lambda h: (h["_source"]["file_date"], h["_id"]), reverse=True):
        source, (accession, filename) = hit["_source"], hit["_id"].split(":", 1)
        if not ADVISORY_EXHIBIT.match(source.get("file_type", "")) or NOT_AN_AGREEMENT.search(filename):
            continue
        if not filename.lower().endswith((".htm", ".html", ".txt")) or source["ciks"][0] in chosen:
            continue
        cik = source["ciks"][0]
        registrant = re.sub(r"\s*\(CIK.*", "", source["display_names"][0]).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", f"{registrant} {source['file_type']}".lower()).strip("-")[:70]
        chosen[cik] = {
            "key": f"edgar-{slug}", "title": f"{registrant} — {source['file_type']} ({source['file_date']})",
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filename}",
            "filed": source["file_date"], "cik": cik,
        }
        if len(chosen) == count:
            break
    return list(chosen.values())


def source_path(sample: dict) -> Path:
    return OUT_DIR / f"{sample['key']}{'.txt' if sample['url'].endswith('.txt') else '.html'}"


def single_schedule(raw: str) -> bool:
    return 1 <= len(RATE.findall(re.sub(r"<[^>]+>", " ", raw))) <= MAX_RATES


def discover(count: int, user_agent: str) -> list[dict]:
    """The first `count` agreements (one per fund family, newest first) whose text holds a single fee schedule."""
    if DISCOVERED.exists():
        cached = json.loads(DISCOVERED.read_text())
        if len(cached) >= count:
            return cached[:count]
    hits, found, checked = [], [], set()
    for page in range(SEARCH_PAGES):
        url = f"{SEARCH_URL}?{urllib.parse.urlencode(SEARCH_QUERY | {'from': page * 100})}"
        hits += json.loads(fetch(url, user_agent))["hits"]["hits"]
        for sample in pick_agreements(hits):
            if sample["cik"] in checked or len(found) == count:
                continue
            checked.add(sample["cik"])
            source = source_path(sample)
            try:
                if not source.exists():
                    source.write_bytes(fetch(sample["url"], user_agent))
            except Exception as error:
                print(f"skipped {sample['key']}: {error}", file=sys.stderr)
                continue
            if single_schedule(source.read_text(errors="ignore")):
                found.append(sample)
        if len(found) == count:
            break
    print(f"discovered {len(found)} single-schedule agreements from {len(checked)} fund families", file=sys.stderr)
    DISCOVERED.write_text(json.dumps(found, indent=2))
    return found


def relationship(source: Path) -> str:
    """Sub-advisory agreements (adviser to sub-adviser) are kept but counted apart from advisory ones."""
    head = source.read_text(errors="ignore")[:6000].lower()
    return "sub-advisory" if re.search(r"sub-?\s?advis", head) else "advisory"


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
    parser.add_argument("--discover", type=int, default=0, metavar="N", help="add N agreements from EDGAR full-text search")
    parser.add_argument("--upload-count", type=int, metavar="K", help="upload only the first K discovered agreements")
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        sys.exit("Set SEC_USER_AGENT to 'Your Name your.email@example.com' (SEC fair-access policy).")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    discovered = discover(args.discover, user_agent) if args.discover else []
    to_upload = {s["key"] for s in SAMPLES + discovered[:args.upload_count]}
    manifest = []
    for sample in SAMPLES + discovered:
        source = source_path(sample)
        pdf = OUT_DIR / f"{sample['key']}.pdf"
        try:
            if not source.exists():
                source.write_bytes(fetch(sample["url"], user_agent))
            if not pdf.exists():  # a re-render changes the bytes, which would make a new document version
                render_pdf(source, pdf)
        except Exception as error:  # one bad filing must not stop the batch
            print(f"skipped {sample['key']}: {error}", file=sys.stderr)
            continue
        manifest.append(sample | {"pdf": pdf.name, "relationship": relationship(source)})
        if args.upload and sample["key"] in to_upload:
            upload(args.upload, sample["key"], sample["title"], pdf, sample["url"])
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if args.upload:
        upload(args.upload, "tremblay-ima", "Tremblay household — Investment Management Agreement (synthetic)",
               SYNTHETIC, None, TREMBLAY_HOUSEHOLD_ID)


if __name__ == "__main__":
    main()
