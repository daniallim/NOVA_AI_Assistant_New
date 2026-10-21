"""
Model client for NOVA - now talks to LM Studio's local server
(OpenAI-compatible API) instead of Ollama.

The class is still called OllamaClient so ui.py doesn't need changing;
LMStudioClient is an alias for readability.

In LM Studio: open the "Developer" tab (or "Local Server"), load your model,
and click "Start Server". Default address is http://127.0.0.1:1234
"""

import requests
import config
from config import SYSTEM_PROMPT

# Read with defaults so this works whatever you named things in config.py.
LMSTUDIO_URL = getattr(config, "LMSTUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMSTUDIO_MODEL = getattr(config, "LMSTUDIO_MODEL", "")
AUTO_FALLBACK = getattr(config, "OLLAMA_AUTO_FALLBACK", False)
TEMPERATURE = getattr(config, "MODEL_TEMPERATURE", 0.35)
MAX_TOKENS = getattr(config, "MODEL_MAX_TOKENS", 1024)


def _normalize_messages(messages):
    """
    Many local chat templates (Mistral/Ministral especially) reject:
      - a 'system' message anywhere except the very start
      - two messages in a row with the same role
    NOVA's tool loop injects a system note mid-conversation, so we convert
    those to 'user' and merge consecutive same-role messages.
    """
    cleaned = []
    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "tool":
            role = "user"
            content = f"[tool result]\n{content}"
        elif role == "system":
            role = "user"
            content = f"[system note]\n{content}"
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n\n" + content
        else:
            cleaned.append({"role": role, "content": content})

    # Conversation should start with a user turn.
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


class OllamaClient:
    def __init__(self, model=None):
        self.model = model or LMSTUDIO_MODEL
        self.resolved = False

    # ------------------------------------------------------------------
    def available_models(self):
        """Model IDs exactly as LM Studio's API lists them."""
        try:
            r = requests.get(f"{LMSTUDIO_URL}/models", timeout=3)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
        except (requests.RequestException, ValueError, KeyError):
            return []

    def resolve_model(self):
        if self.resolved:
            return self.model

        models = self.available_models()
        if not models:
            return self.model  # server offline; chat() will raise a clear error

        if self.model in models:
            self.resolved = True
            return self.model

        if AUTO_FALLBACK or not self.model:
            usable = [m for m in models if "embed" not in m.lower()]
            if usable:
                print(
                    f"[NOVA] Model '{self.model}' not found in LM Studio. "
                    f"Using '{usable[0]}'. Available: {', '.join(models)}"
                )
                self.model = usable[0]
                self.resolved = True
        else:
            print(
                f"[NOVA] Model '{self.model}' not in LM Studio's list: "
                f"{', '.join(models)}. LM Studio may still load it on demand."
            )
        return self.model

    # ------------------------------------------------------------------
    def is_online(self):
        try:
            r = requests.get(f"{LMSTUDIO_URL}/models", timeout=2)
            return r.ok
        except requests.RequestException:
            return False

    def chat(self, messages):
        model = self.resolve_model()
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}]
            + _normalize_messages(messages),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
        try:
            r = requests.post(
                f"{LMSTUDIO_URL}/chat/completions", json=payload, timeout=300
            )
        except requests.ConnectionError:
            raise RuntimeError(
                "Can't reach LM Studio at "
                f"{LMSTUDIO_URL}. Open LM Studio, load your model, and start "
                "the Local Server (Developer tab -> Start Server)."
            )

        if not r.ok:
            try:
                detail = r.json().get("error", {})
                detail = detail.get("message", detail) if isinstance(detail, dict) else detail
            except ValueError:
                detail = r.text[:300]
            raise RuntimeError(
                f"LM Studio returned {r.status_code} for model '{model}': {detail}"
            )

        data = r.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected reply from LM Studio: {str(data)[:300]}")


LMStudioClient = OllamaClient