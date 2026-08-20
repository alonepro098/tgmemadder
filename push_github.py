import os
import base64
import json
import urllib.request
import urllib.error
import sys

# Force UTF-8 encoding for stdout
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = "alonepro098/tgmemadder"

def upload_file(rel_path, token=None):
    token = token or TOKEN or os.environ.get('GITHUB_TOKEN')
    if not token:
        print("[!] GITHUB_TOKEN environment variable required.")
        return False
        
    url = f"https://api.github.com/repos/{REPO}/contents/{rel_path}"
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "Python-Git-Pusher",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        with open(rel_path, 'rb') as f:
            content_bytes = f.read()
    except Exception as e:
        print(f"[-] Cannot read file {rel_path}: {e}")
        return False

    b64_content = base64.b64encode(content_bytes).decode('utf-8')

    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            sha = data.get('sha')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[-] Error checking {rel_path}: {e.code} {e.reason}")

    payload = {
        "message": f"Update {rel_path} - Complete Telegram Bot & Backend",
        "content": b64_content,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    json_data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=json_data, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[+] Successfully pushed {rel_path} to GitHub!")
            return True
    except urllib.error.HTTPError as e:
        print(f"[!] Failed to push {rel_path}: {e.code} - {e.read().decode('utf-8')}")
        return False

def push_all():
    print(f"Pushing all codebase files to https://github.com/{REPO}...")
    token = TOKEN or os.environ.get('GITHUB_TOKEN')
    
    files_to_push = []
    base_dir = os.path.abspath(".")
    for root, dirs, files in os.walk(base_dir):
        if '.git' in root or '__pycache__' in root or 'venv' in root or '.idea' in root:
            continue
        for file in files:
            if file.endswith('.db') or file.endswith('.pyc') or file == 'session.txt' or file.endswith('.zip'):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, base_dir).replace('\\', '/')
            files_to_push.append(rel_path)

    print(f"Found {len(files_to_push)} files to push.")
    
    for f in files_to_push:
        upload_file(f, token)

if __name__ == '__main__':
    push_all()
