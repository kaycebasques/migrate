import time
import os
import sys
import json
import subprocess
from pathlib import Path
import requests
import dotenv
from typing import TypedDict
from google import genai
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

def capture_screenshot(url: str, output_path: Path, delete_selectors: list[str] = None):
    """Loads URL in headless Playwright and takes a screenshot."""
    print(f"Loading URL for screenshot: {url}")
    if delete_selectors is None:
        delete_selectors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url)
            # Wait a few seconds as requested
            time.sleep(5)
            
            # Delete elements as requested
            for selector in delete_selectors:
                print(f"Deleting elements matching: {selector}")
                try:
                    page.evaluate(
                        "selector => { document.querySelectorAll(selector).forEach(e => e.remove()) }",
                        selector
                    )
                except Exception as e:
                    print(f"Error deleting {selector}: {e}")
                    
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
    config_file = workspace_dir / 'config.json'
    
    # Load .env
    if env_file.exists():
        print(f"Loading .env from {env_file}")
        dotenv.load_dotenv(dotenv_path=env_file)
    else:
        print(f"Warning: .env file not found at {env_file}")
        
    paths = get_url_paths(urls_file)
    prompt = get_prompt(prompt_file)
    
    # Load config.json
    config = {}
    if config_file.exists():
        print(f"Loading config from {config_file}")
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    else:
        print(f"Warning: config.json not found at {config_file}")
    
    old_base_url = config.get('old', {}).get('base_url', 'https://bazel.build')
    new_base_url = config.get('new', {}).get('base_url', 'https://preview.bazel.build')
    
    data_dir = workspace_dir / 'data'
    
    # Initialize Gemini Client
    # It will automatically pick up GEMINI_API_KEY from environment
    client = genai.Client()
    
    for path in paths:
        rel_path = path.lstrip('/')
        output_dir = data_dir / rel_path
        
        if output_dir.exists():
            if (output_dir / 'ERROR').exists():
                print(f"Skipping {path} (Already done with error)")
                continue
            if (output_dir / 'NOT_OK').exists():
                print(f"Skipping {path} (Already NOT_OK)")
                continue
            if (output_dir / 'old.png').exists() and (output_dir / 'new.png').exists() and (output_dir / 'diff.json').exists():
                print(f"Skipping {path} (Already done)")
                continue
                
        old_url = old_base_url + path
        new_url = new_base_url + path
        
        if not check_status(old_url):
            print(f"Skipping {path} (Old site not 200)")
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / 'NOT_OK').touch()
            continue
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        screenshot_path_old = output_dir / 'old.png'
        capture_screenshot(old_url, screenshot_path_old, config.get('old', {}).get('delete', []))
        
        new_site_valid = check_status(new_url)
        screenshot_path_new = None
        
        if new_site_valid:
            screenshot_path_new = output_dir / 'new.png'
            capture_screenshot(new_url, screenshot_path_new, config.get('new', {}).get('delete', []))
        else:
            log_error(workspace_dir, path)
            error_file = output_dir / 'ERROR'
            print(f"Touching error file: {error_file}")
            error_file.touch()
            
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
                class Response(TypedDict):
                    issues: list[str]

                gemini_config = genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Response
                )

                response = client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=[file_old, file_new, prompt],
                    config=gemini_config
                )
                
                print(f"--- Gemini Response for {path} ---")
                print(response.parsed['issues'])
                print("----------------------------------")
                
                diff_json_path = output_dir / 'diff.json'
                print(f"Saving analysis to {diff_json_path}")
                with open(diff_json_path, 'w') as f:
                    json.dump(response.parsed, f, indent=2)
                
            except Exception as e:
                print(f"Error during Gemini analysis: {e}")
        else:
            print(f"Skipping analysis for {path} (Missing one or both screenshots)")
            
        # Commit changes for this path
        print(f"Committing changes for {path}")
        subprocess.run(["git", "add", str(output_dir)], cwd=workspace_dir)
        result = subprocess.run(["git", "commit", "-m", path], capture_output=True, text=True, cwd=workspace_dir)
        if result.returncode != 0:
            print(f"Git commit for {path} result: {result.stdout.strip() or result.stderr.strip()}")
        result = subprocess.run(["git", "push"], capture_output=True, text=True, cwd=workspace_dir)

if __name__ == "__main__":
    main()
