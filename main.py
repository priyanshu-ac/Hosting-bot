import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta, timezone
# Removed unused telegram.* imports as we are using telebot consistently
# from telegram import Update
# from telegram.ext import Updater, CommandHandler, CallbackContext
import psutil
import sqlite3
import json # Kept in case needed elsewhere, but not used in provided logic
import logging # Kept in case needed elsewhere
import signal # Kept in case needed elsewhere
import threading
import re # Added for regex matching in auto-install
import sys # Added for sys.executable
import atexit
import requests # For polling exceptions
import ast, hashlib, importlib.util # smart dependency scan
import base64, io
from types import SimpleNamespace as _NS

# --- Flask Keep Alive ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'am Kelly File Host"

def run_flask():
  # Make sure to run on port provided by environment or default to 8080
  port = int(os.environ.get("PORT", 8080))
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True # Allows program to exit even if this thread is running
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration ---
TOKEN = os.environ.get('BOT_TOKEN', '9172290267:AAHohaifu-OX1FHOqY1aBlPSiS1Uo-7343Q')  # set BOT_TOKEN as an environment variable (never write the token in code)
OWNER_ID = int(os.environ.get('OWNER_ID', 6506909666))
ADMIN_ID = int(os.environ.get('ADMIN_ID', 6506909666))
YOUR_USERNAME = '@Priyanshu0091' # Replace with your Telegram username (without the @)
UPDATE_CHANNEL = 'https://t.me/autolikebyme' # Replace with your update channel link

# Folder setup - using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__)) # Get script's directory
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf') # Assuming this name is intentional
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

# File upload limits
# Free/premium limits are now set from the Admin Panel (Limits + Plans). Only admin/owner are fixed here:
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')
# FREE_MODE_LIMIT = 3 # Removed as free_mode is removed

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

# Initialize bot
if 'PASTE_' in TOKEN:
    sys.exit('❌ BOT_TOKEN is not set. Create a new token in @BotFather and set it as the BOT_TOKEN environment variable.')
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# ===== small-caps font (ᴀʙᴄᴅᴇ…) for every message, caption and button =====
_SC_MAP = dict(zip('abcdefghijklmnopqrstuvwxyz', 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ'))
_SC_MAP.update({k.upper(): v for k, v in list(_SC_MAP.items())})
_RAW_MARK = '\u2063'   # put this invisible mark in a text: everything AFTER it is sent untouched (logs, error output)
_CODE_SPAN = re.compile(r'```.*?```|`[^`\n]*`', re.S)
_WORD_RUN = re.compile(r'[A-Za-z]+')

def _sc_word(m):
    s, a, b = m.string, m.start(), m.end()
    before, after = (s[a - 1] if a else ''), (s[b] if b < len(s) else '')
    if before and (before.isdigit() or before in '@/_#\\'): return m.group(0)                 # @user, /command, _x
    if after and (after.isdigit() or after in '_/@\\'): return m.group(0)                      # file_1, py3, a/b
    if before == '.' and a >= 2 and s[a - 2].isalnum(): return m.group(0)                      # bot.PY  <- extension
    if after == '.' and b + 1 < len(s) and s[b + 1].isalnum(): return m.group(0)               # BOT.py, t.me
    if after == '-' and b + 1 < len(s) and s[b + 1].isdigit(): return m.group(0)               # ORD-1234
    if after == ':' and s[b + 1:b + 3] == '//': return m.group(0)                              # https://
    return ''.join(_SC_MAP.get(c, c) for c in m.group(0))

def _sc_plain(t): return _WORD_RUN.sub(_sc_word, t)

def sc(text):
    """Small-caps conversion that leaves file names, links, @usernames, /commands, numbers and `code` alone."""
    if not isinstance(text, str) or not text: return text
    head, _mark, tail = text.partition(_RAW_MARK)
    out, last = [], 0
    for m in _CODE_SPAN.finditer(head):
        out.append(_sc_plain(head[last:m.start()])); out.append(m.group(0)); last = m.end()
    out.append(_sc_plain(head[last:]))
    return ''.join(out) + tail

def _install_text_wrappers():
    def wrap(name, pos, kw):
        orig = getattr(bot, name)
        def w(*a, **k):
            a = list(a)
            if kw in k and isinstance(k[kw], str): k[kw] = sc(k[kw])
            elif pos is not None and len(a) > pos and isinstance(a[pos], str): a[pos] = sc(a[pos])
            return orig(*a, **k)
        setattr(bot, name, w)
    for name, pos, kw in (('send_message', 1, 'text'), ('reply_to', 1, 'text'), ('send_photo', None, 'caption'),
                          ('send_document', None, 'caption'), ('send_video', None, 'caption'), ('edit_message_caption', 0, 'caption')):
        wrap(name, pos, kw)
    orig_edit, orig_send, orig_answer = bot.edit_message_text, bot.send_message, bot.answer_callback_query
    def edit_w(*a, **k):
        a = list(a)
        text = k.get('text', a[0] if a else None)
        chat_id = k.get('chat_id', a[1] if len(a) > 1 else None)
        mid = k.get('message_id', a[2] if len(a) > 2 else None)
        if mid is None and chat_id is not None:     # a screen opened from a keyboard button has no message to edit -> send a new one
            return orig_send(chat_id, text, **{x: k[x] for x in ('reply_markup', 'parse_mode') if x in k})
        if isinstance(text, str):
            if 'text' in k: k['text'] = sc(text)
            else: a[0] = sc(text)
        return orig_edit(*a, **k)
    def answer_w(*a, **k):
        a = list(a)
        cid = k.get('callback_query_id', a[0] if a else None)
        if cid is None: return None                  # keyboard-button "fake callback": nothing to answer
        if 'text' in k and isinstance(k['text'], str): k['text'] = sc(k['text'])
        elif len(a) > 1 and isinstance(a[1], str): a[1] = sc(a[1])
        return orig_answer(*a, **k)
    bot.edit_message_text, bot.answer_callback_query = edit_w, answer_w

_install_text_wrappers()

# --- Data structures ---
bot_scripts = {} # Stores info about running scripts {script_key: info_dict}
user_subscriptions = {} # {user_id: {'expiry': datetime_object}}
user_files = {} # {user_id: [(file_name, file_type), ...]}
active_users = set() # Set of all user IDs that have interacted with the bot
admin_ids = {ADMIN_ID, OWNER_ID} # Set of admin IDs
# free_mode = False # Removed free_mode

# --- Logging Setup ---
# Configure basic logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Colored buttons (Telegram Bot API 9.4: style = primary(blue) / success(green) / danger(red)) ---
_AUTO = object()

def auto_style(text):
    """Pick a color from the button text. None = normal grey button."""
    t = (text or '').lower()
    if '🔙' in t: return None                                      # Back buttons stay neutral
    if t.rstrip().endswith(': off'): return 'danger'                # switches: OFF = red, ON = green
    if 'lock status' in t or 'lock center' in t: return 'primary'
    if 'unlock' in t or 'unban' in t: return 'success'
    if 'restart' in t: return 'primary'
    if any(k in t for k in ('stop', 'delete', 'remove', 'cancel', 'lock', 'ban', 'restore')): return 'danger'
    if any(k in t for k in ('start', 'upload', 'add ', 'confirm', 'run all', 'give', 'premium', 'backup', 'pay now', 'buy')): return 'success'
    return 'primary'

class CInlineButton(types.InlineKeyboardButton):
    def __init__(self, text, *args, style=_AUTO, **kwargs):
        super().__init__(sc(text), *args, **kwargs)
        self._btn_style = auto_style(text) if style is _AUTO else style
    def to_dict(self):
        d = super().to_dict()
        if self._btn_style: d['style'] = self._btn_style
        return d

class CKeyboardButton(types.KeyboardButton):
    def __init__(self, text, *args, style=_AUTO, **kwargs):
        super().__init__(sc(text), *args, **kwargs)
        self._btn_style = auto_style(text) if style is _AUTO else style
    def to_dict(self):
        d = super().to_dict()
        if self._btn_style: d['style'] = self._btn_style
        return d
# --- End colored buttons ---

# --- Database Setup ---
def init_db():
    """Initialize the database with required tables"""
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False) # Allow access from multiple threads
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS autostart
                     (user_id INTEGER, file_name TEXT, PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS plans
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL, bots INTEGER, days INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS orders
                     (order_id TEXT PRIMARY KEY, user_id INTEGER, plan_name TEXT, bots INTEGER, days INTEGER,
                      amount REAL, payable REAL, status TEXT, payment_url TEXT, upi_link TEXT,
                      created TEXT, expires_at TEXT, fulfilled INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS expired_stopped
                     (user_id INTEGER, file_name TEXT, PRIMARY KEY (user_id, file_name))''')
        for _col, _typ in (('bots', 'INTEGER'), ('plan_name', 'TEXT')):   # older databases: add the new columns
            try: c.execute(f"ALTER TABLE subscriptions ADD COLUMN {_col} {_typ}")
            except sqlite3.OperationalError: pass
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''') # Added admins table
        # Ensure owner and initial admin are in admins table
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
             c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    """Load data from database into memory"""
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        # Load subscriptions
        c.execute('SELECT user_id, expiry, bots, plan_name FROM subscriptions')
        for user_id, expiry, bots, plan_name in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry), 'bots': bots, 'plan_name': plan_name}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        # Load user files
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        # Load active users
        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        # Load admins
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall()) # Load admins into the set

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

# Initialize DB and Load Data at startup
init_db()
load_data()
# --- End Database Setup ---

# --- Helper Functions ---
def get_user_folder(user_id):
    """Get or create user's folder for storing files"""
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_count(user_id):
    """Get the number of files uploaded by a user"""
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name): # Parameter renamed for clarity
    """Check if a bot script is currently running for a specific user"""
    script_key = f"{script_owner_id}_{file_name}" # Key uses script_owner_id
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                logger.warning(f"Process {script_info['process'].pid} for {script_key} found in memory but not running/zombie. Cleaning up.")
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except Exception as log_e:
                        logger.error(f"Error closing log file during zombie cleanup {script_key}: {log_e}")
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            logger.warning(f"Process for {script_key} not found (NoSuchProcess). Cleaning up.")
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                     script_info['log_file'].close()
                except Exception as log_e:
                     logger.error(f"Error closing log file during cleanup of non-existent process {script_key}: {log_e}")
            if script_key in bot_scripts:
                 del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process status for {script_key}: {e}", exc_info=True)
            return False
    return False


