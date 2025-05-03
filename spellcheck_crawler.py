# 🔍 Project: SpellSentinel - British English Web Spell Checker

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import pandas as pd
from spellchecker import SpellChecker
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(filename='crawler.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize British English spell checker
spell = SpellChecker(language='en')

try:
    spell.word_frequency.load_text_file('en_GB-large.dic')  # Load custom British English dictionary
    logging.info("Custom British English dictionary loaded successfully.")
except FileNotFoundError:
    logging.warning("Custom dictionary 'en_GB-large.dic' not found. Using default dictionary.")
    print("⚠️ Warning: Custom dictionary 'en_GB-large.dic' not found. Using default dictionary.")

# Config
BASE_URL = "https://auraadesign.co.uk"
SITEMAP_URL = urljoin(BASE_URL, "/sitemap_index.xml")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SpellSentinelBot/1.0)"}
MAX_WORKERS = 10
RETRY_LIMIT = 3
TIMEOUT = 15

# Whitelist of custom terms (brand names, etc.)
CUSTOM_IGNORE = {"auraa", "auraadesign", "luxury", "wallart", "faux"}
CUSTOM_IGNORE = {word for word in CUSTOM_IGNORE if word.isalpha()}

# Step 1: Parse sitemap and extract all URLs
def extract_urls_from_sitemap(sitemap_url):
    urls = []
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            logging.warning(f"Failed to fetch sitemap: {sitemap_url}")
            return urls

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            logging.error(f"XML parsing error for sitemap {sitemap_url}: {e}")
            return urls

        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        for sitemap in root.findall("ns:sitemap", namespace):
            loc = sitemap.find("ns:loc", namespace).text
            urls.extend(extract_urls_from_sitemap(loc))

        for url in root.findall("ns:url", namespace):
            loc = url.find("ns:loc", namespace)
            if loc is not None:
                urls.append(loc.text)
    except Exception as e:
        logging.error(f"Error parsing sitemap {sitemap_url}: {e}")
    return urls

# Step 2: Clean and extract visible text from HTML
def extract_text_from_url(url):
    for attempt in range(RETRY_LIMIT):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                logging.warning(f"Non-200 status code {resp.status_code} for {url}")
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            text = soup.get_text(separator=' ')
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1}: Failed to fetch {url} - {e}")
            time.sleep(1)
    logging.error(f"Failed to fetch {url} after {RETRY_LIMIT} attempts.")
    return ""

# Step 3: Spell check the text with context
def find_spelling_errors(text):
    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', text)
    errors = []
    seen = set()

    for sentence in sentences:
        words = re.findall(r"\b[a-zA-Z\']+\b", sentence)
        misspelled = spell.unknown(words) - CUSTOM_IGNORE

        for word in misspelled:
            if (word, sentence) not in seen:
                seen.add((word, sentence))
                correction = spell.correction(word)
                errors.append((word, correction, sentence.strip()))

    return errors

# Step 4: Process a single URL
def process_url(url):
    logging.debug(f"Processing URL: {url}")
    text = extract_text_from_url(url)
    logging.debug(f"Extracted text length: {len(text)}")
    if not text:
        return []
    errors = find_spelling_errors(text)
    logging.debug(f"Found {len(errors)} spelling errors in {url}")
    results = []
    for word, correction, context in errors:
        results.append({
            "URL": url,
            "Misspelled Word": word,
            "Suggested Correction (British English)": correction,
            "Context": context
        })
    return results

# Step 5: Run the audit with concurrency
def run_spellcheck_audit():
    logging.info("Starting spellcheck audit.")
    urls = extract_urls_from_sitemap(SITEMAP_URL)
    if not urls:
        logging.error("No URLs found in the sitemap. Exiting.")
        print("❌ No URLs found in the sitemap. Exiting.")
        return
    logging.info(f"Total URLs found: {len(urls)}")

    report = []
    skipped = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_url, url): url for url in urls}
        for i, future in enumerate(as_completed(futures)):
            url = futures[future]
            try:
                result = future.result(timeout=TIMEOUT)
                report.extend(result)
                print(f"[{i+1}/{len(urls)}] Audited {url} ✅")
            except TimeoutError:
                logging.error(f"Timeout processing {url}")
                skipped.append(url)
            except Exception as e:
                logging.error(f"Error processing {url}: {e}")
                skipped.append(url)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"auraa_spellcheck_report_{timestamp}.csv"
    skipped_filename = f"skipped_urls_{timestamp}.csv"

    pd.DataFrame(report).to_csv(report_filename, index=False)
    pd.DataFrame(skipped, columns=["Skipped URLs"]).to_csv(skipped_filename, index=False)
    print(f"\n✅ Spellcheck audit complete.")
    print(f"📄 Report saved: {report_filename}")
    print(f"⚠️ Skipped URLs saved: {skipped_filename}")

if __name__ == "__main__":
    try:
        run_spellcheck_audit()
    except KeyboardInterrupt:
        logging.warning("Spellcheck audit interrupted by user.")
        print("\n❌ Spellcheck audit interrupted.")
