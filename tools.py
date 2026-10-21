import os
import re
import shutil
import subprocess
import webbrowser
from difflib import get_close_matches
from pathlib import Path
from datetime import datetime
import requests

# Friendly-name shortcuts that never need a filesystem search - fast path.
SAFE_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "explorer": "explorer.exe",
    "powerpoint": "POWERPNT.EXE",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "outlook": "OUTLOOK.EXE",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "vscode": "Code.exe",
    "code": "Code.exe",
}


def _list_installed_apps():
    """
    Reads the same list Windows itself uses for Settings > Apps and
    Control Panel > Programs and Features - the Uninstall registry keys.
    This is the real, definitive list of everything installed on the
    machine (name, install folder, and icon/exe path), so NOVA can find
    an app the same way Windows does instead of guessing exe names.
    Returns a dict: {display_name_lower: {"name":, "install_location":, "icon":}}
    """
    try:
        import winreg
    except ImportError:
        return {}

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    apps = {}
    for hive, path in roots:
        try:
            root_key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        try:
            count = winreg.QueryInfoKey(root_key)[0]
            for i in range(count):
                try:
                    sub_name = winreg.EnumKey(root_key, i)
                    with winreg.OpenKey(root_key, sub_name) as sub_key:
                        try:
                            display_name = winreg.QueryValueEx(sub_key, "DisplayName")[0]
                        except FileNotFoundError:
                            continue
                        if not display_name:
                            continue
                        entry = {"name": display_name, "install_location": None, "icon": None}
                        try:
                            entry["install_location"] = winreg.QueryValueEx(sub_key, "InstallLocation")[0]
                        except FileNotFoundError:
                            pass
                        try:
                            entry["icon"] = winreg.QueryValueEx(sub_key, "DisplayIcon")[0]
                        except FileNotFoundError:
                            pass
                        apps[display_name.lower()] = entry
                except OSError:
                    continue
        finally:
            root_key.Close()
    return apps


def _resolve_from_installed_apps(name):
    """Fuzzy-match `name` against the real Windows installed-apps list and
    try to find a launchable .exe for the best match."""
    apps = _list_installed_apps()
    if not apps:
        return None, None

    name_lower = name.lower()
    match_key = None

    # Exact or substring match first (most reliable).
    for key in apps:
        if key == name_lower or name_lower in key or key in name_lower:
            match_key = key
            break

    # Fall back to fuzzy matching for typos / partial names.
    if not match_key:
        close = get_close_matches(name_lower, apps.keys(), n=1, cutoff=0.6)
        if close:
            match_key = close[0]

    if not match_key:
        return None, None

    entry = apps[match_key]

    # DisplayIcon often points straight at the exe, sometimes with an
    # icon-index suffix like "C:\...\app.exe,0" - strip that off.
    if entry["icon"]:
        icon_path = re.sub(r",-?\d+$", "", entry["icon"]).strip('"')
        if icon_path.lower().endswith(".exe") and os.path.exists(icon_path):
            return icon_path, entry["name"]

    # Otherwise, search the install folder itself for the most likely exe.
    if entry["install_location"] and os.path.isdir(entry["install_location"]):
        for dirpath, _dirs, files in os.walk(entry["install_location"]):
            for f in files:
                if f.lower().endswith(".exe"):
                    return os.path.join(dirpath, f), entry["name"]

    return None, entry["name"]


def system_info():
    import platform
    import psutil
    return {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def list_directory(path):
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        return f"Directory not found: {p}"
    items = []
    for x in sorted(p.iterdir(), key=lambda q: (not q.is_dir(), q.name.lower()))[:80]:
        items.append(("[DIR] " if x.is_dir() else "      ") + x.name)
    return "\n".join(items) if items else "(empty)"


def _find_shortcut(name, extra_roots=()):
    """Search Start Menu (user + system) and Desktop (user + public) for a
    shortcut (.lnk) whose filename contains `name`."""
    name_lower = name.lower()
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
        *extra_roots,
    ]
    best_match = None
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".lnk") and name_lower in f.lower():
                    if f[:-4].lower() == name_lower:
                        return os.path.join(dirpath, f)
                    if best_match is None:
                        best_match = os.path.join(dirpath, f)
    return best_match


def _find_registry_app_path(name):
    """Windows resolves many named programs (e.g. 'chrome', 'firefox') via
    the App Paths registry key - this is the same mechanism Win+R / the
    Windows Run box uses, so checking it covers apps that don't show up
    as Start Menu shortcuts at all."""
    try:
        import winreg
    except ImportError:
        return None  # not on Windows

    exe_name = name if name.lower().endswith(".exe") else name + ".exe"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths\{}".format(exe_name)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value and os.path.exists(value):
                    return value
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return None