def kill_process_tree(process_info):
    """Kill a process and all its children, ensuring log file is closed."""
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A') 

    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
                logger.info(f"Closed log file for {script_key} (PID: {process_info.get('process', {}).get('pid', 'N/A')})")
            except Exception as log_e:
                logger.error(f"Error closing log file during kill for {script_key}: {log_e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
           pid = process.pid
           if pid: 
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.info(f"Attempting to kill process tree for {script_key} (PID: {pid}, Children: {[c.pid for c in children]})")

                    for child in children:
                        try:
                            child.terminate()
                            logger.info(f"Terminated child process {child.pid} for {script_key}")
                        except psutil.NoSuchProcess:
                            logger.warning(f"Child process {child.pid} for {script_key} already gone.")
                        except Exception as e:
                            logger.error(f"Error terminating child {child.pid} for {script_key}: {e}. Trying kill...")
                            try: child.kill(); logger.info(f"Killed child process {child.pid} for {script_key}")
                            except Exception as e2: logger.error(f"Failed to kill child {child.pid} for {script_key}: {e2}")

                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        logger.warning(f"Child process {p.pid} for {script_key} still alive. Killing.")
                        try: p.kill()
                        except Exception as e: logger.error(f"Failed to kill child {p.pid} for {script_key} after wait: {e}")

                    try:
                        parent.terminate()
                        logger.info(f"Terminated parent process {pid} for {script_key}")
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            logger.warning(f"Parent process {pid} for {script_key} did not terminate. Killing.")
                            parent.kill()
                            logger.info(f"Killed parent process {pid} for {script_key}")
                    except psutil.NoSuchProcess:
                        logger.warning(f"Parent process {pid} for {script_key} already gone.")
                    except Exception as e:
                        logger.error(f"Error terminating parent {pid} for {script_key}: {e}. Trying kill...")
                        try: parent.kill(); logger.info(f"Killed parent process {pid} for {script_key}")
                        except Exception as e2: logger.error(f"Failed to kill parent {pid} for {script_key}: {e2}")

                except psutil.NoSuchProcess:
                    logger.warning(f"Process {pid or 'N/A'} for {script_key} not found during kill. Already terminated?")
           else: logger.error(f"Process PID is None for {script_key}.")
        elif log_file_closed: logger.warning(f"Process object missing for {script_key}, but log file closed.")
        else: logger.error(f"Process object missing for {script_key}, and no log file. Cannot kill.")
    except Exception as e:
        logger.error(f"❌ Unexpected error killing process tree for PID {pid or 'N/A'} ({script_key}): {e}", exc_info=True)

# --- Automatic Package Installation & Script Running ---

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name) 
    if package_name is None: 
        logger.info(f"Module '{module_name}' is core. Skipping pip install.")
        return False 
    try:
        bot.reply_to(message, f"🐍 Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        logger.info(f"Running install: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            logger.info(f"Installed {package_name}. Output:\n{result.stdout}")
            bot.reply_to(message, f"✅ Package `{package_name}` (for `{module_name}`) installed.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ Failed to install `{package_name}` for `{module_name}`.\nLog:\n```\n{result.stderr or result.stdout}\n```"
            logger.error(error_msg)
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except Exception as e:
        error_msg = f"❌ Error installing `{package_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Node package `{module_name}` not found. Installing locally...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        logger.info(f"Running npm install: {' '.join(command)} in {user_folder}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            logger.info(f"Installed {module_name}. Output:\n{result.stdout}")
            bot.reply_to(message, f"✅ Node package `{module_name}` installed locally.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ Failed to install Node package `{module_name}`.\nLog:\n```\n{result.stderr or result.stdout}\n```"
            logger.error(error_msg)
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except FileNotFoundError:
         error_msg = "❌ Error: 'npm' not found. Ensure Node.js/npm are installed and in PATH."
         logger.error(error_msg)
         bot.reply_to(message, error_msg)
         return False
    except Exception as e:
        error_msg = f"❌ Error installing Node package `{module_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

# ===================== SMART INSTALL + SCRIPT RUNNER (rewritten) =====================
# How it works now:
#   1. Read the script (and the local modules it imports) and find EVERY third-party import
#   2. Install all missing packages (+ requirements.txt) together, in ONE go
#   3. Only then start the script, wait STARTUP_CHECK_SECONDS and confirm it is really alive
#   4. Safety net: if it still dies with "No module named X", install X and restart automatically
#   5. "Started" message is sent ONLY after the script has stayed alive
PIP_LOCK = threading.Lock()
NPM_LOCK = threading.Lock()
STARTUP_CHECK_SECONDS = 8   # script must stay alive this long before we say "started"
MAX_AUTOFIX_ROUNDS = 6      # max "install missing module -> restart" cycles

# import-name -> pip package name (None = never install). Unknown names are tried as-is.
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI', 'telegram': 'python-telegram-bot', 'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram', 'pyrogram': 'pyrogram', 'telethon': 'telethon', 'telepot': 'telepot', 'tgcrypto': 'tgcrypto',
    'bs4': 'beautifulsoup4', 'PIL': 'Pillow', 'cv2': 'opencv-python-headless', 'yaml': 'PyYAML',
    'dotenv': 'python-dotenv', 'dateutil': 'python-dateutil', 'Crypto': 'pycryptodome', 'jwt': 'PyJWT',
    'sklearn': 'scikit-learn', 'serial': 'pyserial', 'attr': 'attrs', 'OpenSSL': 'pyOpenSSL', 'nacl': 'PyNaCl',
    'websocket': 'websocket-client', 'magic': 'python-magic', 'git': 'GitPython', 'flask_cors': 'Flask-Cors',
    'fitz': 'PyMuPDF', 'docx': 'python-docx', 'pptx': 'python-pptx', 'speech_recognition': 'SpeechRecognition',
    'pkg_resources': 'setuptools', 'flask': 'Flask', 'sqlalchemy': 'SQLAlchemy', 'django': 'Django',
    'google': None,  # ambiguous namespace (google.generativeai, google.cloud...) -> use requirements.txt
}


class _Ctx:
    """Minimal message-like object, so scripts can be (re)started without a user message (auto-restart on boot)."""
    class _Chat:
        def __init__(self, chat_id): self.id = chat_id
    def __init__(self, chat_id):
        self.chat = _Ctx._Chat(chat_id); self.message_id = None; self.from_user = None


def _safe_reply(msg_obj, text, **kwargs):
    text = str(text)[:4000]
    try:
        if getattr(msg_obj, 'message_id', None):
            return bot.reply_to(msg_obj, text, **kwargs)
        return bot.send_message(msg_obj.chat.id, text, **kwargs)
    except Exception as e:
        logger.error(f"_safe_reply failed: {e}")


def _pip(args, timeout=900):
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-q'] + list(args)
    logger.info(f"Running: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='ignore')
        return r.returncode == 0, (r.stderr or r.stdout or '')[-1500:]
    except subprocess.TimeoutExpired:
        return False, 'pip timed out'
    except Exception as e:
        return False, str(e)


def _is_local_module(user_folder, name):
    return os.path.exists(os.path.join(user_folder, name + '.py')) or os.path.isdir(os.path.join(user_folder, name))


def _scan_python_imports(script_path, user_folder):
    """Top-level third-party import names used by the script and by the local modules it imports."""
    names, seen, queue = set(), set(), [script_path]
    while queue and len(seen) < 50:
        path = queue.pop()
        if path in seen: continue
        seen.add(path)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                tree = ast.parse(f.read())
        except Exception as e:
            logger.warning(f"Could not parse {path} for imports: {e}")
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import): mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module: mods = [node.module]
            for m in mods:
                top = m.split('.')[0]
                if _is_local_module(user_folder, top):
                    base = os.path.join(user_folder, *m.split('.'))
                    for cand in (base + '.py', os.path.join(base, '__init__.py')):
                        if os.path.exists(cand): queue.append(cand)
                else:
                    names.add(top)
    return names


def _missing_py_packages(import_names):
    missing = set()
    for n in import_names:
        pkg = TELEGRAM_MODULES.get(n, n)
        if pkg is None: continue
        try:
            if importlib.util.find_spec(n) is not None: continue
        except Exception:
            pass
        missing.add(pkg)
    return sorted(missing)


class HeavyPackageBlocked(Exception):
    pass


def ensure_python_deps(script_path, user_folder, say, allow_heavy=True):
    """Install EVERYTHING the script needs in one go. Returns the list of packages that failed."""
    failed = []
    with PIP_LOCK:
        req_path = os.path.join(user_folder, 'requirements.txt')
        marker = os.path.join(user_folder, '.requirements.md5')
        if not allow_heavy:   # free plan: refuse heavy packages BEFORE anything is installed
            heavy = set()
            if os.path.exists(req_path):
                with open(req_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        nm = _norm_pkg(re.split(r'[<>=!~\[;@ ]', line.strip(), maxsplit=1)[0])
                        if nm in HEAVY_PACKAGES: heavy.add(nm)
            for imp in _scan_python_imports(script_path, user_folder):
                pkg = TELEGRAM_MODULES.get(imp, imp)
                if pkg and _norm_pkg(pkg) in HEAVY_PACKAGES: heavy.add(_norm_pkg(pkg))
            if heavy: raise HeavyPackageBlocked(', '.join(sorted(heavy)))
        if os.path.exists(req_path):
            with open(req_path, 'rb') as f: digest = hashlib.md5(f.read()).hexdigest()
            prev = ''
            if os.path.exists(marker):
                with open(marker) as f: prev = f.read().strip()
            if digest != prev:  # installed once per requirements.txt version, not on every start
                say("📦 Installing packages from requirements.txt ...")
                ok, log = _pip(['-r', req_path])
                if ok:
                    with open(marker, 'w') as f: f.write(digest)
                else:
                    failed.append('requirements.txt')
                    say(f"❌ requirements.txt install error:\n\u2063{log[-800:]}")
        missing = _missing_py_packages(_scan_python_imports(script_path, user_folder))
        if missing:
            say("📦 Installing: " + ", ".join(missing))
            ok, log = _pip(missing)
            if not ok:  # find which package is the bad one, install the rest
                for pkg in missing:
                    ok1, log1 = _pip([pkg])
                    if not ok1:
                        failed.append(pkg)
                        say(f"❌ Could not install '{pkg}':\n\u2063{log1[-500:]}")
        if not failed and (os.path.exists(req_path) or missing):
            say("✅ All packages installed.")
    return failed


def ensure_node_deps(user_folder, say):
    if os.path.exists(os.path.join(user_folder, 'package.json')) and not os.path.isdir(os.path.join(user_folder, 'node_modules')):
        say("📦 Installing Node packages (npm install) ...")
        try:
            with NPM_LOCK:
                r = subprocess.run(['npm', 'install'], capture_output=True, text=True, cwd=user_folder, timeout=900, encoding='utf-8', errors='ignore')
            if r.returncode == 0: say("✅ Node packages installed.")
            else: say(f"❌ npm install failed:\n\u2063{(r.stderr or r.stdout)[-800:]}")
        except FileNotFoundError:
            say("❌ 'npm' not found. Install Node.js on the server.")
        except Exception as e:
            say(f"❌ npm error: {e}")


def _find_missing_module(kind, log_tail):
    """Package name to install, based on the crash log (None if not a missing-module crash)."""
    if kind == 'py':
        m = re.search(r"No module named '([^']+)'", log_tail)
        if not m: return None
        top = m.group(1).split('.')[0]
        return TELEGRAM_MODULES.get(top, top)
    m = re.search(r"Cannot find module '([^']+)'", log_tail)
    if not m: return None
    name = m.group(1)
    if name.startswith('.') or name.startswith('/'): return None
    parts = name.split('/')
    return '/'.join(parts[:2]) if name.startswith('@') else parts[0]


def _install_single(kind, pkg, user_folder):
    if kind == 'py':
        with PIP_LOCK: ok, _ = _pip([pkg])
        return ok
    try:
        with NPM_LOCK:
            r = subprocess.run(['npm', 'install', pkg], capture_output=True, text=True, cwd=user_folder, timeout=900, encoding='utf-8', errors='ignore')
        return r.returncode == 0
    except Exception:
        return False


def _read_log_tail(log_path, max_chars=1500):
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: return f.read()[-max_chars:].strip()
    except Exception:
        return ''


def _launch_process(kind, script_path, owner_id, user_folder, file_name, script_key, msg_obj):
    log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
    open(log_path, 'w').close()   # fresh log on every start
    log_file = open(log_path, 'a', encoding='utf-8', errors='ignore')   # append mode, so the monitor can trim big logs safely
    cmd = [sys.executable, '-u', script_path] if kind == 'py' else ['node', script_path]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        process = subprocess.Popen(cmd, cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
                                   creationflags=creationflags, encoding='utf-8', errors='ignore')
    except Exception:
        log_file.close(); raise
    if os.name == 'posix':
        try: psutil.Process(process.pid).nice(10)   # hosted scripts run at low priority, this bot stays fast
        except Exception: pass
    bot_scripts[script_key] = {
        'process': process, 'log_file': log_file, 'file_name': file_name,
        'chat_id': msg_obj.chat.id, 'script_owner_id': owner_id,
        'start_time': datetime.now(), 'user_folder': user_folder, 'type': kind, 'script_key': script_key
    }
    return process, log_file, log_path


def _run_script_generic(kind, script_path, owner_id, user_folder, file_name, msg_obj):
    script_key = f"{owner_id}_{file_name}"
    label = 'Python' if kind == 'py' else 'JS'
    say = lambda text: _safe_reply(msg_obj, text)
    try:
        if not os.path.exists(script_path):
            say(f"❌ Error: Script '{file_name}' not found!")
            if owner_id in user_files:
                user_files[owner_id] = [f for f in user_files.get(owner_id, []) if f[0] != file_name]
            remove_user_file_db(owner_id, file_name)
            return
        if is_bot_running(owner_id, file_name):
            say(f"⚠️ '{file_name}' is already running."); return
        if owner_id not in admin_ids and running_bots_total() >= int(get_num('max_total_bots')):
            say("🚫 The server is full right now (maximum running bots reached). Please try again later."); return
        allow_heavy = get_tier_limits(owner_id)['heavy_ok']

        # 1) install everything first
        try:
            if kind == 'py': ensure_python_deps(script_path, user_folder, say, allow_heavy=allow_heavy)
            else: ensure_node_deps(user_folder, say)
        except HeavyPackageBlocked as hb:
            say(f"🚫 Heavy package not allowed on the free plan: {hb}\n💎 Premium plans allow heavy packages. Open 💎 Premium Plans.")
            return

        # 2) start, verify it stays alive, auto-fix a missing module if one still shows up
        tried, rounds = set(), 0
        while True:
            rounds += 1
            try:
                process, log_file, log_path = _launch_process(kind, script_path, owner_id, user_folder, file_name, script_key, msg_obj)
            except FileNotFoundError:
                say(f"❌ {label} interpreter not found on the server."); return
            except Exception as e:
                say(f"❌ Error starting '{file_name}': {e}"); return
            logger.info(f"Started {label} process {process.pid} for {script_key}")

            deadline = time.time() + STARTUP_CHECK_SECONDS
            while time.time() < deadline and process.poll() is None: time.sleep(0.5)

            if process.poll() is None:
                set_autostart(owner_id, file_name, True)
                say(f"✅ {label} bot '{file_name}' started! (PID: {process.pid})\n📦 All packages ready.")
                return

            # it died right after start
            tail = _read_log_tail(log_path)
            try: log_file.close()
            except Exception: pass
            bot_scripts.pop(script_key, None)
            missing = _find_missing_module(kind, tail)
            if missing and not allow_heavy and _norm_pkg(missing) in HEAVY_PACKAGES:
                say(f"🚫 '{missing}' is a heavy package — premium only."); return
            if missing and missing not in tried and rounds < MAX_AUTOFIX_ROUNDS:
                tried.add(missing)
                say(f"📦 Missing module '{missing}' found. Installing, then restarting ...")
                if _install_single(kind, missing, user_folder): continue
                say(f"❌ Could not install '{missing}'.")
            code = process.returncode
            head = "ℹ️ finished (exit code 0)" if code == 0 else f"❌ stopped right after start (exit code {code})"
            say(f"'{file_name}' {head}\n\nLog:\n\u2063{tail[-1200:] or '(empty)'}")
            return
    except Exception as e:
        logger.error(f"Unexpected error running {file_name}: {e}", exc_info=True)
        say(f"❌ Unexpected error running '{file_name}': {e}")
        info = bot_scripts.pop(script_key, None)
        if info: kill_process_tree(info)


def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    _run_script_generic('py', script_path, script_owner_id, user_folder, file_name, message_obj_for_reply)


def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    _run_script_generic('js', script_path, script_owner_id, user_folder, file_name, message_obj_for_reply)


# --- Auto-restart after the host restarts (Render etc. kill all child processes) ---
def set_autostart(user_id, file_name, on):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            if on: conn.execute('INSERT OR IGNORE INTO autostart (user_id, file_name) VALUES (?, ?)', (user_id, file_name))
            else: conn.execute('DELETE FROM autostart WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
        except Exception as e:
            logger.error(f"autostart db error: {e}")
        finally: conn.close()


def autostart_all():
    time.sleep(5)
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            rows = conn.execute('SELECT user_id, file_name FROM autostart').fetchall()
            conn.close()
    except Exception as e:
        logger.error(f"autostart read error: {e}"); return
    logger.info(f"Auto-restarting {len(rows)} script(s) that were running before shutdown.")
    for uid, fn in rows:
        ftype = next((t for n, t in user_files.get(uid, []) if n == fn), None)
        folder = get_user_folder(uid)
        path = os.path.join(folder, fn)
        if not ftype or not os.path.exists(path):
            set_autostart(uid, fn, False); continue
        if is_bot_running(uid, fn): continue
        target = run_script if ftype == 'py' else run_js_script
        threading.Thread(target=target, args=(path, uid, folder, fn, _Ctx(uid)), daemon=True).start()
        time.sleep(2)


# --- Same file name uploaded again: old file gets a new name, new file takes the name ---
def archive_existing_file(user_id, file_name):
    """If user already has `file_name`, rename the OLD one (file, log, db record, running process) to name_old1.ext.
    Returns the new name of the old file, or None if there was nothing to rename."""
    folder = get_user_folder(user_id)
    old_path = os.path.join(folder, file_name)
    has_record = any(f[0] == file_name for f in user_files.get(user_id, []))
    if not (has_record or os.path.exists(old_path)): return None

    base, ext = os.path.splitext(file_name)
    n = 1
    while True:
        new_name = f"{base}_old{n}{ext}"
        if not os.path.exists(os.path.join(folder, new_name)) and not any(f[0] == new_name for f in user_files.get(user_id, [])): break
        n += 1
    new_path = os.path.join(folder, new_name)
    if os.path.exists(old_path): os.rename(old_path, new_path)
    old_log = os.path.join(folder, f"{base}.log")
    new_log = os.path.join(folder, f"{os.path.splitext(new_name)[0]}.log")
    if os.path.exists(old_log):
        try: os.rename(old_log, new_log)
        except OSError as e: logger.warning(f"Could not rename log: {e}")

    ftype = next((f[1] for f in user_files.get(user_id, []) if f[0] == file_name), ext.lstrip('.') or 'py')
    remove_user_file_db(user_id, file_name)
    save_user_file(user_id, new_name, ftype)

    old_key, new_key = f"{user_id}_{file_name}", f"{user_id}_{new_name}"
    info = bot_scripts.pop(old_key, None)
    if info:  # old one keeps running under its new name
        info['file_name'] = new_name; info['script_key'] = new_key
        bot_scripts[new_key] = info
        set_autostart(user_id, file_name, False); set_autostart(user_id, new_name, True)
    else:
        set_autostart(user_id, file_name, False)
    logger.info(f"Renamed old '{file_name}' -> '{new_name}' for user {user_id}")
    return new_name

# --- End Automatic Package Installation & Script Running ---


# --- Database Operations ---
DB_LOCK = threading.Lock() 

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
            logger.info(f"Saved file '{file_name}' ({file_type}) for user {user_id}")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error saving file for user {user_id}, {file_name}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error saving file for {user_id}, {file_name}: {e}", exc_info=True)
        finally: conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]: del user_files[user_id]
            logger.info(f"Removed file '{file_name}' for user {user_id} from DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing file for {user_id}, {file_name}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error removing file for {user_id}, {file_name}: {e}", exc_info=True)
        finally: conn.close()

def add_active_user(user_id):
    active_users.add(user_id) 
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
            logger.info(f"Added/Confirmed active user {user_id} in DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error adding active user {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error adding active user {user_id}: {e}", exc_info=True)
        finally: conn.close()

def save_subscription(user_id, expiry, bots=None, plan_name=None):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry, bots, plan_name) VALUES (?, ?, ?, ?)',
                      (user_id, expiry_str, bots, plan_name))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry, 'bots': bots, 'plan_name': plan_name}
            logger.info(f"Saved subscription for {user_id}, expiry {expiry_str}, bots {bots}, plan {plan_name}")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error saving subscription for {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error saving subscription for {user_id}: {e}", exc_info=True)
        finally: conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions: del user_subscriptions[user_id]
            logger.info(f"Removed subscription for {user_id} from DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing subscription for {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error removing subscription for {user_id}: {e}", exc_info=True)
        finally: conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id) 
            logger.info(f"Added admin {admin_id} to DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error adding admin {admin_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error adding admin {admin_id}: {e}", exc_info=True)
        finally: conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        logger.warning("Attempted to remove OWNER_ID from admins.")
        return False 
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0 
                if removed: admin_ids.discard(admin_id); logger.info(f"Removed admin {admin_id} from DB")
                else: logger.warning(f"Admin {admin_id} found but delete affected 0 rows.")
            else:
                logger.warning(f"Admin {admin_id} not found in DB.")
                admin_ids.discard(admin_id)
            return removed
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing admin {admin_id}: {e}"); return False
        except Exception as e: logger.error(f"❌ Unexpected error removing admin {admin_id}: {e}", exc_info=True); return False
        finally: conn.close()
# --- End Database Operations ---

# ============================================================================
#  v2 FEATURES  (A) settings · tiers · lock · plans · MinorUPI payments · expiry
# ============================================================================
GRACE_DAYS = 3                 # after a plan ends, extra bots are stopped only after this many days
REMIND_DAYS = 3                # "plan ends soon" reminder
ORDER_EXPIRY_MIN = 10          # payment order validity (minutes)
GATEWAY_TIMEOUT = 15           # seconds for every gateway call
DEFAULT_PAID_BOTS = 5          # bots for a manually given legacy subscription without a plan
LOG_MAX_BYTES = 1024 * 1024    # hosted-bot log files are trimmed above this size
HEAVY_PACKAGES = {             # not allowed for free users (premium / admin only)
    'torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorflow-cpu', 'keras', 'scikit-learn', 'sklearn',
    'opencv-python', 'opencv-python-headless', 'opencv-contrib-python', 'selenium', 'playwright', 'pyppeteer',
    'undetected-chromedriver', 'moviepy', 'transformers', 'diffusers', 'scipy', 'dlib', 'face-recognition',
}

DEFAULT_SETTINGS = {
    'free_bot_limit': '1',
    'free_max_file_mb': '2', 'free_max_zip_mb': '5', 'free_storage_mb': '10',
    'paid_max_file_mb': '20', 'paid_max_zip_mb': '20', 'paid_storage_mb': '200',
    'max_total_bots': '8',
    'storage_budget_mb': '0',          # 0 = use real disk size in Status
    'lock_free': '0', 'lock_all': '0',
    'minorupi_base_url': 'https://minorupi.onvoroa.com', 'minorupi_api_key': '',
    'last_backup': '',
    'force_on': '1', 'force_channels': '[]',   # force join (set from Admin Panel -> Force Join)
    'run_all': '0',                            # Run All Code switch
}
SETTINGS = dict(DEFAULT_SETTINGS)
banned_ids = set()
_CUR = threading.local()       # id of the user whose callback is being handled (used by menus)


def _db_exec(sql, params=(), fetch=None):
    """Run ONE statement under DB_LOCK. fetch: None -> rowcount | 'one' | 'all'."""
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            cur = conn.execute(sql, params)
            if fetch == 'one': res = cur.fetchone()
            elif fetch == 'all': res = cur.fetchall()
            else: res = cur.rowcount
            conn.commit()
            return res
        finally:
            conn.close()


def load_settings():
    for k, v in _db_exec("SELECT key, value FROM settings", fetch='all'):
        if k in DEFAULT_SETTINGS: SETTINGS[k] = v

def load_banned():
    banned_ids.clear()
    banned_ids.update(u for (u,) in _db_exec("SELECT user_id FROM banned", fetch='all'))

def get_setting(key): return SETTINGS.get(key, DEFAULT_SETTINGS.get(key, ''))

def get_num(key):
    try: return float(get_setting(key))
    except (TypeError, ValueError): return float(DEFAULT_SETTINGS[key])

def set_setting(key, value):
    SETTINGS[key] = str(value)
    _db_exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

def _notify(user_id, text, **kw):
    try: bot.send_message(user_id, text, **kw)
    except Exception as e: logger.warning(f"notify {user_id} failed: {e}")

def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try: total += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    return total

def fmt_price(p): return f"₹{p:g}"


# ---------------------------------------------------------------- tiers & lock
def is_premium(user_id):
    s = user_subscriptions.get(user_id)
    return bool(s and s['expiry'] > datetime.now())

def is_locked_for(user_id):
    """Admins are never locked. 'Lock All' locks everybody else, 'Lock Free' only non-premium users."""
    if user_id in admin_ids: return False
    if get_setting('lock_all') == '1': return True
    return get_setting('lock_free') == '1' and not is_premium(user_id)

def lock_status_text(user_id):
    lf, la = get_setting('lock_free') == '1', get_setting('lock_all') == '1'
    if user_id in admin_ids:
        return f"Free {'🔒' if lf else '🔓'} · All {'🔒' if la else '🔓'}"
    return '🔒 Locked' if is_locked_for(user_id) else '🔓 Open'

def get_tier_limits(user_id):
    """MB limits for uploads. storage_mb None = unlimited. 20 MB = Telegram's download limit for bots."""
    if user_id in admin_ids:
        return {'file_mb': 20, 'zip_mb': 20, 'storage_mb': None, 'heavy_ok': True}
    if is_premium(user_id):
        return {'file_mb': min(20, get_num('paid_max_file_mb')), 'zip_mb': min(20, get_num('paid_max_zip_mb')),
                'storage_mb': get_num('paid_storage_mb'), 'heavy_ok': True}
    return {'file_mb': min(20, get_num('free_max_file_mb')), 'zip_mb': min(20, get_num('free_max_zip_mb')),
            'storage_mb': get_num('free_storage_mb'), 'heavy_ok': False}

def get_user_file_limit(user_id):
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if is_premium(user_id):
        bots = user_subscriptions[user_id].get('bots')
        return int(bots) if bots else DEFAULT_PAID_BOTS
    return int(get_num('free_bot_limit'))

