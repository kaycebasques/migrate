import time
import os
import sys
from pathlib import Path
import requests
import dotenv
from google import genai
from playwright.sync_api import sync_playwright

OLD_BASE_URL = "https://bazel.build"
NEW_BASE_URL = "https://preview.bazel.build"

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

def get_prompt(prompt_file: Path) -> str:
    """Reads the prompt from a file."""
    print(f"Reading prompt from {prompt_file}")
    try:
        with open(prompt_file, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: {prompt_file} not found")
        sys.exit(1)

def check_status(url: str) -> bool:
    """Checks if URL returns 200 OK."""
    print(f"Checking status of {url}")
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Status code: {response.status_code}")
            return False
        return True
    except Exception as e:
        print(f"Error checking URL: {e}")
        return False

def capture_screenshot(url: str, output_path: Path):
    """Loads URL in headless Playwright and takes a screenshot."""
    print(f"Loading URL for screenshot: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url)
            # Wait a few seconds as requested
            time.sleep(5)
            page.screenshot(path=str(output_path), full_page=True)
            print(f"Screenshot saved to {output_path}")
        except Exception as e:
            print(f"Error during navigation or screenshot: {e}")
        finally:
            browser.close()

def log_error(workspace_dir: Path, path: str):
    """Logs a path to errors.txt if not already present."""
    errors_file = workspace_dir / 'errors.txt'
    
    existing_errors = set()
    if errors_file.exists():
        with open(errors_file, 'r') as f:
            existing_errors = {line.strip() for line in f}
            
    if path not in existing_errors:
        print(f"Logging error for path: {path}")
        with open(errors_file, 'a') as f:
            f.write(path + '\n')
    else:
        print(f"Path {path} already in errors.txt")

def main():
    workspace_dir = get_workspace_dir()
    urls_file = workspace_dir / 'urls.txt'
    prompt_file = workspace_dir / 'prompt.txt'
    env_file = workspace_dir / '.env'
    
    # Load .env
    if env_file.exists():
        print(f"Loading .env from {env_file}")
        dotenv.load_dotenv(dotenv_path=env_file)
    else:
        print(f"Warning: .env file not found at {env_file}")
        
    paths = get_url_paths(urls_file)
    prompt = get_prompt(prompt_file)
    
    data_dir = workspace_dir / 'data'
    
    # Initialize Gemini Client
    # It will automatically pick up GEMINI_API_KEY from environment
    client = genai.Client()
    
    test_paths = paths[10:20]
    print(f"Testing first 3 paths: {test_paths}")
    
    for path in test_paths:
        old_url = OLD_BASE_URL + path
        new_url = NEW_BASE_URL + path
        
        if not check_status(old_url):
            print(f"Skipping {path} (Old site not 200)")
            continue
            
        rel_path = path.lstrip('/')
        output_dir = data_dir / rel_path
        output_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path_old = output_dir / 'old.png'
        capture_screenshot(old_url, screenshot_path_old)
        
        new_site_valid = check_status(new_url)
        screenshot_path_new = None
        
        if new_site_valid:
            screenshot_path_new = output_dir / 'new.png'
            capture_screenshot(new_url, screenshot_path_new)
        else:
            log_error(workspace_dir, path)
            
        # If both screenshots exist, run Gemini analysis
        if screenshot_path_old.exists() and screenshot_path_new and screenshot_path_new.exists():
            print(f"Analyzing discrepancies for {path}")
            try:
                # Upload files
                print(f"Uploading {screenshot_path_old}")
                file_old = client.files.upload(file=str(screenshot_path_old))
                print(f"Uploading {screenshot_path_new}")
                file_new = client.files.upload(file=str(screenshot_path_new))
                
                # Generate content
                print("Generating content from Gemini...")
                response = client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=[file_old, file_new, prompt],
                )
                
                print(f"--- Gemini Response for {path} ---")
                print(response.text)
                print("----------------------------------")
                
            except Exception as e:
                print(f"Error during Gemini analysis: {e}")
        else:
            print(f"Skipping analysis for {path} (Missing one or both screenshots)")

if __name__ == "__main__":
    main()
