"""Build projects (websites, apps, scripts) with the LLM and open them in VS Code."""
import os
import re
import shutil
import subprocess
import time
 
ROOT = os.path.expanduser(os.environ.get("JARVIS_PROJECTS", "~/JarvisProjects"))
PROMPT = (
    "You are an elite front-end engineer and designer. Build this completely, working, with no placeholders:\n{task}\n\n"
    "Output every file in exactly this format and nothing else:\n### FILE: relative/path.ext\n<full file content>\n### END\n"
    "Rules: for websites make ONE index.html with inline CSS and JS, modern polished design, responsive, smooth animations. "
    "For 3D use three.js loaded from https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js (no OrbitControls import). "
    "Stay compact (under about 350 lines total) so it finishes. No explanations outside the files."
)
 
 
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "project"
 
 
def open_in_vscode(path):
    if shutil.which("code"):
        r = subprocess.run(["code", path], capture_output=True, text=True)
    else:
        r = subprocess.run(["open", "-a", "Visual Studio Code", path], capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()
 
 
def build(llm, task, name=None):
    """Returns (ok, message, folder)."""
    raw = llm(PROMPT.format(task=task))
    if not raw:
        return False, "The coding model returned nothing. Is Groq/Ollama reachable?", None
    files = re.findall(r"### FILE:\s*(.+?)\n(.*?)(?=\n### END|\n### FILE:|\Z)", raw, re.S)
    if not files:
        return False, "The model didn't return files in the expected format. Try again.", None
    folder = os.path.join(ROOT, f"{_slug(name or task)}-{time.strftime('%m%d-%H%M')}")
    written = []
    for rel, body in files:
        rel = rel.strip().strip("`")
        if rel.startswith("/") or ".." in rel.split("/"):
            continue
        body = re.sub(r"^```[\w-]*\n|\n```\s*$", "", body.strip("\n"))
        dest = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        written.append(rel)
    if not written:
        return False, "No safe files to write.", None
    ok, err = open_in_vscode(folder)
    return True, f"Created {len(written)} files in {folder}: {', '.join(written)}." + ("" if ok else f" (VS Code didn't open: {err})"), folder
 












