def _status_line(user_id):
    """(status label, extra line) used in welcome / main menu texts."""
    if user_id == OWNER_ID: return "👑 Owner", ""
    if user_id in admin_ids: return "🛡️ Admin", ""
    if is_premium(user_id):
        s = user_subscriptions[user_id]
        days = max(0, (s['expiry'] - datetime.now()).days)
        return f"⭐ Premium ({s.get('plan_name') or 'Plan'})", f"\n⏳ Plan ends in: {days} days"
    return "🆓 Free User", ""

def running_bots_total():
    return sum(1 for key, info in list(bot_scripts.items())
               if is_bot_running(info.get('script_owner_id', 0), info.get('file_name', '')))

def _norm_pkg(name): return re.sub(r'[-_.]+', '-', (name or '').strip().lower())


# ---------------------------------------------------------------- plans
def get_plans():
    return _db_exec("SELECT id, name, price, bots, days FROM plans ORDER BY price, id", fetch='all')

def plans_text():
    rows = get_plans()
    if not rows: return "📦 No plans yet. Tap ➕ Add Plan."
    return "📦 Plans\n\n" + "\n".join(f"#{i}  {n} — {fmt_price(p)} — {b} bots — {d} days" for i, n, p, b, d in rows)

def activate_plan(user_id, plan_name, bots, days):
    """Start or extend a premium plan. Returns the new expiry. Safe to call for renewals."""
    now = datetime.now()
    old = user_subscriptions.get(user_id, {})
    active_now = bool(old.get('expiry') and old['expiry'] > now)
    start = old['expiry'] if active_now else now
    new_bots = max(int(bots), int(old.get('bots') or 0)) if active_now else int(bots)
    expiry = start + timedelta(days=int(days))
    save_subscription(user_id, expiry, bots=new_bots, plan_name=plan_name)
    restart_expired_stopped(user_id)
    return expiry

def restart_expired_stopped(user_id):
    """After a renewal: start again the bots that were stopped because the plan ended."""
    rows = _db_exec("SELECT file_name FROM expired_stopped WHERE user_id = ?", (user_id,), fetch='all')
    if not rows: return
    limit = get_user_file_limit(user_id)
    folder = get_user_folder(user_id)
    started = 0
    for (fn,) in rows:
        _db_exec("DELETE FROM expired_stopped WHERE user_id = ? AND file_name = ?", (user_id, fn))
        ftype = next((t for n, t in user_files.get(user_id, []) if n == fn), None)
        path = os.path.join(folder, fn)
        if not ftype or not os.path.exists(path) or started >= limit: continue
        target = run_script if ftype == 'py' else run_js_script
        threading.Thread(target=target, args=(path, user_id, folder, fn, _Ctx(user_id)), daemon=True).start()
        started += 1
    if started: _notify(user_id, f"♻️ Plan renewed — restarting {started} of your stopped bot(s).")

def _stop_script(uid, file_name):
    info = bot_scripts.pop(f"{uid}_{file_name}", None)
    if info: kill_process_tree(info)
    set_autostart(uid, file_name, False)

_reminded = set()

def _check_subscriptions():
    now = datetime.now()
    for uid, sub in list(user_subscriptions.items()):
        exp = sub['expiry']
        if now < exp <= now + timedelta(days=REMIND_DAYS) and (uid, exp.date()) not in _reminded:
            _reminded.add((uid, exp.date()))
            _notify(uid, f"⏰ Your {sub.get('plan_name') or 'premium'} plan ends on {exp:%Y-%m-%d}.\nRenew from 💎 Premium Plans to keep all your bots.")
        elif exp <= now and now - exp >= timedelta(days=GRACE_DAYS) and uid not in admin_ids:
            _enforce_free_limit(uid)
            remove_subscription_db(uid)

def _enforce_free_limit(uid):
    """Plan fully over (grace passed): keep the first N bots, stop the rest (files are NOT deleted)."""
    limit = int(get_num('free_bot_limit'))
    files = sorted(user_files.get(uid, []))
    stopped = []
    for fn, _ft in files[limit:]:
        if is_bot_running(uid, fn):
            _stop_script(uid, fn); stopped.append(fn)
            _db_exec("INSERT OR IGNORE INTO expired_stopped (user_id, file_name) VALUES (?, ?)", (uid, fn))
    if stopped:
        _notify(uid, f"⏹️ Your plan ended. Free plan allows {limit} bot(s), so these were stopped (not deleted):\n" +
                "\n".join(f"• {f}" for f in stopped) + "\n\nRenew a plan and they start again automatically.")

def subscription_watcher():
    while True:
        try: _check_subscriptions()
        except Exception as e: logger.error(f"subscription_watcher error: {e}", exc_info=True)
        time.sleep(600)


# ---------------------------------------------------------------- MinorUPI payments (API only, no webhook)
def gateway_ready():
    return bool(get_setting('minorupi_api_key').strip() and get_setting('minorupi_base_url').strip())

def _gw_headers():
    return {'Authorization': f"Bearer {get_setting('minorupi_api_key').strip()}", 'Content-Type': 'application/json'}

def _gw_url(path): return get_setting('minorupi_base_url').strip().rstrip('/') + path

def _utc_naive(iso_text, fallback):
    try:
        dt = datetime.fromisoformat(str(iso_text).replace('Z', '+00:00'))
        if dt.tzinfo: dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return fallback

def _create_order_inner(user_id, plan_row):
    """Returns (order_dict, None) on success or (None, error_text). Re-uses a still-pending order for the same plan."""
    _pid, name, price, bots, days = plan_row
    if not gateway_ready(): return None, "Payments are not configured yet. Please contact the owner."
    now_utc = datetime.utcnow()
    pending = _db_exec("SELECT order_id, plan_name, amount, payable, payment_url, expires_at FROM orders "
                       "WHERE user_id = ? AND status = 'pending' AND expires_at > ?", (user_id, now_utc.isoformat()), fetch='all')
    if pending:      # one active payment at a time: never create a second link while one is still open
        oid, pname, amount, payable, url, exp = pending[-1]
        return {'order_id': oid, 'plan_name': pname, 'amount': amount, 'payable_amount': payable, 'payment_url': url,
                'qr_base64': None, 'expires_at': exp, 'reused': True}, None
    body = {"amount": float(price), "expiry_minutes": ORDER_EXPIRY_MIN, "note": f"TG_{user_id}_{name}"[:100]}
    try:
        r = requests.post(_gw_url('/api/v1/orders'), headers=_gw_headers(), json=body, timeout=GATEWAY_TIMEOUT)
        js = r.json()
    except Exception as e:
        logger.error(f"create_order request failed: {type(e).__name__}")
        return None, "Payment gateway is not reachable right now. Try again in a minute."
    if not (r.ok and isinstance(js, dict) and js.get('success')):
        msg = (js.get('message') or js.get('error')) if isinstance(js, dict) else None
        logger.error(f"create_order rejected: HTTP {r.status_code} {msg}")
        return None, f"Gateway error: {msg or 'HTTP ' + str(r.status_code)}"
    d = js.get('data') or {}
    oid = d.get('order_id')
    if not oid or not (d.get('payment_url') or d.get('upi_link')):
        return None, "Gateway returned an incomplete order. Try again."
    payable = float(d.get('payable_amount') or d.get('base_amount') or price)
    exp = _utc_naive(d.get('expires_at'), now_utc + timedelta(minutes=ORDER_EXPIRY_MIN))
    _db_exec("INSERT OR IGNORE INTO orders (order_id, user_id, plan_name, bots, days, amount, payable, status, "
             "payment_url, upi_link, created, expires_at, fulfilled) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
             (oid, user_id, name, int(bots), int(days), float(price), payable, 'pending',
              d.get('payment_url') or '', d.get('upi_link') or '', now_utc.isoformat(), exp.isoformat()))
    d['payable_amount'] = payable; d['expires_at'] = exp.isoformat()
    return d, None

_user_locks = {}
_user_locks_guard = threading.Lock()

def create_order(user_id, plan_row):
    """Per-user lock: two quick taps can never create two payment links."""
    with _user_locks_guard: lock = _user_locks.setdefault(user_id, threading.Lock())
    with lock:
        return _create_order_inner(user_id, plan_row)

def fulfill_order(order_id):
    """Idempotent: the plan is given exactly once per paid order, even if several threads see 'paid'."""
    if _db_exec("UPDATE orders SET status='paid', fulfilled=1 WHERE order_id=? AND fulfilled=0", (order_id,)) != 1:
        return False
    uid, plan_name, bots, days, amount = _db_exec(
        "SELECT user_id, plan_name, bots, days, amount FROM orders WHERE order_id=?", (order_id,), fetch='one')
    try:
        expiry = activate_plan(uid, plan_name, bots, days)
    except Exception as e:
        logger.error(f"activate_plan failed for order {order_id}: {e}", exc_info=True)
        _db_exec("UPDATE orders SET status='pending', fulfilled=0 WHERE order_id=?", (order_id,))   # poller retries
        _notify(OWNER_ID, f"⚠️ Order {order_id} is PAID but activating the plan failed ({e}). It will be retried automatically.")
        return False
    _notify(uid, f"✅ Payment received!\n💎 {plan_name} activated: {bots} bots until {expiry:%Y-%m-%d}.")
    _notify(OWNER_ID, f"💰 New payment {fmt_price(amount)} — {plan_name} — user {uid} (order {order_id})")
    return True

def poll_order(order_id):
    """Ask the gateway once. Returns the status text we now know."""
    row = _db_exec("SELECT status, user_id, plan_name, expires_at FROM orders WHERE order_id=?", (order_id,), fetch='one')
    if not row: return 'unknown'
    status_db, uid, plan_name, exp = row
    if status_db != 'pending': return status_db
    try:
        r = requests.get(_gw_url(f"/api/v1/orders/{order_id}"), headers=_gw_headers(), timeout=GATEWAY_TIMEOUT)
        js = r.json()
        d = js.get('data', js) if isinstance(js, dict) else {}
        if d.get('order_id') and d['order_id'] != order_id:
            logger.warning("poll_order: order id mismatch in response"); return 'pending'
        status = str(d.get('status', '')).lower()
    except Exception as e:
        logger.warning(f"poll_order {order_id} failed: {type(e).__name__}")
        return 'pending'
    if status == 'paid':
        fulfill_order(order_id); return 'paid'
    if status in ('expired', 'cancelled', 'failed'):
        if _db_exec("UPDATE orders SET status=? WHERE order_id=? AND status='pending'", (status, order_id)) == 1:
            _notify(uid, f"❌ Your payment order ({plan_name}) is {status}. Open 💎 Premium Plans to try again.")
        return status
    return 'pending'

def payment_poller():
    """Background: while there are unpaid orders, ask the gateway every few seconds. Idle otherwise."""
    while True:
        busy = False
        try:
            if gateway_ready():
                rows = _db_exec("SELECT order_id, expires_at, user_id, plan_name FROM orders WHERE status='pending'", fetch='all')
                busy = bool(rows)
                for oid, exp, uid, pname in rows:
                    st = poll_order(oid)
                    exp_dt = _utc_naive(exp, datetime.utcnow())
                    if st == 'pending' and datetime.utcnow() > exp_dt + timedelta(minutes=2):
                        if _db_exec("UPDATE orders SET status='expired' WHERE order_id=? AND status='pending'", (oid,)) == 1:
                            _notify(uid, f"⌛ Your payment order ({pname}) expired. Open 💎 Premium Plans to create a new one.")
                    time.sleep(0.3)
        except Exception as e:
            logger.error(f"payment_poller error: {e}", exc_info=True)
        time.sleep(7 if busy else 20)

def mask_key(k):
    k = (k or '').strip()
    return '(not set)' if not k else (k[:6] + '…' + k[-3:] if len(k) > 12 else '••••••')


# ---------------------------------------------------------------- user-facing plans & buying
MEDALS = ['🥉', '🥈', '🥇']

def show_plans(chat_id, user_id, edit_message_id=None):
    status, extra = _status_line(user_id)
    lim = get_tier_limits(user_id)
    used, limit = get_user_file_count(user_id), get_user_file_limit(user_id)
    storage = "unlimited" if lim['storage_mb'] is None else f"{lim['storage_mb']:g} MB"
    text = (f"💎 Premium\n\n🔰 Status: {status}{extra}\n🤖 Bots: {used}/{'∞' if limit == float('inf') else limit}\n"
            f"📈 Limit: script {lim['file_mb']:g} MB · zip {lim['zip_mb']:g} MB · storage {storage}"
            f"{'' if lim['heavy_ok'] else ' · no heavy packages'}\n")
    rows = get_plans()
    markup = types.InlineKeyboardMarkup(row_width=1)
    if rows:
        text += "\nPick a plan 👇 (your plan starts automatically after payment)\n\n"
        for n_, (_i, name, price, bots, days) in enumerate(rows, 1):
            medal = MEDALS[n_ - 1] if n_ <= len(MEDALS) else '💎'
            text += f"{n_}. {medal} {name} — {bots} bot{'s' if bots != 1 else ''} — {days} days — {fmt_price(price)}\n"
            markup.add(CInlineButton(f"💎 {n_}. {medal} {name} • {fmt_price(price)} • {days}d", callback_data=f'buy_{_i}', style='success'))
    else:
        text += "\nNo paid plans are available yet. Contact the owner."
    markup.add(CInlineButton('⬅️ Back', callback_data='back_to_main', style='primary'))
    if edit_message_id:
        try: bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=markup); return
        except Exception: pass
    bot.send_message(chat_id, text, reply_markup=markup)

def plans_callback(call):
    bot.answer_callback_query(call.id)
    show_plans(call.message.chat.id, call.from_user.id, call.message.message_id)

def _logic_plans(message):
    show_plans(message.chat.id, message.from_user.id)