def _find_in_install_dirs(name):
    """Shallow search of the common install locations for an .exe whose
    filename contains `name`. Depth-limited so it stays fast instead of
    scanning the whole drive."""
    name_lower = name.lower()
    roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, _dirs, files in os.walk(root):
            # Stop descending more than 3 levels deep under each root.
            if dirpath.rstrip("\\/").count(os.sep) - base_depth > 3:
                _dirs[:] = []
                continue
            for f in files:
                if f.lower().endswith(".exe") and name_lower in f.lower():
                    return os.path.join(dirpath, f)
    return None


def open_application(name):
    """
    Opens ANY installed application by name - not limited to a fixed list.
    Resolution order:
      1. Windows' own installed-apps list (Settings > Apps registry data) -
         fuzzy-matched against what you typed, using its real exe path
      2. A known friendly name in SAFE_APPS, resolved via PATH or registry
      3. The typed name itself, resolved via PATH or registry
      4. A matching Start Menu or Desktop shortcut
      5. A shallow search of Program Files / Program Files (x86) / the
         user's LOCALAPPDATA\\Programs folder
    """
    key = (name or "").strip()
    if not key:
        return "No application name given."
    lower = key.lower()

    # 1. Ask Windows itself: is this in the real installed-apps list?
    errors_seed = []
    exe_from_apps, matched_name = _resolve_from_installed_apps(key)
    if exe_from_apps:
        try:
            subprocess.Popen([exe_from_apps], shell=False)
            return f"Opened {matched_name}."
        except Exception as e:
            errors_seed.append(f"installed-apps match '{exe_from_apps}': {e}")

    candidates = [key]
    if lower in SAFE_APPS and SAFE_APPS[lower] not in candidates:
        candidates.insert(0, SAFE_APPS[lower])

    errors = list(errors_seed)
    for candidate in candidates:
        exe = shutil.which(candidate) or shutil.which(
            candidate if candidate.lower().endswith(".exe") else candidate + ".exe"
        )
        if exe:
            try:
                subprocess.Popen([exe], shell=False)
                return f"Opened {exe}."
            except Exception as e:
                errors.append(f"PATH match '{exe}': {e}")

        reg_path = _find_registry_app_path(candidate)
        if reg_path:
            try:
                subprocess.Popen([reg_path], shell=False)
                return f"Opened {reg_path}."
            except Exception as e:
                errors.append(f"registry match '{reg_path}': {e}")

    shortcut = _find_shortcut(key)
    if shortcut:
        try:
            os.startfile(shortcut)
            return f"Opened {key} via shortcut."
        except Exception as e:
            errors.append(f"shortcut '{shortcut}': {e}")

    exe_path = _find_in_install_dirs(key)
    if exe_path:
        try:
            subprocess.Popen([exe_path], shell=False)
            return f"Opened {exe_path}."
        except Exception as e:
            errors.append(f"install-dir match '{exe_path}': {e}")

    if errors:
        return f"Found '{key}' but every launch attempt failed: {'; '.join(errors)}"
    return (
        f"Couldn't find an installed application matching '{key}'. "
        "Try the exact name shown in its Start Menu entry."
    )


def open_url(url):
    if not (url.startswith("https://") or url.startswith("http://")):
        return "Only http:// and https:// URLs are allowed."
    webbrowser.open(url)
    return f"Opened {url}"


def web_search(query, max_results=5):
    """
    Live web search (no API key required) via DuckDuckGo's HTML endpoint.
    This is what lets NOVA "go online" for current information instead of
    only using what the local model already knows.
    """
    query = (query or "").strip()
    if not query:
        return "No search query provided."

    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; NOVA-Assistant/1.0)"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        return f"Web search failed: {e}"

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        return f"Web search failed while parsing results: {e}"

    results = []
    for block in soup.select(".result__body")[:max_results]:
        link = block.select_one(".result__a")
        snippet = block.select_one(".result__snippet")
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link.get("href", "")
        text = snippet.get_text(strip=True) if snippet else ""
        results.append(f"- {title}\n  {href}\n  {text}")

    if not results:
        return f"No web results found for '{query}'."

    return f"Web search results for '{query}':\n" + "\n".join(results)


def take_screenshot(output="nova_screenshot.png"):
    from PIL import ImageGrab
    image = ImageGrab.grab()
    image.save(output)
    return f"Screenshot saved to {output}"


