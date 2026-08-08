from webview import window
import os
import socket
import sys
import threading
import time

import webview

from app_config import APP_WINDOW_TITLE, LOGO_ICON_FILE
from logdata import get_app_dir, logger

HOST = "127.0.0.1"
PORT = 8000
LOGIN_URL = f"http://{HOST}:{PORT}/login"
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"

WINDOW_WIDTH = 1366
WINDOW_HEIGHT = 820

SPLASH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Starting…</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: linear-gradient(145deg, #0f766e 0%, #134e4a 50%, #1e293b 100%);
    color: #f8fafc;
  }
  .card {
    text-align: center;
    padding: 2.5rem 3rem;
    border-radius: 20px;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    backdrop-filter: blur(12px);
    max-width: 420px;
    width: 90%;
  }
  .spinner {
    width: 56px;
    height: 56px;
    margin: 0 auto 1.25rem;
    border: 4px solid rgba(255,255,255,0.2);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.85s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  h1 { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; }
  p { font-size: 0.9rem; color: #cbd5e1; line-height: 1.5; }
  .sub { margin-top: 1rem; font-size: 0.75rem; color: #94a3b8; }
</style>
</head>
<body>
  <div class="card">
    <div class="spinner" aria-hidden="true"></div>
    <h1>GMMMC Pathology Lab</h1>
    <p>Starting application…<br>Please wait a moment.</p>
    <p class="sub">Pathology Lab of GMMMC Sukkur</p>
  </div>
</body>
</html>"""


def _resolve_icon_path() -> str | None:
    base_dir = get_app_dir()
    ico = os.path.join(base_dir, LOGO_ICON_FILE)
    if os.path.exists(ico):
        return ico
    for rel in ("static/images/hospital_logo.png", "hospital_logo.png"):
        png = os.path.join(base_dir, rel.replace("/", os.sep))
        if os.path.exists(png):
            return png
    return None


def _window_position() -> tuple[int, int]:
    """Center the window on the primary display (fixes bottom-left / off-screen startup)."""
    try:
        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            x = max(0, (sw - WINDOW_WIDTH) // 2)
            y = max(0, (sh - WINDOW_HEIGHT) // 2)
            return x, y
    except Exception:
        pass
    return 80, 80


def _wait_for_server(timeout_s: float = 45.0) -> bool:
    """Poll lightweight health endpoint until the app is ready."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=0.4) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.12)
    return False


def _is_server_running() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _run_server() -> None:
    # Lazy import keeps splash visible sooner (heavy modules load in background).
    import uvicorn

    from main import app

    logger.info("Starting Uvicorn server for desktop window...")
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )


def _open_app(window) -> None:
    if _wait_for_server():
        logger.info("Server ready — loading login page")
        window.load_url(LOGIN_URL)
    else:
        logger.error("Server did not start in time")
        window.load_url(LOGIN_URL)


if __name__ == "__main__":
    pos_x, pos_y = _window_position()
    icon_path = _resolve_icon_path()

    if not _is_server_running():
        server_thread = threading.Thread(target=_run_server, daemon=True)
        server_thread.start()
    else:
        logger.info("Server is already running on %s:%s — attaching desktop window.", HOST, PORT)

    window = webview.create_window(
        title=APP_WINDOW_TITLE,
        html=SPLASH_HTML,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        x=pos_x,
        y=pos_y,
        min_size=(1024, 700),
        resizable=True,
        text_select=True,   # Allow users to select and copy text
        easy_drag=False,    # Prevent drag-to-move from blocking text selection
    )

    logger.info("Launching desktop window (splash) at %s,%s", pos_x, pos_y)
    webview.start(lambda: _open_app(window), icon=icon_path, user_agent="LabFlowDesktopApp/1.0")

