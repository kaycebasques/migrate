import time
import os
import sys
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

def get_workspace_dir() -> Path:
    """Returns the workspace directory or exits if not set."""
    workspace_str = os.environ.get('BUILD_WORKSPACE_DIRECTORY')
    if not workspace_str:
        print("Error: BUILD_WORKSPACE_DIRECTORY environment variable not set.")
        print("This script should be run with 'bazel run'.")
        sys.exit(1)
    return Path(workspace_str)

def get_url_paths(file_path: Path) -> list[str]:
    """Reads all lines from a file and returns a list of stripped paths."""
    print(f"Reading {file_path}")
    try:
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: {file_path} not found")
        sys.exit(1)

def check_status(url: str) -> bool:
    """Checks if URL returns 200 OK."""
    print(f"Checking status of {url}")
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Skipping {url} (Status code: {response.status_code})")
            return False
        return True
    except Exception as e:
        print(f"Error checking URL: {e}")
        return False

def capture_screenshot(url: str, output_path: Path):
    """Loads URL in headless Playwright and takes a screenshot."""
    print(f"Loading URL: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url)
            # Wait a few seconds as requested
            time.sleep(5)
            page.screenshot(path=str(output_path))
            print(f"Screenshot saved to {output_path}")
        except Exception as e:
            print(f"Error during navigation or screenshot: {e}")
        finally:
            browser.close()

def main():
    workspace_dir = get_workspace_dir()
    urls_file = workspace_dir / 'urls.txt'
    
    paths = get_url_paths(urls_file)
    
    data_dir = workspace_dir / 'data'
    
    limit = int(os.environ.get('LIMIT_URLS', '0'))
    count = 0
    
    for path in paths:
        url = "https://bazel.build" + path
        
        if not check_status(url):
            continue
            
        # Only create output dir after verifying 200
        rel_path = path.lstrip('/')
        output_dir = data_dir / rel_path
        output_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = output_dir / 'old.png'
        capture_screenshot(url, screenshot_path)
        
        count += 1
        if limit > 0 and count >= limit:
            print(f"Reached limit of {limit} URLs. Stopping.")
            break

if __name__ == "__main__":
    main()
