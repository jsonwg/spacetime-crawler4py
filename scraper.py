import atexit
import json
import os
import re
from collections import Counter
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs
from bs4 import BeautifulSoup

VALID_DOMAINS = {"ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu"}
DOKU_ACTIONS = {"do", "tab_details", "tab_files", "image", "ns"}
IS_DATE = re.compile(r"/day/\d{4}-\d{2}-\d{2}")
IS_WORD = re.compile(r"\b[a-zA-Z][a-zA-Z'-]*\b")
INVALID_FILETYPES = re.compile(
    r".*\.(css|js|bmp|gif|jpe?g|ico"
    + r"|png|tiff?|mid|mp2|mp3|mp4"
    + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
    + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
    + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
    + r"|epub|dll|cnf|tgz|sha1"
    + r"|thmx|mso|arff|rtf|jar|csv"
    + r"|rm|smil|wmv|swf|wma|zip|rar|gz"
    # extra added extensions to filter below
    + r"|can|mpg|mol|sdf|ppsx|apk|smi|svg)$")

SUBDOMAIN_COUNTS_FILE = "subdomains.json"
WORD_COUNTS_FILE = "words.json"
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can't",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from",
    "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've",
    "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of",
    "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd",
    "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
}


subdomain_data = {
    "subdomains": {}, 
    "unique": 0
}

word_data = {
    "freq": Counter(), 
    "longest_page": {
        "url": "", 
        "count": 0
    }
}


def save_subdomain_data():
    with open(SUBDOMAIN_COUNTS_FILE, "w") as f:
        serialized = {
            "subdomains": {sub: list(urls) for sub, urls in subdomain_data["subdomains"].items()},
            "unique": subdomain_data["unique"],
        }
        json.dump(serialized, f)


def save_word_data():
    with open(WORD_COUNTS_FILE, "w") as f:
        json.dump(word_data, f)


def count_words(url, resp, soup):
    content_type = resp.raw_response.headers.get("Content-Type", "").lower()
    if "text/html" not in content_type:
        return
    if INVALID_FILETYPES.match(urlparse(url).path.lower()):
        return

    try:
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True).lower()
        words = [w for w in IS_WORD.findall(text) if w not in STOP_WORDS and len(w) > 1]
        if not words:
            return
        word_data["freq"].update(words)
        if len(words) > word_data["longest_page"]["count"]:
            word_data["longest_page"] = {"url": url, "count": len(words)}
    except Exception as e:
        print(f"Error counting words on {url}", e)


def record_subdomain(url):
    parsed = urlparse(url)
    subdomain = parsed.netloc
    stripped = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    if subdomain not in subdomain_data["subdomains"]:
        subdomain_data["subdomains"][subdomain] = set()
    if stripped not in subdomain_data["subdomains"][subdomain]:
        subdomain_data["subdomains"][subdomain].add(stripped)
        subdomain_data["unique"] += 1


atexit.register(save_subdomain_data)
atexit.register(save_word_data)


def scraper(url, resp):
    if resp.status != 200 or not resp.raw_response:
        return []
    
    try:
        soup = BeautifulSoup(resp.raw_response.content, "html.parser")
        record_subdomain(url)
        count_words(url, resp, soup)
        if subdomain_data["unique"] % 100 == 0:
            save_subdomain_data()
            save_word_data()
        links = extract_next_links(resp, soup)
        return [link for link in links if is_valid(link)]
    except Exception as e:
        print(f"Error scraping {url}", e)
        return []


def extract_next_links(resp, soup):
    links = []
    if resp.status != 200 or not resp.raw_response:
        return links

    try:
        for anchor in soup.find_all("a", href=True):
            link = anchor.get("href")
            full_url = urljoin(resp.url, link)
            final_url = urlunparse(urlparse(full_url)._replace(fragment=''))
            links.append(final_url)
    except Exception as e:
        print("Error parsing page:", e)
    finally:
        return links


def reduce_dale_cooper(netloc, params):
    if "dale-cooper" not in netloc:
        return False
    return bool(params)


def reduce_doku(path, params):
    if "doku.php" not in path:
        return False

    if DOKU_ACTIONS & set(params.keys()):
        return True

    # filter out more paths
    idx_vals = params.get("idx", [])
    if any(":" in val for val in idx_vals):
        return True
    return False

def low_info(path, params):
    # giant chem file
    if "randomsmiles100k" in path:
        return True
    # redundant pages
    if {"C", "O"} & set(params.keys()):
        return True

def temporal_trap(netloc, path_lower, params):
    if "tribe-bar-date" in params:
        return True
    if {"ical", "outlook-ical"} & set(params.keys()):
        return True
    # certain dynamic events pages don't have static param val
    if any(k.startswith("tribe__") for k in params.keys()):
        return False
    if IS_DATE.search(path_lower):
        return True
    if netloc in ["wics.ics.uci.edu", "isg.ics.uci.edu"] and path_lower.startswith("/events"):
        return True
    if netloc == "wics.ics.uci.edu" and path_lower.startswith("/reg"):
        return True
    if netloc == "grape.ics.uci.edu" and ("timeline" in path_lower or "version" in params):
        return True
    return False


def is_valid(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not (parsed.netloc in VALID_DOMAINS or any(parsed.netloc.endswith("." + domain) for domain in VALID_DOMAINS)):
            return False

        normalized_path = parsed.path.lower()
        query_params = parse_qs(parsed.query)

        if INVALID_FILETYPES.match(normalized_path):
            return False
        if "share" in query_params or "redirect_to" in query_params:
            return False
        if reduce_dale_cooper(parsed.netloc, query_params):
            return False
        if reduce_doku(normalized_path, query_params):
            return False
        if temporal_trap(parsed.netloc, normalized_path, query_params):
            return False
        if low_info(normalized_path, query_params):
            return False

        return True

    except TypeError:
        print("TypeError for ", parsed)
        raise
