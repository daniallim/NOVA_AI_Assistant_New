# NOVA AI Assistant

A local-first futuristic desktop AI assistant for Windows.

## Stack

- Python
- PySide6 / Qt
- Ollama for the local LLM
- MySQL memory (SQLite fallback) - see SETUP_MYSQL.md
- psutil system monitoring
- sounddevice + SpeechRecognition for optional microphone input
- pyttsx3 for optional offline TTS
- pynput for optional mouse/keyboard automation

## Model

NOVA is configured for the model you already have installed:

    gemma4:12b

Change it in `config.py` (`OLLAMA_MODEL`). The value must match a NAME from
`ollama list`. If it does not, NOVA auto-selects an installed model and says so.

## Database

NOVA stores everything in MySQL so you can inspect it in MySQL Workbench:
users, conversations, messages, memories, tasks, tool_logs.

Set your password in `mysql_config.py`, then run:

    python setup_database.py

Full instructions: **SETUP_MYSQL.md**

## Run

1. Install Python 3.11+.
2. Install Ollama and make sure it is running.
3. Open PowerShell in this folder.
4. Create a virtual environment:
   `python -m venv .venv`
5. Activate it:
   `.venv\Scripts\Activate.ps1`
6. Install packages:
   `pip install -r requirements.txt`
7. Make sure your model is present:
   `ollama list`
8. Create the database:
   `python setup_database.py`
9. Run:
   `python main.py`

Or just double-click `run_nova.bat`, which does all of the above.

## Features

- Black/cyan futuristic HUD interface
- Animated AI core
- Live CPU/RAM/GPU monitoring
- Local Ollama chat
- SQLite conversation memory
- Voice input button
- Offline text-to-speech
- Safe PC tools: open apps, system info, screenshot, list files
- Tool execution requires explicit confirmation for higher-risk actions
- Generated UI sound effects
- Keyboard shortcut: Ctrl+Shift+Space toggles listening

## Important

This is an advanced working foundation, not movie-level AGI. The agent only has the tools explicitly implemented in `tools.py`.

## What's new in 2.0

- MySQL backend with a 6-table relational schema (+ `v_chat_history` view)
- Automatic SQLite fallback if MySQL is unreachable, so NOVA always starts
- Memories now have `memory_type` and `importance` (1-10); context is built
  from the highest-importance memories first
- Every tool run is recorded in `tasks` and `tool_logs`, including ones
  blocked by SAFE MODE
- New tools: `recall`, `db_stats`
- New DATABASE button showing live row counts and recent tool activity
- Conversations are titled from your first message
- Ollama model auto-resolution with a clear error if the model is missing
