import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import pandas as pd
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
import logging
from datetime import datetime
import difflib
import multiprocessing

# Logging
logging.basicConfig(filename='crawler.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Config
BASE_URL = "https://auraadesign.co.uk"
SITEMAP_URL = urljoin(BASE_URL, "/sitemap_index.xml")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SpellSentinelBot/1.0)"}
MAX_DOWNLOAD_WORKERS = 30
MAX_PROCESS_WORKERS = multiprocessing.cpu_count()
RETRY_LIMIT = 3
TIMEOUT = 15

# Load word list once (shared between processes)
try:
    with open("en_GB.txt", "r", encoding="utf-8") as f:
        british_words = set(word.strip().lower() for word in f if word.strip())
    logging.info("Custom en_GB word list loaded.")
except FileNotFoundError:
    logging.error("British English word list 'en_GB.txt' not found. Exiting.")
    raise SystemExit("❌ 'en_GB.txt' not found.")

CUSTOM_IGNORE = {"auraa", "auraadesign", "luxury", "wallart", "faux"}
british_words.update(CUSTOM_IGNORE)

# Shared session
session = requests.Session()
session.headers.update(HEADERS)

def extract_urls_from_sitemap(sitemap_url):
    urls = []
    try:
        resp = session.get(sitemap_url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return urls
        root = ET.fromstring(resp.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        for sitemap in root.findall("ns:sitemap", ns):
            loc = sitemap.find("ns:loc", ns).text
            urls.extend(extract_urls_from_sitemap(loc))
        for url in root.findall("ns:url", ns):
            loc = url.find("ns:loc", ns)
            if loc is not None:
                urls.append(loc.text)
    except Exception as e:
        logging.error(f"Sitemap parse error: {e}")
    return urls

def extract_text_from_url(url):
    for attempt in range(RETRY_LIMIT):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = ' '.join(soup.stripped_strings)
            return url, text.strip()
        except Exception as e:
            logging.warning(f"Retry {attempt + 1} for {url}: {e}")
            time.sleep(1)
    return url, ""

# Edit-distance suggestion
def suggest_word(word):
    matches = difflib.get_close_matches(word, british_words, n=1, cutoff=0.8)
    return matches[0] if matches else ""

def find_spelling_errors_for_text(data):
    url, text = data
    if not text or len(text) < 100:
        return []

    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', text)
    seen = set()
    results = []

    for sentence in sentences:
        words = re.findall(r"\b[a-zA-Z']+\b", sentence)
        for word in words:
            lw = word.lower()
            if lw not in british_words and (lw, sentence) not in seen:
                seen.add((lw, sentence))
                suggestion = suggest_word(lw)
                results.append({
                    "URL": url,
                    "Misspelled Word": word,
                    "Suggested Correction (British English)": suggestion,
                    "Context": sentence.strip()
                })

    return results

def run_spellcheck_audit():
    urls = extract_urls_from_sitemap(SITEMAP_URL)
    if not urls:
        print("❌ No URLs found.")
        return

    print(f"🔎 Total URLs found: {len(urls)}")

    # Step 1: Fetch content
    texts = []
    skipped = []
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as downloader:
        future_to_url = {downloader.submit(extract_text_from_url, url): url for url in urls}
        for i, future in enumerate(as_completed(future_to_url)):
            url = future_to_url[future]
            try:
                data = future.result()
                texts.append(data)
                print(f"[{i+1}/{len(urls)}] Downloaded: {url}")
            except Exception as e:
                logging.error(f"Download error for {url}: {e}")
                skipped.append(url)

    # Step 2: Spell check using multiprocessing
    report = []
    with ProcessPoolExecutor(max_workers=MAX_PROCESS_WORKERS) as processor:
        futures = processor.map(find_spelling_errors_for_text, texts)
        for errors in futures:
            report.extend(errors)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pd.DataFrame(report).to_csv(f"auraa_spellcheck_report_{timestamp}.csv", index=False)
    pd.DataFrame(skipped, columns=["Skipped URLs"]).to_csv(f"skipped_urls_{timestamp}.csv", index=False)

    print(f"\n✅ Spellcheck complete. Report saved.")

if __name__ == "__main__":
    try:
        run_spellcheck_audit()
    except KeyboardInterrupt:
        print("\n❌ Audit interrupted.")
