import os
import sys
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
import json

workspace_dir = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
if workspace_dir:
    config_path = os.path.join(workspace_dir, "config.json")
else:
    config_path = "config.json"

try:
    with open(config_path, "r") as f:
        config = json.load(f)
except FileNotFoundError:
    config = {}

OLD_URL = config.get("OLD_URL", "https://bazel.build")
NEW_URL = config.get("NEW_URL", "https://preview.bazel.build")
OLD_SELECTOR = config.get("OLD_SELECTOR", "article.devsite-article")
NEW_SELECTOR = config.get("NEW_SELECTOR", "#content-area")

def main():
    workspace_dir = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace_dir:
        print("BUILD_WORKSPACE_DIRECTORY not set. Run with 'bazel run'", file=sys.stderr)
        sys.exit(1)
        
    data_dir = os.path.join(workspace_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    todo_file = os.path.join(data_dir, "TODO")
    done_file = os.path.join(data_dir, "DONE")
    error_file = os.path.join(data_dir, "ERROR")
    
    if not os.path.exists(todo_file) and not os.path.exists(done_file) and not os.path.exists(error_file):
        with open(todo_file, "w") as f:
            f.write("")
            
    failed_paths = []
    
    while True:
        undone_pages = []
        find_undone_pages(data_dir, data_dir, undone_pages)
        
        if not undone_pages:
            break
            
        for dir_path in undone_pages:
            url = path_to_url(dir_path, data_dir)
            process_page(dir_path, url, data_dir, failed_paths)
            
    if failed_paths:
        print("Failed paths:")
        for path in failed_paths:
            print(f"  {path}")

def find_undone_pages(current_dir, data_dir, results):
    for entry in os.scandir(current_dir):
        if entry.is_dir():
            find_undone_pages(entry.path, data_dir, results)
        elif entry.is_file() and entry.name == "TODO":
            results.append(current_dir)

def path_to_url(path, data_dir):
    rel_path = os.path.relpath(path, data_dir)
    if rel_path == ".":
        return OLD_URL
    else:
        return f"{OLD_URL}/{rel_path}"

def extract_links(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        url = urljoin(base_url, href)
        # Remove fragment
        parsed = urlparse(url)
        url_no_frag = parsed._replace(fragment="").geturl()
        
        # Normalize index.html
        if url_no_frag.endswith("/index.html"):
            url_no_frag = url_no_frag[:-10]
            
        links.append(url_no_frag)
    return links

def should_process_link(url_str):
    try:
        url = urlparse(url_str)
        base = urlparse(OLD_URL)
        
        if url_str == OLD_URL or url_str == OLD_URL + "/":
            return False
            
        if url.netloc != base.netloc:
            return False
            
        return True
    except Exception:
        return False

def queue_link(link, data_dir):
    url = urlparse(link)
    path = url.path
    rel_link_path = path.lstrip('/')
    target_dir = os.path.join(data_dir, rel_link_path)
    
    todo_file = os.path.join(target_dir, "TODO")
    done_file = os.path.join(target_dir, "DONE")
    error_file = os.path.join(target_dir, "ERROR")
    
    if not os.path.exists(todo_file) and not os.path.exists(done_file) and not os.path.exists(error_file):
        os.makedirs(target_dir, exist_ok=True)
        with open(todo_file, "w") as f:
            f.write("")

# TODO when constructing data dir we should still note the original url
# that exists on the page, even if it redirects. maybe we can add a REDIRECT
# file to indicate this situation.


def fetch_url(url, ignore_errors=False):
    try:
        return requests.get(url)
    except Exception as e:
        if not ignore_errors:
            print(f"Failed to fetch '{url}': {e}", file=sys.stderr)
        return None


def extract_and_save_element(html, selector, output_path):
    soup = BeautifulSoup(html, 'html.parser')
    element = soup.select_one(selector)
    if element:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(str(element))
        return True
    return False


def update_page_state(dir_path, add_state, remove_state=None):
    if remove_state:
        remove_file = os.path.join(dir_path, remove_state)
        if os.path.exists(remove_file):
            os.remove(remove_file)
            
    with open(os.path.join(dir_path, add_state), "w") as f:
        f.write("")


def handle_successful_fetch(dir_path, url, new_url, resp, new_resp, data_dir, failed_paths):
    html = resp.text
    extract_and_save_element(html, OLD_SELECTOR, os.path.join(dir_path, "old.html"))
    
    new_status = str(new_resp.status_code) if new_resp else "Error"
    
    if new_status == "200":
        update_page_state(dir_path, "PASS")
        extract_and_save_element(new_resp.text, NEW_SELECTOR, os.path.join(dir_path, "new.html"))
    else:
        update_page_state(dir_path, "FAIL")
        rel_path = os.path.relpath(dir_path, data_dir)
        print(f"FAIL:\n  Old URL: {url}\n  New URL: {new_url}\n  Status: {new_status}", file=sys.stderr)
        failed_paths.append(rel_path)
        
    links = extract_links(html, resp.url)
    
    for link in links:
        if should_process_link(link):
            queue_link(link, data_dir)
            
    update_page_state(dir_path, "DONE", remove_state="TODO")


def process_page(dir_path, url, data_dir, failed_paths):
    print(f"Processing {url}...")
    try:
        resp = fetch_url(url)
        if not resp:
            update_page_state(dir_path, "ERROR", remove_state="TODO")
            return
            
        status = str(resp.status_code)
        new_url = url.replace(OLD_URL, NEW_URL)
        new_resp = fetch_url(new_url, ignore_errors=True)
        
        if status == "200":
            handle_successful_fetch(dir_path, url, new_url, resp, new_resp, data_dir, failed_paths)
        else:
            print(f"Non-200 status for {url}: {status}", file=sys.stderr)
            update_page_state(dir_path, "ERROR", remove_state="TODO")
            
    except Exception as e:
        print(f"Failed to process '{url}': {e}", file=sys.stderr)
        update_page_state(dir_path, "ERROR", remove_state="TODO")

if __name__ == "__main__":
    main()