def _parse_remember(argument):
    """
    Accepts:
        "User likes Python"
        "User likes Python | 8"
        "User likes Python | 8 | preference"
    Returns (content, importance, memory_type).
    """
    parts = [p.strip() for p in (argument or "").split("|")]
    content = parts[0] if parts else ""
    importance = 5
    memory_type = "fact"
    if len(parts) > 1 and parts[1]:
        try:
            importance = max(1, min(10, int(parts[1])))
        except ValueError:
            pass
    if len(parts) > 2 and parts[2]:
        memory_type = parts[2].lower()
    return content, importance, memory_type


def new_office_document(app_name):
    """
    Actually opens a brand-new blank document *inside* an Office app via
    COM automation - not just launching the exe. This is what lets NOVA
    do "open a blank presentation" rather than just "open PowerPoint".
    Requires pywin32 (pip install pywin32) and a real Office install.
    """
    app_name = (app_name or "").strip().lower()
    com_targets = {
        "powerpoint": ("PowerPoint.Application", "Presentations"),
        "word": ("Word.Application", "Documents"),
        "excel": ("Excel.Application", "Workbooks"),
    }
    if app_name not in com_targets:
        return f"'{app_name}' isn't a supported Office app (use powerpoint, word, or excel)."

    prog_id, collection_name = com_targets[app_name]
    try:
        import win32com.client
    except ImportError:
        return (
            "pywin32 isn't installed, so NOVA can't control Office directly. "
            "Run: pip install pywin32 (then restart NOVA)."
        )

    try:
        app = win32com.client.Dispatch(prog_id)
        app.Visible = True
        collection = getattr(app, collection_name)
        collection.Add()
        return f"Created a new blank {app_name} document and brought it to the front."
    except Exception as e:
        return f"Couldn't create a new {app_name} document: {e}"


def _run(name, argument, db):
    """Execute a tool. Returns (result_text, status)."""
    if name == "system_info":
        return str(system_info()), "success"

    if name == "list_directory":
        return list_directory(argument or "."), "success"

    if name == "open_application":
        out = open_application(argument)
        return out, "success" if out.startswith("Opened") else "blocked"

    if name == "new_document":
        out = new_office_document(argument)
        status = "success" if out.startswith("Created") else "error"
        return out, status

    if name == "open_url":
        out = open_url(argument)
        return out, "success" if out.startswith("Opened") else "blocked"

    if name == "screenshot":
        return take_screenshot(), "success"

    if name == "web_search":
        query = (argument or "").strip()
        if not query:
            return "No search query provided.", "error"
        result = web_search(query)
        status = "success" if not result.startswith("Web search failed") else "error"
        return result, status

    if name == "remember":
        content, importance, memory_type = _parse_remember(argument)
        if not content:
            return "Nothing to remember.", "error"
        mem_id = db.add_memory(content, memory_type=memory_type, importance=importance)
        return (
            f"Memory #{mem_id} saved "
            f"(type={memory_type}, importance={importance}): {content}",
            "success",
        )

    if name == "recall":
        keyword = (argument or "").strip()
        if keyword:
            hits = db.search_messages(keyword, limit=10)
            if not hits:
                return f"Nothing found for '{keyword}'.", "success"
            return "\n".join(
                f"[{h['role']}] {h['content'][:160]}" for h in hits
            ), "success"
        mems = db.memories_detailed(15)
        if not mems:
            return "No memories stored yet.", "success"
        return "\n".join(
            f"#{m['id']} ({m['memory_type']}, imp {m['importance']}) {m['content']}"
            for m in mems
        ), "success"

    if name == "db_stats":
        s = db.stats()
        return (
            f"conversations={s['conversations']}  messages={s['messages']}  "
            f"memories={s['memories']}  tasks={s['tasks']}  tool_logs={s['tool_logs']}",
            "success",
        )

    return f"Unknown tool: {name}", "error"


def execute_tool(name, argument, db):
    """
    Runs the tool, records it in tasks + tool_logs, and returns the result text.
    Every call is visible in MySQL Workbench afterwards.
    """
    task_id = None
    try:
        task_id = db.add_task(f"tool:{name}", status="running")
    except Exception:
        pass

    try:
        result, status = _run(name, argument, db)
    except Exception as e:
        result, status = f"Tool '{name}' failed: {e}", "error"

    try:
        db.log_tool(name, argument, result, status=status)
    except Exception:
        pass

    if task_id is not None:
        try:
            db.update_task(
                task_id,
                "done" if status == "success" else "failed",
                result[:2000],
            )
        except Exception:
            pass

    return result


def log_blocked_tool(name, argument, db, reason="Blocked by SAFE MODE."):
    """Record a tool the app refused to run, so the audit trail stays complete."""
    try:
        db.log_tool(name, argument, reason, status="blocked")
    except Exception:
        pass
    return reason