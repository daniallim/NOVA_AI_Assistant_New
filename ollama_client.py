import requests
from config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_AUTO_FALLBACK,
    SYSTEM_PROMPT,
)


class OllamaClient:
    def __init__(self, model=OLLAMA_MODEL):
        self.model = model
        self.resolved = False

    # ------------------------------------------------------------------
    def available_models(self):
        """Names exactly as 'ollama list' shows them."""
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    def resolve_model(self):
        """
        Make sure self.model is a model Ollama actually has.
        Handles 'gemma4' vs 'gemma4:12b' and falls back to the largest
        installed model if the configured one is missing.
        """
        if self.resolved:
            return self.model

        models = self.available_models()
        if not models:
            return self.model          # Ollama offline; let chat() raise

        if self.model in models:
            self.resolved = True
            return self.model

        # Try a tag-less match, e.g. configured "gemma4" -> installed "gemma4:12b"
        base = self.model.split(":")[0]
        for name in models:
            if name.split(":")[0] == base:
                print(f"[NOVA] Model '{self.model}' not found, using '{name}'.")
                self.model = name
                self.resolved = True
                return self.model

        if OLLAMA_AUTO_FALLBACK:
            print(
                f"[NOVA] Model '{self.model}' is not installed. "
                f"Installed: {', '.join(models)}. Using '{models[0]}'."
            )
            self.model = models[0]
            self.resolved = True
        return self.model

    # ------------------------------------------------------------------
    def is_online(self):
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
            return r.ok
        except requests.RequestException:
            return False

    def chat(self, messages):
        model = self.resolve_model()
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "stream": False,
            "options": {
                "temperature": 0.35,
                "num_ctx": 8192,
            },
        }
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
        if r.status_code == 404:
            raise RuntimeError(
                f"Ollama does not have a model named '{model}'. "
                f"Run 'ollama list' and set OLLAMA_MODEL in config.py to a listed NAME."
            )
        r.raise_for_status()
        return r.json()["message"]["content"]