def buy_callback(call):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    try: plan_id = int(call.data.split('_', 1)[1])
    except (ValueError, IndexError): bot.answer_callback_query(call.id, "Invalid plan."); return
    rows = _db_exec("SELECT id, name, price, bots, days FROM plans WHERE id=?", (plan_id,), fetch='all')
    if not rows: bot.answer_callback_query(call.id, "This plan is no longer available.", show_alert=True); return
    if not gateway_ready():
        bot.answer_callback_query(call.id, "Payments are not set up yet. Contact the owner.", show_alert=True); return
    bot.answer_callback_query(call.id, "⏳ Please wait...")
    wait = bot.send_message(chat_id, "⏳ Please wait — your payment and QR code are being created...")
    order, err = create_order(uid, rows[0])
    try: bot.delete_message(chat_id, wait.message_id)
    except Exception: pass
    if err: bot.send_message(chat_id, f"❌ {err}"); return
    exp = _utc_naive(order.get('expires_at'), datetime.utcnow() + timedelta(minutes=ORDER_EXPIRY_MIN))
    mins = max(1, int((exp - datetime.utcnow()).total_seconds() // 60) + 1)
    markup = types.InlineKeyboardMarkup(row_width=1)
    if order.get('payment_url'): markup.add(CInlineButton('💳 Pay Now', url=order['payment_url']))
    markup.add(CInlineButton('🔄 Check Status', callback_data=f"chk_{order['order_id']}"))
    if order.get('reused'):                    # an older payment is still open: no new link is created
        bot.send_message(chat_id, f"⚠️ You already have an active payment.\n\n💎 {order['plan_name']} — pay exactly ₹{float(order['payable_amount']):.2f}\n"
                                  f"⏱️ Expires in about {mins} min\n🧾 Order: {order['order_id']}\n\n"
                                  f"Finish it first (or wait until it expires), then you can choose another plan.", reply_markup=markup)
        return
    _pid, name, price, bots, days = rows[0]
    caption = (f"💎 {name} — {bots} bots for {days} days\n\n💰 Pay exactly: ₹{float(order['payable_amount']):.2f}\n"
               f"⏱️ Valid for about {mins} min\n🧾 Order: {order['order_id']}\n\n"
               f"Scan the QR with any UPI app, or tap Pay Now. Your plan starts automatically after payment.")
    qr = order.get('qr_base64'); sent = False
    if qr:
        try:
            raw = base64.b64decode(qr.split(',', 1)[-1])
            bot.send_photo(chat_id, io.BytesIO(raw), caption=caption, reply_markup=markup); sent = True
        except Exception as e: logger.warning(f"QR send failed: {e}")
    if not sent: bot.send_message(chat_id, caption, reply_markup=markup)

def check_order_callback(call):
    oid = call.data.split('_', 1)[1]
    row = _db_exec("SELECT user_id FROM orders WHERE order_id=?", (oid,), fetch='one')
    if not row or (row[0] != call.from_user.id and call.from_user.id not in admin_ids):
        bot.answer_callback_query(call.id, "Order not found.", show_alert=True); return
    st = poll_order(oid)
    msg = {'paid': "✅ Paid — your plan is active!", 'pending': "⏳ Not paid yet. Finish the payment, then check again.",
           'expired': "⌛ This order expired. Create a new one.", 'cancelled': "❌ Order cancelled.",
           'failed': "❌ Payment failed."}.get(st, f"Status: {st}")
    bot.answer_callback_query(call.id, msg, show_alert=True)


# ============================================================================
#  v2 FEATURES  (B) server status · backup/restore · users · admin flows · menus
# ============================================================================

# ---------------------------------------------------------------- server status (CPU / RAM / disk)
def _read_text(path):
    try:
        with open(path, 'r') as f: return f.read().strip()
    except Exception:
        return None

def get_mem_info():
    """(used_bytes, total_bytes). Uses the container limit (cgroup) when there is one, else the machine."""
    cur, lim = _read_text('/sys/fs/cgroup/memory.current'), _read_text('/sys/fs/cgroup/memory.max')
    if cur and lim and cur.isdigit() and lim.isdigit():
        used = int(cur)
        stat = _read_text('/sys/fs/cgroup/memory.stat') or ''
        m = re.search(r'^inactive_file (\d+)', stat, re.M)
        if m: used = max(0, used - int(m.group(1)))      # cache the kernel can drop is not "used"
        return used, int(lim)
    cur, lim = _read_text('/sys/fs/cgroup/memory/memory.usage_in_bytes'), _read_text('/sys/fs/cgroup/memory/memory.limit_in_bytes')
    if cur and lim and cur.isdigit() and lim.isdigit() and int(lim) < (1 << 50):
        return int(cur), int(lim)
    vm = psutil.virtual_memory()
    return vm.total - vm.available, vm.total

def _file_size(path):
    try: return os.path.getsize(path)
    except OSError: return 0

def _app_cpu_percent():
    """CPU used by this bot + every hosted bot, measured over 0.5 s, in % of ONE core."""
    me = psutil.Process()
    procs = [me] + me.children(recursive=True)
    for p in procs:
        try: p.cpu_percent(None)
        except psutil.Error: pass
    time.sleep(0.5)
    total = 0.0
    for p in procs:
        try: total += p.cpu_percent(None)
        except psutil.Error: pass
    return total

def get_cpu_info():
    """(percent, basis). basis 'limit' = % of this container's CPU quota (cgroup), 'core' = % of one core used by this app."""
    def usage():
        m = re.search(r'^usage_usec (\d+)', _read_text('/sys/fs/cgroup/cpu.stat') or '', re.M)
        return int(m.group(1)) if m else None
    mx = (_read_text('/sys/fs/cgroup/cpu.max') or '').split()
    if len(mx) == 2 and mx[0].isdigit() and mx[1].isdigit() and int(mx[1]) > 0 and usage() is not None:
        cores = int(mx[0]) / int(mx[1])
        u0, w0 = usage(), time.time(); time.sleep(0.5); u1, w1 = usage(), time.time()
        if u1 is not None and w1 > w0 and cores > 0:
            return max(0.0, min(100.0, (u1 - u0) / ((w1 - w0) * 1e6) / cores * 100)), 'limit'
    return _app_cpu_percent(), 'core'

def system_snapshot():
    ru, rt = get_mem_info(); cpu, basis = get_cpu_info()
    data = dir_size(UPLOAD_BOTS_DIR) + _file_size(DATABASE_PATH)
    budget = int(get_num('storage_budget_mb') * 1048576)
    return {'cpu_pct': cpu, 'cpu_basis': basis, 'ram_used': ru, 'ram_total': rt, 'ram_pct': ru / rt * 100 if rt else 0,
            'data_bytes': data, 'budget_bytes': budget, 'data_pct': data / budget * 100 if budget else 0}

def level(pct): return '🚨' if pct >= 90 else '🔴' if pct >= 80 else '🟡' if pct >= 60 else '🟢'
def bar(pct, n=10):
    f = int(round(min(max(pct, 0), 100) / 100 * n)); return '█' * f + '░' * (n - f)
def _mb(b): return b / 1048576

def health_text(snap):
    pcts = [('CPU', snap['cpu_pct']), ('RAM', snap['ram_pct'])]
    if snap['budget_bytes']: pcts.append(('Storage', snap['data_pct']))
    crit = [n for n, p in pcts if p >= 90]; high = [n for n, p in pcts if 80 <= p < 90]
    if crit: return f"🚨 CRASH RISK — {', '.join(crit)} almost full!"
    if high: return f"🔴 High load — {', '.join(high)}"
    if any(p >= 60 for _n, p in pcts): return "🟡 Moderate load"
    return "🟢 All good"

def collect_bot_usage():
    """RAM + CPU of every running hosted bot (including its child processes)."""
    trees = []
    for _key, info in list(bot_scripts.items()):
        try:
            p = psutil.Process(info['process'].pid)
            tree = [p] + p.children(recursive=True)
            for q in tree:
                try: q.cpu_percent(None)
                except psutil.Error: pass
            trees.append((info, tree))
        except Exception:
            continue
    time.sleep(0.4)
    out = []
    for info, tree in trees:
        rss, cpu = 0, 0.0
        for q in tree:
            try: rss += q.memory_info().rss; cpu += q.cpu_percent(None)
            except psutil.Error: pass
        out.append({'owner': info.get('script_owner_id'), 'file': info.get('file_name'), 'rss': rss, 'cpu': cpu})
    return out

def _logic_statistics(message, user_id=None):
    uid = user_id or message.from_user.id
    if uid not in admin_ids:                      # users: only what matters to them
        lim = get_tier_limits(uid); status, extra = _status_line(uid)
        limit = get_user_file_limit(uid)
        usage = [u for u in collect_bot_usage() if u['owner'] == uid]
        storage = "" if lim['storage_mb'] is None else f" / {lim['storage_mb']:g} MB"
        _safe_reply(message, f"📊 Status\n\n🔰 Plan: {status}{extra}\n🤖 Bots: {get_user_file_count(uid)} / {'∞' if limit == float('inf') else limit}\n"
                             f"🟢 Running now: {len(usage)}\n📁 Storage: {_mb(dir_size(get_user_folder(uid))):.1f}{storage}\n"
                             f"📏 Max file: {lim['file_mb']:g} MB (zip {lim['zip_mb']:g} MB)")
        return
    snap = system_snapshot()
    usage = collect_bot_usage()
    basis = "of the container limit" if snap['cpu_basis'] == 'limit' else "used by this app, of 1 core"
    text = (f"📊 Server Status\n\n"
            f"🖥️ CPU  {level(snap['cpu_pct'])} {bar(snap['cpu_pct'])} {snap['cpu_pct']:.0f}%  ({basis})\n"
            f"🧠 RAM  {level(snap['ram_pct'])} {bar(snap['ram_pct'])} {snap['ram_pct']:.0f}%  ({_mb(snap['ram_used']):.0f}/{_mb(snap['ram_total']):.0f} MB)\n"
            f"💾 Bot data  {_mb(snap['data_bytes']):.1f} MB")
    if snap['budget_bytes']:
        text += f" / {_mb(snap['budget_bytes']):.0f} MB  {level(snap['data_pct'])} {bar(snap['data_pct'])} {snap['data_pct']:.0f}%"
    text += f"\n\n{health_text(snap)}\n"
    files_total = sum(len(f) for f in user_files.values())
    text += (f"\n👥 Users: {len(active_users)}   📂 Files: {files_total}\n"
             f"🟢 Running bots: {running_bots_total()} / {int(get_num('max_total_bots'))}\n"
             f"💎 Premium users: {sum(1 for u in user_subscriptions if is_premium(u))}   ⛔ Banned: {len(banned_ids)}\n"
             f"🔒 Lock: {lock_status_text(uid)}\n")
    top = sorted(usage, key=lambda x: -x['rss'])[:5]
    if top:
        text += "\n🏋️ Heaviest bots:\n" + "\n".join(
            f"{i}. {u['file']} (user {u['owner']}) — {_mb(u['rss']):.0f} MB, CPU {u['cpu']:.0f}%" for i, u in enumerate(top, 1))
    _safe_reply(message, text)

def resource_monitor():
    """Every minute: alert the owner if the server is nearly full, and keep hosted-bot logs small."""
    last_alert = 0
    while True:
        time.sleep(60)
        try:
            snap = system_snapshot()
            worst = max(snap['cpu_pct'], snap['ram_pct'], snap['data_pct'] if snap['budget_bytes'] else 0)
            if worst >= 90 and time.time() - last_alert > 1800:
                last_alert = time.time()
                top = sorted(collect_bot_usage(), key=lambda x: -x['rss'])[:3]
                _notify(OWNER_ID, f"🚨 Server almost full!\n{health_text(snap)}\nCPU {snap['cpu_pct']:.0f}% · RAM {snap['ram_pct']:.0f}% ({_mb(snap['ram_used']):.0f}/{_mb(snap['ram_total']):.0f} MB)\n" +
                        "\n".join(f"• {u['file']} (user {u['owner']}) {_mb(u['rss']):.0f} MB" for u in top))
            for _k, info in list(bot_scripts.items()):
                lp = os.path.join(info.get('user_folder', ''), f"{os.path.splitext(info.get('file_name', ''))[0]}.log")
                try:
                    if os.path.exists(lp) and os.path.getsize(lp) > LOG_MAX_BYTES: os.truncate(lp, 0)
                except OSError: pass
        except Exception as e:
            logger.error(f"resource_monitor error: {e}", exc_info=True)


# ---------------------------------------------------------------- backup & restore
BACKUP_PART_LIMIT = 15 * 1024 * 1024   # keep every part under 20 MB so the bot can download it again for restore
BACKUP_SKIP_DIRS = {'node_modules', '__pycache__', '.git', 'venv', '.venv'}
BACKUP_SKIP_FILES = {'.requirements.md5'}
MERGE_TABLES = ['subscriptions', 'user_files', 'active_users', 'autostart', 'admins', 'plans', 'orders',
                'settings', 'banned', 'expired_stopped']
restore_armed_until = 0.0

def _iter_user_files(folder):
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in BACKUP_SKIP_DIRS]
        for f in files:
            if f in BACKUP_SKIP_FILES or f.endswith('.log'): continue
            ap = os.path.join(root, f)
            yield ap, os.path.relpath(ap, folder).replace(os.sep, '/')

def create_backup_parts():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp = tempfile.mkdtemp(prefix='backup_')
    db_copy = os.path.join(tmp, 'bot_data.db')
    with DB_LOCK:
        src = sqlite3.connect(DATABASE_PATH, check_same_thread=False); dst = sqlite3.connect(db_copy)
        try: src.backup(dst)
        finally: dst.close(); src.close()
    parts, state = [], {'n': 0, 'zf': None, 'path': None}
    def open_part():
        state['n'] += 1
        state['path'] = os.path.join(tmp, f"backup_{ts}_part{state['n']}.zip")
        state['zf'] = zipfile.ZipFile(state['path'], 'w', zipfile.ZIP_DEFLATED)
        parts.append(state['path'])
    open_part()
    state['zf'].write(db_copy, 'bot_data.db')
    state['zf'].writestr('meta.json', json.dumps({'created': datetime.now().isoformat(), 'bot': 'file-host-v2',
                                                  'users': len(user_files)}))
    for uid_dir in sorted(os.listdir(UPLOAD_BOTS_DIR)):
        full = os.path.join(UPLOAD_BOTS_DIR, uid_dir)
        if not os.path.isdir(full): continue
        if state['zf'].fp: state['zf'].fp.flush()
        if os.path.getsize(state['path']) > BACKUP_PART_LIMIT:
            state['zf'].close(); open_part()
        for ap, rel in _iter_user_files(full):
            state['zf'].write(ap, f"upload_bots/{uid_dir}/{rel}")
    state['zf'].close()
    return parts, tmp

def run_backup(reason='auto', chat_id=None):
    chat_id = chat_id or OWNER_ID
    parts, tmp = create_backup_parts()
    try:
        for i, p in enumerate(parts, 1):
            size = os.path.getsize(p)
            note = "" if size < 20 * 1024 * 1024 else "\n⚠️ Over 20 MB: Telegram bots cannot download this file back for restore."
            with open(p, 'rb') as f:
                bot.send_document(chat_id, f, timeout=180,
                                  caption=f"💾 Backup ({reason}) — part {i}/{len(parts)} — {size / 1048576:.1f} MB\n"
                                          f"🕒 {datetime.now():%Y-%m-%d %H:%M}\n🔐 Contains users' files and bot tokens — keep it private.{note}")
        set_setting('last_backup', datetime.now().isoformat())
        return len(parts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def backup_scheduler():
    time.sleep(90)
    while True:
        try:
            last = get_setting('last_backup')
            if not last or datetime.now() - datetime.fromisoformat(last) >= timedelta(hours=24):
                run_backup('automatic 24h')
        except Exception as e:
            logger.error(f"backup_scheduler error: {e}", exc_info=True)
            _notify(OWNER_ID, f"⚠️ Automatic backup failed: {e}")
        time.sleep(1800)

def _merge_db(backup_db):
    notes = []
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            conn.execute("ATTACH DATABASE ? AS bk", (backup_db,))
            for t in MERGE_TABLES:
                try:
                    live = [r[1] for r in conn.execute(f"PRAGMA main.table_info({t})")]
                    old = [r[1] for r in conn.execute(f"PRAGMA bk.table_info({t})")]
                    cols = ','.join(c for c in live if c in old)
                    if not cols: continue
                    verb = 'INSERT OR IGNORE' if t == 'orders' else 'INSERT OR REPLACE'   # never re-open a paid order
                    n = conn.execute(f"{verb} INTO main.{t} ({cols}) SELECT {cols} FROM bk.{t}").rowcount
                    notes.append(f"{t}:{n}")
                except sqlite3.Error as e:
                    notes.append(f"{t}: skipped ({e})")
            conn.commit()
            conn.execute("DETACH DATABASE bk")
        finally:
            conn.close()
    return ', '.join(notes)

def reload_memory():
    user_files.clear(); user_subscriptions.clear(); active_users.clear()
    admin_ids.clear(); admin_ids.update({ADMIN_ID, OWNER_ID})
    load_data(); load_settings(); load_banned()

def restore_from_zip_bytes(data):
    tmp = tempfile.mkdtemp(prefix='restore_')
    try:
        zpath = os.path.join(tmp, 'b.zip')
        with open(zpath, 'wb') as f: f.write(data)
        base = os.path.abspath(UPLOAD_BOTS_DIR); files_n = 0; has_db = False
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            if 'meta.json' not in names: raise ValueError("this is not a backup made by this bot")
            if sum(i.file_size for i in zf.infolist()) > 500 * 1024 * 1024: raise ValueError("backup is unreasonably large")
            for n in names:
                norm = os.path.normpath(n)
                if n.startswith('/') or norm.startswith('..') or os.path.isabs(norm):
                    raise ValueError(f"unsafe path in backup: {n}")
                if not (n in ('bot_data.db', 'meta.json') or n.startswith('upload_bots/')):
                    raise ValueError(f"unexpected entry in backup: {n}")
            for info in zf.infolist():
                n = info.filename
                if info.is_dir(): continue
                if n == 'bot_data.db':
                    zf.extract(n, tmp); has_db = True
                elif n.startswith('upload_bots/'):
                    dest = os.path.abspath(os.path.join(UPLOAD_BOTS_DIR, n[len('upload_bots/'):]))
                    if not dest.startswith(base + os.sep): raise ValueError(f"unsafe path in backup: {n}")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(info) as s_, open(dest, 'wb') as d_: shutil.copyfileobj(s_, d_)
                    files_n += 1
        db_note = _merge_db(os.path.join(tmp, 'bot_data.db')) if has_db else "no database in this part"
        reload_memory()
        threading.Thread(target=autostart_all, daemon=True).start()
        return f"✅ Restored.\n📂 Files: {files_n}\n🗄️ Database: {db_note}\n♻️ Bots that were running will start again in a few seconds."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def restore_armed(): return time.time() < restore_armed_until

def handle_restore_upload(message):
    global restore_armed_until
    doc = message.document
    if not (doc.file_name or '').lower().endswith('.zip'):
        bot.reply_to(message, "⚠️ Send the backup .zip file."); return
    if doc.file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "⚠️ This file is over 20 MB — the bot cannot download it. Restore parts are kept under 20 MB."); return
    wait = bot.reply_to(message, "⏳ Restoring backup...")
    try:
        data = bot.download_file(bot.get_file(doc.file_id).file_path)
        result = restore_from_zip_bytes(data)
    except Exception as e:
        logger.error(f"restore failed: {e}", exc_info=True)
        result = f"❌ Restore failed: {e}"
    restore_armed_until = time.time() + 600
    mk = types.InlineKeyboardMarkup(); mk.add(CInlineButton('✅ Done', callback_data='restore_done'))
    bot.edit_message_text(result + "\n\nSend the next part, or tap Done.", wait.chat.id, wait.message_id, reply_markup=mk)

def backup_now_callback(call):
    bot.answer_callback_query(call.id, "⏳ Creating backup...")
    try:
        n = run_backup('manual', call.message.chat.id)
        bot.send_message(call.message.chat.id, f"✅ Backup sent ({n} file(s)).")
    except Exception as e:
        logger.error(f"manual backup failed: {e}", exc_info=True)
        bot.send_message(call.message.chat.id, f"❌ Backup failed: {e}")

def restore_backup_callback(call):
    global restore_armed_until
    restore_armed_until = time.time() + 600
    bot.answer_callback_query(call.id)
    mk = types.InlineKeyboardMarkup(); mk.add(CInlineButton('✅ Done', callback_data='restore_done'))
    bot.send_message(call.message.chat.id, "♻️ Restore mode is ON for 10 minutes.\nSend the backup .zip file now (all parts, one by one). Existing data is merged, nothing is wiped.", reply_markup=mk)

def restore_done_callback(call):
    global restore_armed_until
    restore_armed_until = 0.0
    bot.answer_callback_query(call.id, "Restore mode off.")


# ---------------------------------------------------------------- users (admin) : list / view / remove / ban
USERS_PER_PAGE = 8

def can_manage(requester_id, owner_id):
    """Users manage their own bots; the owner manages everybody; admins manage everybody except admins/owner."""
    if requester_id == owner_id or requester_id == OWNER_ID: return True
    return requester_id in admin_ids and owner_id not in admin_ids

def _user_running_count(uid):
    return sum(1 for fn, _ft in user_files.get(uid, []) if is_bot_running(uid, fn))

def ulist_callback(call):
    try: page = max(0, int(call.data.split('_', 1)[1]))
    except (ValueError, IndexError): page = 0
    ids = sorted(set(active_users) | set(user_files) | set(user_subscriptions) | set(banned_ids),
                 key=lambda u: (-len(user_files.get(u, [])), u))
    pages = max(1, (len(ids) + USERS_PER_PAGE - 1) // USERS_PER_PAGE); page = min(page, pages - 1)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for uid in ids[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]:
        run = _user_running_count(uid)
        icon = '⛔' if uid in banned_ids else '🟢' if run else '⚪'
        tag = ' ⭐' if is_premium(uid) else ' 🛡️' if uid in admin_ids else ''
        markup.add(CInlineButton(f"{icon} {uid} · {len(user_files.get(uid, []))} files{tag}", callback_data=f'uview_{uid}',
                                 style='danger' if uid in banned_ids else 'success' if run else 'primary'))
    nav = []
    if page > 0: nav.append(CInlineButton('◀ Prev', callback_data=f'ulist_{page - 1}'))
    if page < pages - 1: nav.append(CInlineButton('Next ▶', callback_data=f'ulist_{page + 1}'))
    if nav: markup.row(*nav)
    markup.add(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    bot.answer_callback_query(call.id)
    text = f"👥 Users ({len(ids)})  —  page {page + 1}/{pages}\n🟢 running · ⚪ idle · ⛔ banned · ⭐ premium"
    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e: logger.warning(f"ulist edit: {e}")

def uview_callback(call):
    try: uid = int(call.data.split('_', 1)[1])
    except (ValueError, IndexError): bot.answer_callback_query(call.id, "Invalid user."); return
    status, extra = _status_line(uid)
    lim = get_user_file_limit(uid)
    text = (f"👤 User {uid}\n🔰 {status}{extra}{' · ⛔ BANNED' if uid in banned_ids else ''}\n"
            f"📁 Files: {len(user_files.get(uid, []))} / {lim if lim != float('inf') else '∞'}   🟢 Running: {_user_running_count(uid)}\n"
            f"💾 Storage: {_mb(dir_size(get_user_folder(uid))):.1f} MB")
    markup = types.InlineKeyboardMarkup(row_width=1)
    for fn, ft in sorted(user_files.get(uid, [])):
        run = is_bot_running(uid, fn)
        markup.add(CInlineButton(f"{fn} ({ft}) - {'🟢 Running' if run else '🔴 Stopped'}", callback_data=f'file_{uid}_{fn}',
                                 style='success' if run else 'danger'))
    if can_manage(call.from_user.id, uid) and uid != call.from_user.id:
        if user_files.get(uid): markup.add(CInlineButton('🗑️ Delete All Files', callback_data=f'delall_{uid}'))
        if uid not in admin_ids:
            markup.add(CInlineButton('✅ Unban User' if uid in banned_ids else '⛔ Ban User',
                                     callback_data=f'unban_{uid}' if uid in banned_ids else f'ban_{uid}'))
    markup.add(CInlineButton('🔙 Back to Users', callback_data='ulist_0'))
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception as e: logger.warning(f"uview edit: {e}")

def delete_all_user_files(uid):
    n = len(user_files.get(uid, []))
    for fn, _ft in list(user_files.get(uid, [])):
        _stop_script(uid, fn)
        remove_user_file_db(uid, fn)
    shutil.rmtree(os.path.join(UPLOAD_BOTS_DIR, str(uid)), ignore_errors=True)
    _db_exec("DELETE FROM expired_stopped WHERE user_id = ?", (uid,))
    return n

def delask_callback(call):
    try: _, uid, fn = call.data.split('_', 2); uid = int(uid)
    except (ValueError, IndexError): bot.answer_callback_query(call.id, "Invalid data."); return
    if not can_manage(call.from_user.id, uid): bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
    bot.answer_callback_query(call.id)
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(CInlineButton('✅ Yes, delete', callback_data=f'delete_{uid}_{fn}'), CInlineButton('❌ Cancel', callback_data=f'file_{uid}_{fn}'))
    bot.edit_message_text(f"⚠️ Delete `{fn}` of user {uid}? The file, its log and its auto-start are removed.",
                          call.message.chat.id, call.message.message_id, reply_markup=mk, parse_mode='Markdown')

def delall_callback(call):
    uid = int(call.data.split('_', 1)[1])
    if not can_manage(call.from_user.id, uid) or uid == call.from_user.id:
        bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
    bot.answer_callback_query(call.id)
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(CInlineButton('✅ Yes, delete all', callback_data=f'delallyes_{uid}'), CInlineButton('❌ Cancel', callback_data=f'uview_{uid}'))
    bot.edit_message_text(f"⚠️ Delete ALL files of user {uid} and stop all their bots?", call.message.chat.id, call.message.message_id, reply_markup=mk)

def delallyes_callback(call):
    uid = int(call.data.split('_', 1)[1])
    if not can_manage(call.from_user.id, uid) or uid == call.from_user.id:
        bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
    n = delete_all_user_files(uid)
    bot.answer_callback_query(call.id, f"🗑️ {n} file(s) removed.")
    _notify(uid, "🗑️ All your hosted files were removed by an admin.")
    mk = types.InlineKeyboardMarkup(); mk.add(CInlineButton('🔙 Back to Users', callback_data='ulist_0'))
    bot.edit_message_text(f"🗑️ Removed {n} file(s) of user {uid}.", call.message.chat.id, call.message.message_id, reply_markup=mk)

def ban_callback(call, ban):
    uid = int(call.data.split('_', 1)[1])
    if uid in admin_ids or uid == call.from_user.id:
        bot.answer_callback_query(call.id, "⚠️ You cannot ban an admin or yourself.", show_alert=True); return
    if ban:
        banned_ids.add(uid); _db_exec("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (uid,))
        for fn, _ft in list(user_files.get(uid, [])): _stop_script(uid, fn)
        _notify(uid, "⛔ You have been banned from this bot. Your bots were stopped.")
    else:
        banned_ids.discard(uid); _db_exec("DELETE FROM banned WHERE user_id = ?", (uid,))
        _notify(uid, "✅ Your ban was lifted. You can use the bot again.")
    bot.answer_callback_query(call.id, "⛔ Banned." if ban else "✅ Unbanned.")
    call.data = f'uview_{uid}'; uview_callback(call)


# ---------------------------------------------------------------- admin flows: plans / give plan / limits / gateway / payments
def _ask(chat_id, prompt, handler, *args):
    msg = bot.send_message(chat_id, prompt)
    bot.register_next_step_handler(msg, handler, *args)

def _cancelled(message): return (message.text or '').strip().lower() == '/cancel'
def _is_admin_msg(message): return message.from_user.id in admin_ids

def plans_admin_callback(call):
    bot.answer_callback_query(call.id)
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(CInlineButton('➕ Add Plan', callback_data='plan_add'), CInlineButton('✏️ Edit Plan', callback_data='plan_edit'))
    mk.row(CInlineButton('➖ Delete Plan', callback_data='plan_del'))
    mk.row(CInlineButton('🔍 Check User Plan', callback_data='check_subscription'), CInlineButton('❌ Remove User Plan', callback_data='remove_subscription'))
    mk.row(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    try: bot.edit_message_text(plans_text(), call.message.chat.id, call.message.message_id, reply_markup=mk)
    except Exception as e: logger.warning(f"plans_admin edit: {e}")

def _parse_plan(parts):
    name = parts[0].strip()
    if not name or len(name) > 30: raise ValueError("name must be 1-30 characters")
    price, bots, days = float(parts[1]), int(parts[2]), int(parts[3])
    if price <= 0 or bots <= 0 or days <= 0: raise ValueError("price, bots and days must be above 0")
    return name, price, bots, days

def plan_add_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, "➕ Send the plan as:\nname | price | bots | days\nExample: Basic | 99 | 3 | 30\n\n/cancel to abort", process_plan_add)

def process_plan_add(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    try:
        parts = (message.text or '').split('|')
        if len(parts) != 4: raise ValueError("use: name | price | bots | days")
        name, price, bots, days = _parse_plan(parts)
        _db_exec("INSERT INTO plans (name, price, bots, days) VALUES (?, ?, ?, ?)", (name, price, bots, days))
        bot.reply_to(message, "✅ Plan added.\n\n" + plans_text())
    except ValueError as e:
        _ask(message.chat.id, f"⚠️ {e}\nTry again or /cancel.", process_plan_add)

def plan_edit_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, f"{plans_text()}\n\n✏️ Send:\nid | name | price | bots | days\nExample: 2 | Pro | 199 | 10 | 30\n\n/cancel to abort", process_plan_edit)

def process_plan_edit(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    try:
        parts = (message.text or '').split('|')
        if len(parts) != 5: raise ValueError("use: id | name | price | bots | days")
        pid = int(parts[0]); name, price, bots, days = _parse_plan(parts[1:])
        if _db_exec("UPDATE plans SET name=?, price=?, bots=?, days=? WHERE id=?", (name, price, bots, days, pid)) != 1:
            raise ValueError(f"no plan with id {pid}")
        bot.reply_to(message, "✅ Plan updated.\n\n" + plans_text())
    except ValueError as e:
        _ask(message.chat.id, f"⚠️ {e}\nTry again or /cancel.", process_plan_edit)

def plan_del_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, f"{plans_text()}\n\n➖ Send the plan ID to delete (running subscriptions are not affected).\n/cancel to abort", process_plan_del)

def process_plan_del(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    try:
        pid = int((message.text or '').strip())
        if _db_exec("DELETE FROM plans WHERE id=?", (pid,)) != 1: raise ValueError(f"no plan with id {pid}")
        bot.reply_to(message, "✅ Plan deleted.\n\n" + plans_text())
    except ValueError as e:
        _ask(message.chat.id, f"⚠️ {e}\nSend a plan ID or /cancel.", process_plan_del)

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, f"🎁 Give a plan to a user.\nSend: user_id plan_id\nExample: 12345678 2\n\n{plans_text()}\n\n/cancel to abort", process_give_plan)

def process_give_plan(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    try:
        parts = (message.text or '').split()
        if len(parts) != 2: raise ValueError("use: user_id plan_id")
        uid, pid = int(parts[0]), int(parts[1])
        if uid <= 0: raise ValueError("user id must be positive")
        rows = _db_exec("SELECT id, name, price, bots, days FROM plans WHERE id=?", (pid,), fetch='all')
        if not rows: raise ValueError(f"no plan with id {pid}")
        _i, name, _p, bots, days = rows[0]
        expiry = activate_plan(uid, name, bots, days)
        bot.reply_to(message, f"✅ {name} given to {uid}: {bots} bots until {expiry:%Y-%m-%d}.")
        _notify(uid, f"🎉 {name} plan activated: {bots} bots until {expiry:%Y-%m-%d}.")
    except ValueError as e:
        _ask(message.chat.id, f"⚠️ {e}\nTry again or /cancel.", process_give_plan)

LIMIT_LABELS = [
    ('free_bot_limit', '🆓 Free bots'), ('max_total_bots', '🤖 Max running bots'),
    ('free_max_file_mb', '🆓 Script MB'), ('free_max_zip_mb', '🆓 ZIP MB'), ('free_storage_mb', '🆓 Storage MB'),
    ('paid_max_file_mb', '⭐ Script MB'), ('paid_max_zip_mb', '⭐ ZIP MB'), ('paid_storage_mb', '⭐ Storage MB'),
    ('storage_budget_mb', '💽 Disk budget MB'),
]

def limits_admin_callback(call):
    bot.answer_callback_query(call.id)
    budget = get_num('storage_budget_mb')
    budget_txt = 'off (real disk)' if budget <= 0 else f"{budget:g} MB"
    text = ("⚙️ Limits\n\n"
            f"🆓 Free: {int(get_num('free_bot_limit'))} bot · script {get_num('free_max_file_mb'):g} MB · ZIP {get_num('free_max_zip_mb'):g} MB · storage {get_num('free_storage_mb'):g} MB\n"
            f"⭐ Premium: script {get_num('paid_max_file_mb'):g} MB · ZIP {get_num('paid_max_zip_mb'):g} MB · storage {get_num('paid_storage_mb'):g} MB\n"
            f"🤖 Max running bots on the server: {int(get_num('max_total_bots'))}\n"
            f"💽 Disk budget for Status: {budget_txt}\n"
            "\nHeavy packages (torch, tensorflow, opencv, selenium ...) are premium-only.\nTap a value to change it.")
    mk = types.InlineKeyboardMarkup(row_width=2)
    btns = [CInlineButton(f"{label}: {get_setting(key)}", callback_data=f'setlim_{key}', style='primary') for key, label in LIMIT_LABELS]
    mk.add(*btns)
    mk.row(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mk)
    except Exception as e: logger.warning(f"limits edit: {e}")

def setlim_callback(call):
    key = call.data.split('_', 1)[1]
    label = dict(LIMIT_LABELS).get(key)
    if not label: bot.answer_callback_query(call.id, "Unknown setting."); return
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, f"{label} — now {get_setting(key)}.\nSend the new number.\n/cancel to abort", process_setlim, key)

def process_setlim(message, key):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    try:
        v = float((message.text or '').strip().replace(',', '.'))
        whole = key in ('free_bot_limit', 'max_total_bots')
        if v < 0 or (v == 0 and key not in ('free_bot_limit', 'storage_budget_mb')): raise ValueError("value must be above 0 (0 is allowed only for Free bots and Disk budget)")
        note = ""
        if key in ('paid_max_file_mb', 'paid_max_zip_mb') and v > 20:
            v = 20; note = "\n(Capped at 20 MB — the Telegram Bot API cannot download bigger files.)"
        set_setting(key, int(v) if whole else (int(v) if v == int(v) else v))
        bot.reply_to(message, f"✅ Saved: {dict(LIMIT_LABELS)[key]} = {get_setting(key)}{note}")
    except ValueError as e:
        _ask(message.chat.id, f"⚠️ {e}\nSend a number or /cancel.", process_setlim, key)

def gw_menu_callback(call):
    bot.answer_callback_query(call.id)
    text = (f"🔑 MinorUPI Gateway\n\n🌐 Base URL: {get_setting('minorupi_base_url') or '(not set)'}\n"
            f"🔐 API key: {mask_key(get_setting('minorupi_api_key'))}\n"
            f"{'✅ Ready — payments are on' if gateway_ready() else '⚠️ Not configured — payments are off'}")
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(CInlineButton('🌐 Set Base URL', callback_data='gw_url'), CInlineButton('🔑 Set API Key', callback_data='gw_key'))
    mk.row(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mk)
    except Exception as e: logger.warning(f"gw edit: {e}")

def gw_url_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, "🌐 Send the gateway base URL (example: https://minorupi.onvoroa.com)\n/cancel to abort", process_gw_url)

def process_gw_url(message):
    if message.from_user.id != OWNER_ID or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    url = (message.text or '').strip().rstrip('/')
    if not re.match(r'^https?://[^\s/]+', url):
        _ask(message.chat.id, "⚠️ Send a full URL starting with https:// or /cancel.", process_gw_url); return
    set_setting('minorupi_base_url', url)
    bot.reply_to(message, f"✅ Base URL saved: {url}" + ("\n⚠️ Not HTTPS — use https:// for real payments." if url.startswith('http://') else ""))

def gw_key_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, "🔑 Send the gateway API key. I delete your message right after saving it.\n/cancel to abort", process_gw_key)

def process_gw_key(message):
    if message.from_user.id != OWNER_ID or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    key = (message.text or '').strip()
    try: bot.delete_message(message.chat.id, message.message_id)
    except Exception: pass
    if len(key) < 8 or re.search(r'\s', key):
        _ask(message.chat.id, "⚠️ That does not look like an API key. Send it again or /cancel.", process_gw_key); return
    set_setting('minorupi_api_key', key)
    bot.send_message(message.chat.id, f"✅ API key saved: {mask_key(key)}\n(Your message with the key was deleted.)")

def payments_admin_callback(call):
    bot.answer_callback_query(call.id)
    n, total = _db_exec("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM orders WHERE status='paid'", fetch='one')
    pend = _db_exec("SELECT COUNT(*) FROM orders WHERE status='pending'", fetch='one')[0]
    rows = _db_exec("SELECT amount, plan_name, user_id, status, created FROM orders ORDER BY created DESC LIMIT 8", fetch='all')
    icon = {'paid': '✅', 'pending': '⏳'}
    lines = [f"{icon.get(st, '❌')} {fmt_price(a)} {pn} · {u} · {c[5:16]}" for a, pn, u, st, c in rows]
    text = f"💰 Payments\n\n✅ Paid orders: {n}   💵 Total: {fmt_price(total)}\n⏳ Waiting: {pend}\n\n" + ("\n".join(lines) if lines else "No orders yet.")
    mk = types.InlineKeyboardMarkup(); mk.add(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    try: bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mk)
    except Exception as e: logger.warning(f"payments edit: {e}")


# ---------------------------------------------------------------- lock handlers (Lock Free / Lock All)
def lock_set_callback(call, kind, value):
    set_setting('lock_free' if kind == 'free' else 'lock_all', '1' if value else '0')
    logger.warning(f"Admin {call.from_user.id}: lock {kind} = {value}")
    bot.answer_callback_query(call.id, f"{'🔒 Locked' if value else '🔓 Unlocked'}: {'free users' if kind == 'free' else 'ALL users'}")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error updating menu (lock): {e}")

def _logic_toggle_lock(message, kind):
    uid = message.from_user.id
    if uid not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    key = 'lock_free' if kind == 'free' else 'lock_all'
    now_locked = get_setting(key) != '1'
    set_setting(key, '1' if now_locked else '0')
    logger.warning(f"Admin {uid}: lock {kind} = {now_locked}")
    bot.send_message(message.chat.id, f"{'🔒 Locked' if now_locked else '🔓 Unlocked'}: {'free users' if kind == 'free' else 'ALL users (premium too)'}.",
                     reply_markup=create_reply_keyboard_main_menu(uid))   # resend keyboard so the button label flips

# banned users are stopped before any other handler sees the message
@bot.message_handler(func=lambda m: bool(m.from_user) and m.from_user.id in banned_ids,
                     content_types=['text', 'document', 'photo', 'video', 'audio', 'voice', 'sticker'])
def banned_message(message):
    bot.reply_to(message, "⛔ You are banned from using this bot.")


# ---------------------------------------------------------------- start-up of the new tables / values
load_settings()
load_banned()


# ============================================================================
#  v3 FEATURES  (C) force join · admin panel on the keyboard · lock center · run-all switch
# ============================================================================
class _MsgCall:
    """Lets a keyboard-button press reuse the inline screens: no callback to answer, and 'edit' becomes a new message."""
    def __init__(self, message, data=''):
        self.id = None; self.data = data; self.from_user = message.from_user
        self.message = _NS(chat=message.chat, message_id=None)

def _admin_screen(message, func, data='', owner_only=False):
    uid = message.from_user.id
    if owner_only and uid != OWNER_ID: bot.reply_to(message, "⚠️ Owner only."); return
    if uid not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    func(_MsgCall(message, data))


# ---------------------------------------------------------------- force join (channels / groups set from the admin panel)
FJ_CACHE_SECONDS = 300
_fj_cache = {}        # user_id -> time until which "already joined" is trusted (saves Telegram API calls)
_fj_warned = set()

def get_force_channels():
    try: lst = json.loads(get_setting('force_channels') or '[]')
    except ValueError: lst = []
    return [c for c in lst if isinstance(c, dict) and c.get('id')]

def force_join_missing(user_id, use_cache=True):
    """Channels this user still has to join (empty list = all good). Admins are never asked."""
    if user_id in admin_ids or get_setting('force_on') != '1': return []
    chans = get_force_channels()
    if not chans: return []
    if use_cache and _fj_cache.get(user_id, 0) > time.time(): return []
    missing = []
    for ch in chans:
        try:
            m = bot.get_chat_member(ch['id'], user_id)
            if m.status in ('left', 'kicked') or (m.status == 'restricted' and getattr(m, 'is_member', True) is False):
                missing.append(ch)
        except Exception as e:      # a broken channel must never lock everybody out: skip it and tell the owner once
            logger.warning(f"force-join check failed for {ch['id']}: {e}")
            if ch['id'] not in _fj_warned:
                _fj_warned.add(ch['id'])
                _notify(OWNER_ID, f"⚠️ Force Join: I cannot check {ch.get('title') or ch['id']} ({e}). Make sure the bot is an admin there.")
    if not missing: _fj_cache[user_id] = time.time() + FJ_CACHE_SECONDS
    return missing

def send_force_join_prompt(chat_id, missing):
    mk = types.InlineKeyboardMarkup(row_width=1)
    names = []
    for ch in missing:
        names.append(f"• {ch.get('title') or ch['id']}")
        if ch.get('link'): mk.add(CInlineButton(f"📢 Join {ch.get('title') or 'Channel'}", url=ch['link'], style='primary'))
    mk.add(CInlineButton("✅ I've Joined", callback_data='fj_check', style='success'))
    bot.send_message(chat_id, "🔒 To use this bot you must join:\n\n" + "\n".join(names) + "\n\nJoin, then tap ✅ I've Joined.", reply_markup=mk)

# runs before every other handler: not-joined users only ever see the join prompt (this also covers /start)
@bot.message_handler(func=lambda m: bool(m.from_user) and bool(force_join_missing(m.from_user.id)),
                     content_types=['text', 'document', 'photo', 'video', 'audio', 'voice', 'sticker'])
def force_join_message(message):
    missing = force_join_missing(message.from_user.id)
    if missing: send_force_join_prompt(message.chat.id, missing)

def fj_check_callback(call):
    uid = call.from_user.id
    missing = force_join_missing(uid, use_cache=False)
    if missing:
        bot.answer_callback_query(call.id, "❌ You have not joined yet: " + ", ".join(c.get('title') or str(c['id']) for c in missing), show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ Thanks! Welcome.")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception: pass
    _logic_send_welcome(_NS(from_user=call.from_user, chat=call.message.chat, message_id=None))

def fj_text():
    chans = get_force_channels(); on = get_setting('force_on') == '1'
    lines = [f"{i}. {c.get('title')} ({c['id']})" + ('' if c.get('link') else ' ⚠️ no join link') for i, c in enumerate(chans, 1)]
    return (f"📢 Force Join — {'🟢 ON' if on else '🔴 OFF'}\n\n" + ("\n".join(lines) if lines else "No channel or group added yet.") +
            "\n\nUsers must join all of these before they can use the bot. The bot must be an admin in each one.")

def fj_menu_callback(call):
    bot.answer_callback_query(call.id)
    on = get_setting('force_on') == '1'
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(CInlineButton('➕ Add Channel/Group', callback_data='fj_add'), CInlineButton('➖ Remove', callback_data='fj_del'))
    mk.row(CInlineButton('🔴 Turn OFF' if on else '🟢 Turn ON', callback_data='fj_toggle', style='danger' if on else 'success'))
    mk.row(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    try: bot.edit_message_text(fj_text(), call.message.chat.id, call.message.message_id, reply_markup=mk)
    except Exception as e: logger.warning(f"fj menu edit: {e}")

def fj_toggle_callback(call):
    set_setting('force_on', '0' if get_setting('force_on') == '1' else '1'); _fj_cache.clear()
    fj_menu_callback(call)

def fj_add_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, "➕ Send the channel/group @username or numeric ID — or forward any message from it.\n"
                               "The bot must already be an admin there.\n\n/cancel to abort", process_fj_add)

def process_fj_add(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    ref = None
    fc = getattr(message, 'forward_from_chat', None)
    if fc is not None: ref = fc.id
    else:
        t = (message.text or '').strip()
        if re.fullmatch(r'-?\d{5,}', t): ref = int(t)
        elif re.fullmatch(r'@?[A-Za-z][A-Za-z0-9_]{3,}', t): ref = '@' + t.lstrip('@')
    if ref is None:
        _ask(message.chat.id, "⚠️ Send an @username, a numeric ID, or forward a message from the channel. /cancel to abort.", process_fj_add); return
    try:
        chat = bot.get_chat(ref)
        status = bot.get_chat_member(chat.id, bot.get_me().id).status
        if status not in ('administrator', 'creator'): raise ValueError("the bot is not an admin there")
    except Exception as e:
        _ask(message.chat.id, f"⚠️ I cannot use that chat ({e}).\nAdd the bot as admin first, then send it again. /cancel to abort.", process_fj_add); return
    chans = get_force_channels()
    if any(c['id'] == chat.id for c in chans): bot.reply_to(message, "ℹ️ That chat is already in the list."); return
    if len(chans) >= 5: bot.reply_to(message, "⚠️ Maximum 5 channels/groups."); return
    link = f"https://t.me/{chat.username}" if getattr(chat, 'username', None) else None
    if not link:
        try: link = bot.export_chat_invite_link(chat.id)
        except Exception: link = None
    chans.append({'id': chat.id, 'title': (chat.title or str(chat.id))[:40], 'link': link})
    set_setting('force_channels', json.dumps(chans)); _fj_cache.clear()
    bot.reply_to(message, f"✅ Added: {chat.title or chat.id}" + ("" if link else "\n⚠️ No join link (private chat): users will only see its name. Use a public @username or give the bot the 'invite users' right."))

def fj_del_callback(call):
    bot.answer_callback_query(call.id)
    _ask(call.message.chat.id, f"{fj_text()}\n\n➖ Send the number to remove.\n/cancel to abort", process_fj_del)

def process_fj_del(message):
    if not _is_admin_msg(message) or _cancelled(message): bot.reply_to(message, "Cancelled."); return
    chans = get_force_channels()
    try:
        i = int((message.text or '').strip())
        if not 1 <= i <= len(chans): raise ValueError("no such number")
    except ValueError:
        _ask(message.chat.id, "⚠️ Send a number from the list, or /cancel.", process_fj_del); return
    gone = chans.pop(i - 1)
    set_setting('force_channels', json.dumps(chans)); _fj_cache.clear()
    bot.reply_to(message, f"✅ Removed: {gone.get('title')}\n\n{fj_text()}")


# ---------------------------------------------------------------- admin panel (keyboard) : screens + lock center + run-all switch
def _logic_main_menu(message):
    bot.send_message(message.chat.id, "🏠 Main Menu", reply_markup=create_reply_keyboard_main_menu(message.from_user.id))

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required."); return
    bot.send_message(message.chat.id, "👑 Admin Panel", reply_markup=create_admin_reply_keyboard(message.from_user.id))

def admin_panel_callback(call):                 # "🔙 Back to Admin" inside inline screens
    bot.answer_callback_query(call.id)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception: pass
    bot.send_message(call.message.chat.id, "👑 Admin Panel", reply_markup=create_admin_reply_keyboard(call.from_user.id))

def admins_menu_callback(call):
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text("🛡️ Admins\n\nOnly the owner can add or remove admins.", call.message.chat.id,
                               call.message.message_id, reply_markup=create_admin_panel(call.from_user.id))
    except Exception as e: logger.warning(f"admins menu edit: {e}")

def lock_status_block():
    lf, la = get_setting('lock_free') == '1', get_setting('lock_all') == '1'
    return (f"🆓 Free users: {'🔒 Locked' if (lf or la) else '🔓 Open'}\n"
            f"⭐ Premium users: {'🔒 Locked' if la else '🔓 Open'}\n🛡️ Admins are never locked.")

def _logic_lock_center(message):
    if message.from_user.id not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    bot.send_message(message.chat.id, "🔒 Lock Center\n\n" + lock_status_block() + "\n\nChoose below 👇", reply_markup=create_lock_keyboard())

def _logic_lock_status(message):
    if message.from_user.id not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    bot.send_message(message.chat.id, "📋 Lock Status\n\n" + lock_status_block(), reply_markup=create_lock_keyboard())

def _logic_set_lock(message, kind, value):
    uid = message.from_user.id
    if uid not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    set_setting('lock_free' if kind == 'free' else 'lock_all', '1' if value else '0')
    logger.warning(f"Admin {uid}: lock {kind} = {value}")
    note = ""
    if kind == 'free' and not value and get_setting('lock_all') == '1': note = "\nℹ️ Lock All is still ON, so free users stay locked."
    bot.send_message(message.chat.id, f"{'🔒 Locked' if value else '🔓 Unlocked'}: {'free users' if kind == 'free' else 'ALL users (premium too)'}\n\n"
                                      f"{lock_status_block()}{note}", reply_markup=create_lock_keyboard())

def run_all_label():
    return '🟢 Run All Code: ON' if get_setting('run_all') == '1' else '🔴 Run All Code: OFF'

def _logic_run_all_switch(message):
    uid = message.from_user.id
    if uid not in admin_ids: bot.reply_to(message, "⚠️ Admin permissions required."); return
    if get_setting('run_all') != '1':
        set_setting('run_all', '1')
        bot.send_message(message.chat.id, "🟢 Run All Code: ON\nStarting every user's scripts now...", reply_markup=create_admin_reply_keyboard(uid))
        threading.Thread(target=_logic_run_all_scripts, args=(message,), daemon=True).start()
    else:
        n = sum(1 for _k, i in list(bot_scripts.items()) if i.get('script_owner_id') not in admin_ids)
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.row(CInlineButton('✅ Yes, stop all', callback_data='runall_off_yes', style='danger'), CInlineButton('❌ Cancel', callback_data='runall_off_no'))
        bot.send_message(message.chat.id, f"⚠️ Turn Run All Code OFF?\nThis stops {n} running user bot(s). Admin/owner bots keep running. Files are not deleted.", reply_markup=mk)

def runall_off_yes_callback(call):
    stopped = 0
    for _k, info in list(bot_scripts.items()):
        owner = info.get('script_owner_id')
        if owner in admin_ids: continue
        _stop_script(owner, info.get('file_name')); stopped += 1
    set_setting('run_all', '0')
    bot.answer_callback_query(call.id, f"⏹️ Stopped {stopped} bot(s).")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception: pass
    bot.send_message(call.message.chat.id, f"🔴 Run All Code: OFF\nStopped {stopped} user bot(s).", reply_markup=create_admin_reply_keyboard(call.from_user.id))

def runall_off_no_callback(call):
    bot.answer_callback_query(call.id, "Cancelled.")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception: pass

def _logic_users(m): _admin_screen(m, ulist_callback, 'ulist_0')
def _logic_payments(m): _admin_screen(m, payments_admin_callback)
def _logic_give_plan(m): _admin_screen(m, add_subscription_init_callback)
def _logic_plans_admin(m): _admin_screen(m, plans_admin_callback)
def _logic_limits(m): _admin_screen(m, limits_admin_callback)
def _logic_force_join(m): _admin_screen(m, fj_menu_callback)
def _logic_admins(m): _admin_screen(m, admins_menu_callback)
def _logic_gateway(m): _admin_screen(m, gw_menu_callback, owner_only=True)
def _logic_backup_now(m): _admin_screen(m, backup_now_callback, owner_only=True)
def _logic_restore(m): _admin_screen(m, restore_backup_callback, owner_only=True)


# --- Menu creation (Inline and ReplyKeyboards) ---
def create_main_menu_inline(user_id):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(CInlineButton('📤 Upload File', callback_data='upload'), CInlineButton('📂 Check Files', callback_data='check_files'))
    m.add(CInlineButton('📊 Status', callback_data='stats'), CInlineButton('💎 Premium Plans', callback_data='plans'))
    m.add(CInlineButton('⚡ Bot Speed', callback_data='speed'),
          CInlineButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    return m

def reply_layout(user_id):
    rows = [["📤 Upload File", "📂 Check Files"], ["📊 Status", "💎 Premium Plans"], ["⚡ Bot Speed", "📞 Contact Owner"]]
    if user_id in admin_ids: rows.append(["👑 Admin Panel"])
    return rows

def admin_reply_layout(user_id):
    rows = [["👥 Users", "💰 Payments"], ["🎁 Give Plan", "📦 Plans"], ["⚙️ Limits", "📢 Force Join"],
            ["🔒 Lock Center", "📣 Broadcast"], [run_all_label()]]
    if user_id == OWNER_ID:
        rows += [["🔑 Gateway", "💾 Backup Now"], ["♻️ Restore Backup", "🛡️ Admins"]]
    rows.append(["🔙 Main Menu"])
    return rows

LOCK_LAYOUT = [["🔒 Lock Free", "🔓 Unlock Free"], ["🔒 Lock All", "🔓 Unlock All"], ["📋 Lock Status", "🔙 Admin Panel"]]

def _reply_markup(rows):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for row_buttons_text in rows:
        markup.add(*[CKeyboardButton(text) for text in row_buttons_text])
    return markup

def create_reply_keyboard_main_menu(user_id): return _reply_markup(reply_layout(user_id))
def create_admin_reply_keyboard(user_id): return _reply_markup(admin_reply_layout(user_id))
def create_lock_keyboard(): return _reply_markup(LOCK_LAYOUT)

def create_control_buttons(script_owner_id, file_name, is_running=True):
    viewer = getattr(_CUR, 'uid', None)
    other = viewer is not None and viewer != script_owner_id       # an admin looking at somebody else's bot
    delete_data = f"{'delask' if other else 'delete'}_{script_owner_id}_{file_name}"
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(CInlineButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
                   CInlineButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}'))
        markup.row(CInlineButton("🗑️ Delete", callback_data=delete_data),
                   CInlineButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}'))
    else:
        markup.row(CInlineButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
                   CInlineButton("🗑️ Delete", callback_data=delete_data))
        markup.row(CInlineButton("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}'))
    if other: markup.add(CInlineButton("🔙 Back to User", callback_data=f'uview_{script_owner_id}'))
    else: markup.add(CInlineButton("🔙 Back to Files", callback_data='check_files'))
    return markup

def create_admin_panel(user_id=None):
    """Small inline menu used only for the Admins screen (the real admin panel is on the keyboard)."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(CInlineButton('➕ Add Admin', callback_data='add_admin'), CInlineButton('➖ Remove Admin', callback_data='remove_admin'))
    markup.row(CInlineButton('📋 List Admins', callback_data='list_admins'))
    markup.row(CInlineButton('🔙 Back to Admin', callback_data='admin_panel'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(CInlineButton('🎁 Give Plan', callback_data='add_subscription'),
               CInlineButton('➖ Remove Subscription', callback_data='remove_subscription'))
    markup.row(CInlineButton('🔍 Check Subscription', callback_data='check_subscription'),
               CInlineButton('📦 Plans', callback_data='plans_admin'))
    markup.row(CInlineButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup
# --- End Menu Creation ---

# --- File Handling ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    # chat_id = message.chat.id # script_owner_id (user_id here) will be used for script key context
    user_folder = get_user_folder(user_id)
    temp_dir = None 
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        logger.info(f"Temp dir for zip: {temp_dir}")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file: new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            lim = get_tier_limits(user_id)
            total_unc = sum(m.file_size for m in zip_ref.infolist())
            if lim['storage_mb'] is not None and total_unc > lim['storage_mb'] * 1048576:
                raise ValueError(f"the ZIP unpacks to {total_unc / 1048576:.1f} MB, over your {lim['storage_mb']:g} MB storage limit (💎 Premium has more)")
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)
            logger.info(f"Extracted zip to {temp_dir}")

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = None  # requirements.txt is moved to the user folder and installed together with imports (ensure_python_deps)
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            logger.info(f"requirements.txt found, installing: {req_path}")
            bot.reply_to(message, f"🔄 Installing Python deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                logger.info(f"pip install from requirements.txt OK. Output:\n{result.stdout}")
                bot.reply_to(message, f"✅ Python deps from `{req_file}` installed.")
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ Failed to install Python deps from `{req_file}`.\nLog:\n```\n{e.stderr or e.stdout}\n```"
                logger.error(error_msg)
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                 error_msg = f"❌ Unexpected error installing Python deps: {e}"
                 logger.error(error_msg, exc_info=True); bot.reply_to(message, error_msg); return

        if pkg_json:
            logger.info(f"package.json found, npm install in: {temp_dir}")
            bot.reply_to(message, f"🔄 Installing Node deps from `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                logger.info(f"npm install OK. Output:\n{result.stdout}")
                bot.reply_to(message, f"✅ Node deps from `{pkg_json}` installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ 'npm' not found. Cannot install Node deps."); return 
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ Failed to install Node deps from `{pkg_json}`.\nLog:\n```\n{e.stderr or e.stdout}\n```"
                logger.error(error_msg)
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (Log truncated)"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                 error_msg = f"❌ Unexpected error installing Node deps: {e}"
                 logger.error(error_msg, exc_info=True); bot.reply_to(message, error_msg); return

        main_script_name = None; file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']; preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files: main_script_name = p; file_type = 'py'; break
        if not main_script_name:
             for p in preferred_js:
                 if p in js_files: main_script_name = p; file_type = 'js'; break
        if not main_script_name:
            if py_files: main_script_name = py_files[0]; file_type = 'py'
            elif js_files: main_script_name = js_files[0]; file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!"); return

        if lim['storage_mb'] is not None and dir_size(temp_dir) - len(downloaded_file_content) > lim['storage_mb'] * 1048576:
            bot.reply_to(message, f"⚠️ After installing dependencies the project is bigger than your {lim['storage_mb']:g} MB storage limit. Upgrade to 💎 Premium or remove heavy dependencies."); return
        renamed_old = archive_existing_file(user_id, main_script_name)
        if renamed_old:
            bot.reply_to(message, f"♻️ Old '{main_script_name}' renamed to '{renamed_old}'. The new upload now uses the name '{main_script_name}'.")
        logger.info(f"Moving extracted files from {temp_dir} to {user_folder}")
        moved_count = 0
        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path): shutil.rmtree(dest_path)
            elif os.path.exists(dest_path): os.remove(dest_path)
            shutil.move(src_path, dest_path); moved_count +=1
        logger.info(f"Moved {moved_count} items to {user_folder}")

        save_user_file(user_id, main_script_name, file_type)
        logger.info(f"Saved main script '{main_script_name}' ({file_type}) for {user_id} from zip.")
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')

        # Use user_id as script_owner_id for script key context
        if file_type == 'py':
             threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
             threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        logger.error(f"Bad zip file from {user_id}: {e}")
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        logger.error(f"❌ Error processing zip for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir); logger.info(f"Cleaned temp dir: {temp_dir}")
            except Exception as e: logger.error(f"Failed to clean temp dir {temp_dir}: {e}", exc_info=True)

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing JS file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing JS file: {str(e)}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing Python file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing Python file: {str(e)}")
# --- End File Handling ---


# --- Logic Functions (called by commands and text handlers) ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    logger.info(f"Welcome request from user_id: {user_id}, username: @{user_username}")

    if is_locked_for(user_id):
        bot.send_message(chat_id, "⚠️ Bot locked by admin. Try later.")
        return

    user_bio = "Could not fetch bio"; photo_file_id = None
    try: user_bio = bot.get_chat(user_id).bio or "No bio"
    except Exception: pass
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
        if user_profile_photos.photos: photo_file_id = user_profile_photos.photos[0][-1].file_id
    except Exception: pass

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"🎉 New user!\n👤 Name: {user_name}\n✳️ User: @{user_username or 'N/A'}\n"
                                  f"🆔 ID: `{user_id}`\n📝 Bio: {user_bio}")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
            if photo_file_id: bot.send_photo(OWNER_ID, photo_file_id, caption=f"Pic of new user {user_id}")
        except Exception as e: logger.error(f"⚠️ Failed to notify owner about new user {user_id}: {e}")

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    user_status, expiry_info = _status_line(user_id)
    free_hint = "\n💎 Free plan hosts small bots only. Open Premium Plans for more bots and bigger files." if user_status == "🆓 Free User" else ""

    welcome_msg_text = (f"〽️ Welcome, {user_name}!\n\n🆔 Your User ID: `{user_id}`\n"
                        f"✳️ Username: `@{user_username or 'Not set'}`\n"
                        f"🔰 Your Status: {user_status}{expiry_info}\n"
                        f"📁 Files Uploaded: {current_files} / {limit_str}{free_hint}\n\n"
                        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"   Upload single scripts or `.zip` archives.\n\n"
                        f"👇 Use buttons or type commands.")
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        if photo_file_id: bot.send_photo(chat_id, photo_file_id)
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending welcome to {user_id}: {e}", exc_info=True)
        try: bot.send_message(chat_id, welcome_msg_text.replace('`', ''), reply_markup=main_reply_markup)
        except Exception as fallback_e: logger.error(f"Fallback send_message failed for {user_id}: {fallback_e}")

def _logic_upload_file(message):
    user_id = message.from_user.id
    if is_locked_for(user_id):
        bot.reply_to(message, "⚠️ Bot locked by admin, cannot accept files.")
        return

    # Removed free_mode check, relies on get_user_file_limit and FREE_USER_LIMIT
    # Users need to be admin or subscribed to upload if FREE_USER_LIMIT is 0
    # For now, FREE_USER_LIMIT > 0, so free users can upload up to that limit.
    # If we want to restrict free users entirely, set FREE_USER_LIMIT to 0.
    # For this implementation, free users get FREE_USER_LIMIT.

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    bot.reply_to(message, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

def _logic_check_files(message):
    user_id = message.from_user.id
    if is_locked_for(user_id):
        bot.reply_to(message, "⚠️ Bot locked by admin. Try later."); return
    # chat_id = message.chat.id # user_id will be used as script_owner_id for buttons
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name) # Use user_id for checking status
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        # Callback data includes user_id as script_owner_id
        markup.add(CInlineButton(btn_text, callback_data=f'file_{user_id}_{file_name}', style=('success' if is_running else 'danger')))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = lock_status_text(user_id)
        # mode = "💰 Free Mode: ON" if free_mode else "💸 Free Mode: OFF" # Removed free_mode
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     # f"模式 Mode: {mode}\n" # Removed
                     f"👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error during speed test (cmd): {e}", exc_info=True)
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(CInlineButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Click to contact Owner:", reply_markup=markup)

# --- Admin Logic Functions ---
def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💳 Subscription Management\nUse inline buttons from /start or admin command menu.", reply_markup=create_subscription_menu())

def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(message, "📢 Send message to broadcast to all active users.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

# def _logic_toggle_free_mode(message): # Removed
#     pass

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call.message 
    else:
        logger.error("Invalid argument for _logic_run_all_scripts")
        return

    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required.")
        return

    reply_func("⏳ Starting process to run all user scripts. This may take a while...")
    logger.info(f"Admin {admin_user_id} initiated 'run all scripts' from chat {admin_chat_id}.")

    started_count = 0; attempted_users = 0; skipped_files = 0; error_files_details = []

    # Use a copy of user_files keys and values to avoid modification issues during iteration
    all_user_files_snapshot = dict(user_files)

    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user: continue
        attempted_users += 1
        logger.info(f"Processing scripts for user {target_user_id}...")
        user_folder = get_user_folder(target_user_id)

        for file_name, file_type in files_for_user:
            # script_owner_id for key context is target_user_id
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    logger.info(f"Admin {admin_user_id} attempting to start '{file_name}' ({file_type}) for user {target_user_id}.")
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        else:
                            logger.warning(f"Unknown file type '{file_type}' for {file_name} (user {target_user_id}). Skipping.")
                            error_files_details.append(f"`{file_name}` (User {target_user_id}) - Unknown type")
                            skipped_files += 1
                        time.sleep(0.7) # Increased delay slightly
                    except Exception as e:
                        logger.error(f"Error queueing start for '{file_name}' (user {target_user_id}): {e}")
                        error_files_details.append(f"`{file_name}` (User {target_user_id}) - Start error")
                        skipped_files += 1
                else:
                    logger.warning(f"File '{file_name}' for user {target_user_id} not found at '{file_path}'. Skipping.")
                    error_files_details.append(f"`{file_name}` (User {target_user_id}) - File not found")
                    skipped_files += 1
            # else: logger.info(f"Script '{file_name}' for user {target_user_id} already running.")

    summary_msg = (f"✅ All Users' Scripts - Processing Complete:\n\n"
                   f"▶️ Attempted to start: {started_count} scripts.\n"
                   f"👥 Users processed: {attempted_users}.\n")
    if skipped_files > 0:
        summary_msg += f"⚠️ Skipped/Error files: {skipped_files}\n"
        if error_files_details:
             summary_msg += "Details (first 5):\n" + "\n".join([f"  - {err}" for err in error_files_details[:5]])
             if len(error_files_details) > 5: summary_msg += "\n  ... and more (check logs)."

    reply_func(summary_msg, parse_mode='Markdown')
    logger.info(f"Run all scripts finished. Admin: {admin_user_id}. Started: {started_count}. Skipped/Errors: {skipped_files}")


# --- Command Handlers & Text Handlers for ReplyKeyboard ---
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message): _logic_send_welcome(message)

@bot.message_handler(commands=['status']) # Kept for direct command
def command_show_status(message): _logic_statistics(message) # Changed to call _logic_statistics


BUTTON_TEXT_TO_LOGIC = {
    # --- everyone ---
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "📊 Status": _logic_statistics,
    "📊 Statistics": _logic_statistics,          # old keyboards still work
    "💎 Premium Plans": _logic_plans,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    # --- admin keyboard ---
    "👑 Admin Panel": _logic_admin_panel,
    "🔙 Admin Panel": _logic_admin_panel,
    "🔙 Main Menu": _logic_main_menu,
    "👥 Users": _logic_users,
    "💰 Payments": _logic_payments,
    "🎁 Give Plan": _logic_give_plan,
    "📦 Plans": _logic_plans_admin,
    "⚙️ Limits": _logic_limits,
    "📢 Force Join": _logic_force_join,
    "📣 Broadcast": _logic_broadcast_init,
    "🔒 Lock Center": _logic_lock_center,
    "🔒 Lock Free": lambda m: _logic_set_lock(m, 'free', True),
    "🔓 Unlock Free": lambda m: _logic_set_lock(m, 'free', False),
    "🔒 Lock All": lambda m: _logic_set_lock(m, 'all', True),
    "🔓 Unlock All": lambda m: _logic_set_lock(m, 'all', False),
    "📋 Lock Status": _logic_lock_status,
    "🟢 Run All Code: ON": _logic_run_all_switch,
    "🔴 Run All Code: OFF": _logic_run_all_switch,
    # --- owner only ---
    "🔑 Gateway": _logic_gateway,
    "💾 Backup Now": _logic_backup_now,
    "♻️ Restore Backup": _logic_restore,
    "🛡️ Admins": _logic_admins,
}
BUTTON_TEXT_TO_LOGIC = {sc(k): v for k, v in BUTTON_TEXT_TO_LOGIC.items()}     # buttons are sent in small caps, so match them that way
OPEN_WHEN_LOCKED = {sc(x) for x in ("⚡ Bot Speed", "📊 Status", "📊 Statistics", "📞 Contact Owner")}
LEGACY_BUTTONS = {sc(x) for x in ("📢 Updates Channel", "💳 Subscriptions", "🔒 Lock Bot", "🔓 Unlock Bot", "🟢 Running All Code")}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    if is_locked_for(message.from_user.id) and message.text not in OPEN_WHEN_LOCKED:
        bot.reply_to(message, "⚠️ Bot locked by admin. Try later."); return
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func: logic_func(message)
    else: logger.warning(f"Button text '{message.text}' matched but no logic func.")

@bot.message_handler(func=lambda m: m.text in LEGACY_BUTTONS)
def legacy_button(message):
    bot.send_message(message.chat.id, "🔄 The menu was updated. Use the new buttons below.", reply_markup=create_reply_keyboard_main_menu(message.from_user.id))

@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message): _logic_upload_file(message)
@bot.message_handler(commands=['checkfiles'])
def command_check_files(message): _logic_check_files(message)
@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message): _logic_bot_speed(message)
@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message): _logic_contact_owner(message)
@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message): _logic_subscriptions_panel(message)
@bot.message_handler(commands=['statistics']) # Alias for /status
def command_statistics(message): _logic_statistics(message)
@bot.message_handler(commands=['broadcast'])
def command_broadcast(message): _logic_broadcast_init(message)
@bot.message_handler(commands=['lockbot']) 
def command_lock_bot(message): _logic_toggle_lock(message, 'free')
# @bot.message_handler(commands=['freemode']) # Removed
# def command_free_mode(message): _logic_toggle_free_mode(message)
@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message): _logic_admin_panel(message)
@bot.message_handler(commands=['runningallcode']) # Added
def command_run_all_code(message): _logic_run_all_scripts(message)


@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time() 
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)


# --- Document (File) Handler ---
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message): # Renamed
    user_id = message.from_user.id
    chat_id = message.chat.id # Used for replies, script context uses user_id
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")

    if user_id == OWNER_ID and restore_armed():          # owner pressed "Restore Backup": this file is a backup, not a script
        handle_restore_upload(message)
        return

    if is_locked_for(user_id):
        bot.reply_to(message, "⚠️ Bot locked, cannot accept files.")
        return

    # File limit check (relies on FREE_USER_LIMIT being > 0 for free users)
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files via /checkfiles.")
        return

    file_name = doc.file_name
    if not file_name: bot.reply_to(message, "⚠️ No file name. Ensure file has a name."); return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Unsupported type! Only `.py`, `.js`, `.zip` allowed.")
        return
    lim = get_tier_limits(user_id)
    max_mb = lim['zip_mb'] if file_ext == '.zip' else lim['file_mb']
    if doc.file_size > max_mb * 1048576:
        bot.reply_to(message, f"⚠️ File too large for your plan (max {max_mb:g} MB for {'ZIP' if file_ext == '.zip' else 'script'} files).\n💎 Premium gives bigger limits — open Premium Plans."); return
    if lim['storage_mb'] is not None:
        used = dir_size(get_user_folder(user_id))
        if used + doc.file_size > lim['storage_mb'] * 1048576:
            bot.reply_to(message, f"⚠️ Storage full: {used / 1048576:.1f} / {lim['storage_mb']:g} MB. Delete old files (renamed *_old files count too) or upgrade to 💎 Premium."); return

    try:
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception as e: logger.error(f"Failed to forward uploaded file to OWNER_ID {OWNER_ID}: {e}")

        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id) # Renamed
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, download_wait_msg.message_id)
        logger.info(f"Downloaded {file_name} for user {user_id}")
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            renamed_old = archive_existing_file(user_id, file_name)
            if renamed_old:
                bot.reply_to(message, f"♻️ Old '{file_name}' renamed to '{renamed_old}'. The new upload now uses the name '{file_name}'.")
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f: f.write(downloaded_file_content)
            logger.info(f"Saved single file to {file_path}")
            # Pass user_id as script_owner_id
            if file_ext == '.js': handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py': handle_py_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
         logger.error(f"Telegram API Error handling file for {user_id}: {e}", exc_info=True)
         if "file is too big" in str(e).lower():
              bot.reply_to(message, f"❌ Telegram API Error: File too large to download (~20MB limit).")
         else: bot.reply_to(message, f"❌ Telegram API Error: {str(e)}. Try later.")
    except Exception as e:
        logger.error(f"❌ General error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Unexpected error: {str(e)}")
# --- End Document Handler ---


# --- Callback Query Handlers (for Inline Buttons) ---
_last_cb = {}

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    _CUR.uid = user_id
    logger.info(f"Callback: User={user_id}, Data='{data}'")

    if user_id in banned_ids:
        bot.answer_callback_query(call.id, "⛔ You are banned.", show_alert=True); return
    if data != 'fj_check':
        missing = force_join_missing(user_id)
        if missing:
            bot.answer_callback_query(call.id, "🔒 Join the channel first.", show_alert=True)
            send_force_join_prompt(call.message.chat.id, missing); return
    now = time.time()
    if user_id not in admin_ids and now - _last_cb.get(user_id, 0) < 0.6:     # button-spam guard keeps the bot light
        bot.answer_callback_query(call.id, "⏳ Slow down a little."); return
    _last_cb[user_id] = now
    if is_locked_for(user_id) and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked by admin.", show_alert=True)
        return
    try:
        if data == 'upload': upload_callback(call)
        elif data == 'check_files': check_files_callback(call)
        elif data.startswith('file_'): file_control_callback(call)
        elif data.startswith('start_'): start_bot_callback(call)
        elif data.startswith('stop_'): stop_bot_callback(call)
        elif data.startswith('restart_'): restart_bot_callback(call)
        elif data.startswith('delete_'): delete_bot_callback(call)
        elif data.startswith('logs_'): logs_bot_callback(call)
        elif data == 'speed': speed_callback(call)
        elif data == 'back_to_main': back_to_main_callback(call)
        elif data == 'stats': stats_callback(call)
        elif data == 'plans': plans_callback(call)
        elif data == 'fj_check': fj_check_callback(call)
        elif data.startswith('buy_'): buy_callback(call)
        elif data.startswith('chk_'): check_order_callback(call)
        elif data.startswith('confirm_broadcast_'): handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast': handle_cancel_broadcast(call)
        # --- Admin callbacks ---
        elif data == 'subscription': admin_required_callback(call, subscription_management_callback)
        elif data == 'lock_free': admin_required_callback(call, lambda c: lock_set_callback(c, 'free', True))
        elif data == 'unlock_free': admin_required_callback(call, lambda c: lock_set_callback(c, 'free', False))
        elif data == 'lock_all': admin_required_callback(call, lambda c: lock_set_callback(c, 'all', True))
        elif data == 'unlock_all': admin_required_callback(call, lambda c: lock_set_callback(c, 'all', False))
        elif data == 'run_all_scripts': admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast': admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel': admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin': owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin': owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins': admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription': admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription': admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription': admin_required_callback(call, check_subscription_init_callback)
        elif data == 'plans_admin': admin_required_callback(call, plans_admin_callback)
        elif data == 'plan_add': admin_required_callback(call, plan_add_callback)
        elif data == 'plan_edit': admin_required_callback(call, plan_edit_callback)
        elif data == 'plan_del': admin_required_callback(call, plan_del_callback)
        elif data == 'limits_admin': admin_required_callback(call, limits_admin_callback)
        elif data.startswith('setlim_'): admin_required_callback(call, setlim_callback)
        elif data == 'payments_admin': admin_required_callback(call, payments_admin_callback)
        elif data.startswith('ulist_'): admin_required_callback(call, ulist_callback)
        elif data.startswith('uview_'): admin_required_callback(call, uview_callback)
        elif data.startswith('delask_'): delask_callback(call)
        elif data.startswith('delallyes_'): admin_required_callback(call, delallyes_callback)
        elif data.startswith('delall_'): admin_required_callback(call, delall_callback)
        elif data.startswith('unban_'): admin_required_callback(call, lambda c: ban_callback(c, False))
        elif data.startswith('ban_'): admin_required_callback(call, lambda c: ban_callback(c, True))
        elif data == 'fj_menu': admin_required_callback(call, fj_menu_callback)
        elif data == 'fj_add': admin_required_callback(call, fj_add_callback)
        elif data == 'fj_del': admin_required_callback(call, fj_del_callback)
        elif data == 'fj_toggle': admin_required_callback(call, fj_toggle_callback)
        elif data == 'runall_off_yes': admin_required_callback(call, runall_off_yes_callback)
        elif data == 'runall_off_no': admin_required_callback(call, runall_off_no_callback)
        elif data == 'admins_menu': admin_required_callback(call, admins_menu_callback)
        # --- Owner-only callbacks ---
        elif data == 'gw_menu': owner_required_callback(call, gw_menu_callback)
        elif data == 'gw_url': owner_required_callback(call, gw_url_callback)
        elif data == 'gw_key': owner_required_callback(call, gw_key_callback)
        elif data == 'backup_now': owner_required_callback(call, backup_now_callback)
        elif data == 'restore_backup': owner_required_callback(call, restore_backup_callback)
        elif data == 'restore_done': owner_required_callback(call, restore_done_callback)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
            logger.warning(f"Unhandled callback data: {data} from user {user_id}")
    except Exception as e:
        logger.error(f"Error handling callback '{data}' for {user_id}: {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)
        except Exception as e_ans: logger.error(f"Failed to answer callback after error: {e_ans}")

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin permissions required.", show_alert=True)
        return
    func_to_run(call) 

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ Owner permissions required.", show_alert=True)
        return
    func_to_run(call)

def upload_callback(call):
    user_id = call.from_user.id
    # Removed free_mode check
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ File limit ({current_files}/{limit_str}) reached.", show_alert=True)
        return
    bot.answer_callback_query(call.id) 
    bot.send_message(call.message.chat.id, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id 
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "⚠️ No files uploaded.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(CInlineButton("🔙 Back to Main", callback_data='back_to_main'))
            bot.edit_message_text("📂 Your files:\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
        except Exception as e: logger.error(f"Error editing msg for empty file list: {e}")
        return
    bot.answer_callback_query(call.id) 
    markup = types.InlineKeyboardMarkup(row_width=1) 
    for file_name, file_type in sorted(user_files_list): 
        is_running = is_bot_running(user_id, file_name) # Use user_id for status check
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        # Callback includes user_id as script_owner_id
        markup.add(CInlineButton(btn_text, callback_data=f'file_{user_id}_{file_name}', style=('success' if is_running else 'danger')))
    markup.add(CInlineButton("🔙 Back to Main", callback_data='back_to_main'))
    try:
        bot.edit_message_text("📂 Your files:\nClick to manage.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
         if "message is not modified" in str(e): logger.warning("Msg not modified (files).")
         else: logger.error(f"Error editing msg for file list: {e}")
    except Exception as e: logger.error(f"Unexpected error editing msg for file list: {e}", exc_info=True)

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        # Allow owner/admin to control any file, or user to control their own
        if not can_manage(requesting_user_id, script_owner_id):
            logger.warning(f"User {requesting_user_id} tried to access file '{file_name}' of user {script_owner_id} without permission.")
            bot.answer_callback_query(call.id, "⚠️ You can only manage your own files.", show_alert=True)
            check_files_callback(call) # Show their own files
            return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            logger.warning(f"File '{file_name}' not found for user {script_owner_id} during control.")
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            # If admin was viewing, this might be confusing. For now, just show their own.
            check_files_callback(call) 
            return

        bot.answer_callback_query(call.id) 
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?') 
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified (controls for {file_name})")
             else: raise 
    except (ValueError, IndexError) as ve:
        logger.error(f"Error parsing file control callback: {ve}. Data: '{call.data}'")
        bot.answer_callback_query(call.id, "Error: Invalid action data.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in file_control_callback for data '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "An error occurred.", show_alert=True)

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id # Where the admin/user gets the reply

        logger.info(f"Start request: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")

        if not can_manage(requesting_user_id, script_owner_id):
            bot.answer_callback_query(call.id, "⚠️ Permission denied to start this script.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)

        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ Error: File `{file_name}` missing! Re-upload.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name); check_files_callback(call); return

        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Script '{file_name}' already running.", show_alert=True)
            try: bot.edit_message_reply_markup(chat_id_for_reply, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, True))
            except Exception as e: logger.error(f"Error updating buttons (already running): {e}")
            return

        bot.answer_callback_query(call.id, f"⏳ Attempting to start {file_name} for user {script_owner_id}...")

        # Pass call.message as message_obj_for_reply so feedback goes to the person who clicked
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        else:
             bot.send_message(chat_id_for_reply, f"❌ Error: Unknown file type '{file_type}' for '{file_name}'."); return 

        time.sleep(1.5) # Give script time to actually start or fail early
        is_now_running = is_bot_running(script_owner_id, file_name) 
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed, check logs/replies)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified after starting {file_name}")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing start callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid start command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in start_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error starting script.", show_alert=True)
        try: # Attempt to reset buttons to 'stopped' state on error
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn: logger.error(f"Failed to update buttons after start error: {e_btn}")

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Stop request: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not can_manage(requesting_user_id, script_owner_id):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1] 
        script_key = f"{script_owner_id}_{file_name}"

        if not is_bot_running(script_owner_id, file_name): 
            bot.answer_callback_query(call.id, f"⚠️ Script '{file_name}' already stopped.", show_alert=True)
            try:
                 bot.edit_message_text(
                     f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                     chat_id_for_reply, call.message.message_id,
                     reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown')
            except Exception as e: logger.error(f"Error updating buttons (already stopped): {e}")
            return

        bot.answer_callback_query(call.id, f"⏳ Stopping {file_name} for user {script_owner_id}...")
        set_autostart(script_owner_id, file_name, False)
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]; logger.info(f"Removed {script_key} from running after stop.")
        else: logger.warning(f"Script {script_key} running by psutil but not in bot_scripts dict.")

        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified after stopping {file_name}")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing stop callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid stop command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in stop_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error stopping script.", show_alert=True)

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Restart: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not can_manage(requesting_user_id, script_owner_id):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1]; user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name); script_key = f"{script_owner_id}_{file_name}"

        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ Error: File `{file_name}` missing! Re-upload.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            if script_key in bot_scripts: del bot_scripts[script_key]
            check_files_callback(call); return

        bot.answer_callback_query(call.id, f"⏳ Restarting {file_name} for user {script_owner_id}...")
        if is_bot_running(script_owner_id, file_name):
            logger.info(f"Restart: Stopping existing {script_key}...")
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(1.5) 

        logger.info(f"Restart: Starting script {script_key}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        else:
             bot.send_message(chat_id_for_reply, f"❌ Unknown type '{file_type}' for '{file_name}'."); return

        time.sleep(1.5) 
        is_now_running = is_bot_running(script_owner_id, file_name) 
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified (restart {file_name})")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing restart callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid restart command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in restart_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error restarting.", show_alert=True)
        try:
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn: logger.error(f"Failed to update buttons after restart error: {e_btn}")


def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Delete: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not can_manage(requesting_user_id, script_owner_id):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return

        bot.answer_callback_query(call.id, f"🗑️ Deleting {file_name} for user {script_owner_id}...")
        set_autostart(script_owner_id, file_name, False)
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            logger.info(f"Delete: Stopping {script_key}...")
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5) 

        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        deleted_disk = []
        if os.path.exists(file_path):
            try: os.remove(file_path); deleted_disk.append(file_name); logger.info(f"Deleted file: {file_path}")
            except OSError as e: logger.error(f"Error deleting {file_path}: {e}")
        if os.path.exists(log_path):
            try: os.remove(log_path); deleted_disk.append(os.path.basename(log_path)); logger.info(f"Deleted log: {log_path}")
            except OSError as e: logger.error(f"Error deleting log {log_path}: {e}")

        remove_user_file_db(script_owner_id, file_name)
        if requesting_user_id != script_owner_id: _notify(script_owner_id, f"🗑️ Your file '{file_name}' was removed by an admin.")
        deleted_str = ", ".join(f"`{f}`" for f in deleted_disk) if deleted_disk else "associated files"
        try:
            bot.edit_message_text(
                f"🗑️ Record `{file_name}` (User `{script_owner_id}`) and {deleted_str} deleted!",
                chat_id_for_reply, call.message.message_id, reply_markup=None, parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error editing msg after delete: {e}")
            bot.send_message(chat_id_for_reply, f"🗑️ Record `{file_name}` deleted.", parse_mode='Markdown')
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing delete callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid delete command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in delete_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error deleting.", show_alert=True)

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Logs: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not can_manage(requesting_user_id, script_owner_id):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return

        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"⚠️ No logs for '{file_name}'.", show_alert=True); return

        bot.answer_callback_query(call.id) 
        try:
            log_content = ""; file_size = os.path.getsize(log_path)
            max_log_kb = 100; max_tg_msg = 4096
            if file_size == 0: log_content = "(Log empty)"
            elif file_size > max_log_kb * 1024:
                 with open(log_path, 'rb') as f: f.seek(-max_log_kb * 1024, os.SEEK_END); log_bytes = f.read()
                 log_content = log_bytes.decode('utf-8', errors='ignore')
                 log_content = f"(Last {max_log_kb} KB)\n...\n" + log_content
            else:
                 with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: log_content = f.read()

            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                first_nl = log_content.find('\n')
                if first_nl != -1: log_content = "...\n" + log_content[first_nl+1:]
                else: log_content = "...\n" + log_content 
            if not log_content.strip(): log_content = "(No visible content)"

            bot.send_message(chat_id_for_reply, f"📜 Logs for `{file_name}` (User `{script_owner_id}`):\n```\n{log_content}\n```", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error reading/sending log {log_path}: {e}", exc_info=True)
            bot.send_message(chat_id_for_reply, f"❌ Error reading log for `{file_name}`.")
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing logs callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "Error: Invalid logs command.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in logs_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error fetching logs.", show_alert=True)

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time() 
    try:
        bot.edit_message_text("🏃 Testing speed...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing') 
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = lock_status_text(user_id)
        # mode = "💰 Free Mode: ON" if free_mode else "💸 Free Mode: OFF" # Removed
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     # f"模式 Mode: {mode}\n" # Removed
                     f"👤 Your Level: {user_level}")
        bot.answer_callback_query(call.id) 
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
         logger.error(f"Error during speed test (cb): {e}", exc_info=True)
         bot.answer_callback_query(call.id, "Error in speed test.", show_alert=True)
         try: bot.edit_message_text("〽️ Main Menu", chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
         except Exception: pass

def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    user_status, expiry_info = _status_line(user_id)
    main_menu_text = (f"〽️ Welcome back, {call.from_user.first_name}!\n\n🆔 ID: {user_id}\n"
                      f"🔰 Status: {user_status}{expiry_info}\n📁 Files: {current_files} / {limit_str}\n\n"
                      f"👇 Use buttons or type commands.")
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except telebot.apihelper.ApiTelegramException as e:
         if "message is not modified" in str(e): logger.warning("Msg not modified (back_to_main).")
         else: logger.error(f"API error on back_to_main: {e}")
    except Exception as e: logger.error(f"Error handling back_to_main: {e}", exc_info=True)

# --- Admin Callback Implementations (for Inline Buttons) ---
def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("💳 Subscription Management\nSelect action:",
                              call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except Exception as e: logger.error(f"Error showing sub menu: {e}")

def stats_callback(call): # Called by user and admin
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message, user_id=call.from_user.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error updating menu after stats_callback: {e}")

# def toggle_free_mode_callback(call): # Removed
#     pass

def run_all_scripts_callback(call): # Added
    _logic_run_all_scripts(call) # Pass the call object


def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text and message.text.lower() == '/cancel': bot.reply_to(message, "Broadcast cancelled."); return

    broadcast_content = message.text # Can also handle photos, videos etc. if message.content_type is checked
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker or message.voice or message.audio): # If no text and no other media
         bot.reply_to(message, "⚠️ Cannot broadcast empty message. Send text or media, or /cancel.")
         msg = bot.send_message(message.chat.id, "📢 Send broadcast message or /cancel.")
         bot.register_next_step_handler(msg, process_broadcast_message)
         return

    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(CInlineButton("✅ Confirm & Send", callback_data=f"confirm_broadcast_{message.message_id}"),
               CInlineButton("❌ Cancel", callback_data="cancel_broadcast"))

    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"⚠️ Confirm Broadcast:\n\n```\n{preview_text}\n```\n" 
                          f"To **{target_count}** users. Sure?", reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids: bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True); return
    try:
        original_message = call.message.reply_to_message
        if not original_message: raise ValueError("Could not retrieve original message.")

        # Check content type and get content
        broadcast_text = None
        broadcast_photo_id = None
        broadcast_video_id = None
        # Add other types as needed: document, sticker, voice, audio

        if original_message.text:
            broadcast_text = original_message.text
        elif original_message.photo:
            broadcast_photo_id = original_message.photo[-1].file_id # Get highest quality
        elif original_message.video:
            broadcast_video_id = original_message.video.file_id
        # Add more elif for other content types
        else:
            raise ValueError("Message has no text or supported media for broadcast.")

        bot.answer_callback_query(call.id, "🚀 Starting broadcast...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        # Pass all potential content types to execute_broadcast
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id, 
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None, # Pass caption
            chat_id))
        thread.start()
    except ValueError as ve: 
        logger.error(f"Error retrieving msg for broadcast confirm: {ve}")
        bot.edit_message_text(f"❌ Error starting broadcast: {ve}", chat_id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Error in handle_confirm_broadcast: {e}", exc_info=True)
        bot.edit_message_text("❌ Unexpected error during broadcast confirm.", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Broadcast cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    # Optionally delete the original message too if call.message.reply_to_message exists
    if call.message.reply_to_message:
        try: bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except: pass


def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0; failed_count = 0; blocked_count = 0
    start_exec_time = time.time() 
    users_to_broadcast = list(active_users); total_users = len(users_to_broadcast)
    logger.info(f"Executing broadcast to {total_users} users.")
    batch_size = 25; delay_batches = 1.5

    for i, user_id_bc in enumerate(users_to_broadcast): # Renamed
        try:
            if broadcast_text:
                bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
            elif video_id:
                bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
            # Add other send methods for other types
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["bot was blocked", "user is deactivated", "chat not found", "kicked from", "restricted"]): 
                logger.warning(f"Broadcast failed to {user_id_bc}: User blocked/inactive.")
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5; match = re.search(r"retry after (\d+)", err_desc)
                if match: retry_after = int(match.group(1)) + 1 
                logger.warning(f"Flood control. Sleeping {retry_after}s...")
                time.sleep(retry_after)
                try: # Retry once
                    if broadcast_text: bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id: bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
                    elif video_id: bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except Exception as e_retry: logger.error(f"Broadcast retry failed to {user_id_bc}: {e_retry}"); failed_count +=1
            else: logger.error(f"Broadcast failed to {user_id_bc}: {e}"); failed_count += 1
        except Exception as e: logger.error(f"Unexpected error broadcasting to {user_id_bc}: {e}"); failed_count += 1

        if (i + 1) % batch_size == 0 and i < total_users - 1:
            logger.info(f"Broadcast batch {i//batch_size + 1} sent. Sleeping {delay_batches}s...")
            time.sleep(delay_batches)
        elif i % 5 == 0: time.sleep(0.2) 

    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"📢 Broadcast Complete!\n\n✅ Sent: {sent_count}\n❌ Failed: {failed_count}\n"
                  f"🚫 Blocked/Inactive: {blocked_count}\n👥 Targets: {total_users}\n⏱️ Duration: {duration}s")
    logger.info(result_msg)
    try: bot.send_message(admin_chat_id, result_msg)
    except Exception as e: logger.error(f"Failed to send broadcast result to admin {admin_chat_id}: {e}")

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote to Admin.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    owner_id_check = message.from_user.id 
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Admin promotion cancelled."); return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0: raise ValueError("ID must be positive")
        if new_admin_id == OWNER_ID: bot.reply_to(message, "⚠️ Owner is already Owner."); return
        if new_admin_id in admin_ids: bot.reply_to(message, f"⚠️ User `{new_admin_id}` already Admin."); return
        add_admin_db(new_admin_id) 
        logger.warning(f"Admin {new_admin_id} added by Owner {owner_id_check}.")
        bot.reply_to(message, f"✅ User `{new_admin_id}` promoted to Admin.")
        try: bot.send_message(new_admin_id, "🎉 Congrats! You are now an Admin.")
        except Exception as e: logger.error(f"Failed to notify new admin {new_admin_id}: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "👑 Enter User ID to promote or /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)
    except Exception as e: logger.error(f"Error processing add admin: {e}", exc_info=True); bot.reply_to(message, "Error.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID of Admin to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Admin removal cancelled."); return
    try:
        admin_id_remove = int(message.text.strip()) # Renamed
        if admin_id_remove <= 0: raise ValueError("ID must be positive")
        if admin_id_remove == OWNER_ID: bot.reply_to(message, "⚠️ Owner cannot remove self."); return
        if admin_id_remove not in admin_ids: bot.reply_to(message, f"⚠️ User `{admin_id_remove}` not Admin."); return
        if remove_admin_db(admin_id_remove): 
            logger.warning(f"Admin {admin_id_remove} removed by Owner {owner_id_check}.")
            bot.reply_to(message, f"✅ Admin `{admin_id_remove}` removed.")
            try: bot.send_message(admin_id_remove, "ℹ️ You are no longer an Admin.")
            except Exception as e: logger.error(f"Failed to notify removed admin {admin_id_remove}: {e}")
        else: bot.reply_to(message, f"❌ Failed to remove admin `{admin_id_remove}`. Check logs.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "👑 Enter Admin ID to remove or /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)
    except Exception as e: logger.error(f"Error processing remove admin: {e}", exc_info=True); bot.reply_to(message, "Error.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}" for aid in sorted(list(admin_ids)))
        if not admin_list_str: admin_list_str = "(No Owner/Admins configured!)"
        bot.edit_message_text(f"👑 Current Admins:\n\n{admin_list_str}", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_panel(), parse_mode='Markdown')
    except Exception as e: logger.error(f"Error listing admins: {e}")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to remove sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Sub removal cancelled."); return
    try:
        sub_user_id_remove = int(message.text.strip()) # Renamed
        if sub_user_id_remove <= 0: raise ValueError("ID must be positive")
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"⚠️ User `{sub_user_id_remove}` no active sub in memory."); return
        remove_subscription_db(sub_user_id_remove) 
        logger.warning(f"Sub removed for {sub_user_id_remove} by admin {admin_id_check}.")
        bot.reply_to(message, f"✅ Sub for `{sub_user_id_remove}` removed.")
        try: bot.send_message(sub_user_id_remove, "ℹ️ Your subscription removed by admin.")
        except Exception as e: logger.error(f"Failed to notify {sub_user_id_remove} of sub removal: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID to remove sub from, or /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)
    except Exception as e: logger.error(f"Error processing remove sub: {e}", exc_info=True); bot.reply_to(message, "Error.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to check sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription_id)

def process_check_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Sub check cancelled."); return
    try:
        sub_user_id_check = int(message.text.strip()) # Renamed
        if sub_user_id_check <= 0: raise ValueError("ID must be positive")
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message, f"✅ User `{sub_user_id_check}` active sub.\nExpires: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} days left).")
                else:
                    bot.reply_to(message, f"⚠️ User `{sub_user_id_check}` expired sub (On: {expiry_dt:%Y-%m-%d %H:%M:%S}).")
                    remove_subscription_db(sub_user_id_check) # Clean up
            else: bot.reply_to(message, f"⚠️ User `{sub_user_id_check}` in sub list, but expiry missing. Re-add if needed.")
        else: bot.reply_to(message, f"ℹ️ User `{sub_user_id_check}` no active sub record.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID. Send numerical ID or /cancel.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID to check, or /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)
    except Exception as e: logger.error(f"Error processing check sub: {e}", exc_info=True); bot.reply_to(message, "Error.")

# --- End Callback Query Handlers ---

# --- Cleanup Function ---
def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys()) 
    if not script_keys_to_stop: logger.info("No scripts running. Exiting."); return
    logger.info(f"Stopping {len(script_keys_to_stop)} scripts...")
    for key in script_keys_to_stop:
        if key in bot_scripts: logger.info(f"Stopping: {key}"); kill_process_tree(bot_scripts[key])
        else: logger.info(f"Script {key} already removed.")
    logger.warning("Cleanup finished.")
atexit.register(cleanup)

# --- Main Execution ---
if __name__ == '__main__':
    logger.info("="*40 + "\n🤖 Bot Starting Up...\n" + f"🐍 Python: {sys.version.split()[0]}\n" +
                f"🔧 Base Dir: {BASE_DIR}\n📁 Upload Dir: {UPLOAD_BOTS_DIR}\n" +
                f"📊 Data Dir: {IROTECH_DIR}\n🔑 Owner ID: {OWNER_ID}\n🛡️ Admins: {admin_ids}\n" + "="*40)
    keep_alive()
    for _worker in (autostart_all, subscription_watcher, payment_poller, resource_monitor, backup_scheduler):
        threading.Thread(target=_worker, daemon=True).start()   # restart bots · plan expiry · payments · server alerts · daily backup
    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout: logger.warning("Polling ReadTimeout. Restarting in 5s..."); time.sleep(5)
        except requests.exceptions.ConnectionError as ce: logger.error(f"Polling ConnectionError: {ce}. Retrying in 15s..."); time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Unrecoverable polling error: {e}", exc_info=True)
            logger.info("Restarting polling in 30s due to critical error..."); time.sleep(30)
        finally: logger.warning("Polling attempt finished. Will restart if in loop."); time.sleep(1)
