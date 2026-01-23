"""
LLM Client for Mini Claude

Handles communication with the local Ollama instance.
Includes retry logic and health checking.

Environment variables:
- MINI_CLAUDE_MODEL: Which Ollama model to use (default: qwen2.5-coder:7b)
- MINI_CLAUDE_OLLAMA_URL: Ollama API URL (default: http://localhost:11434)
- MINI_CLAUDE_TIMEOUT: Timeout in seconds for LLM calls (default: 300)
"""

import httpx
import os
import time
from typing import Optional


# Default model - can be overridden via environment variable
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_TIMEOUT = 300.0  # 5 minutes - local LLMs on slow machines need time


class LLMClient:
    """Client for communicating with Ollama API."""

    def __init__(
        self,
        base_url: str = None,
        model: str = None,
        timeout: float = None,
        max_retries: int = 3,
    ):
        # Allow environment variables to override defaults
        self.base_url = base_url or os.environ.get("MINI_CLAUDE_OLLAMA_URL", "http://localhost:11434")
        self.model = model or os.environ.get("MINI_CLAUDE_MODEL", DEFAULT_MODEL)
        # Timeout: explicit param > env var > default (300s)
        if timeout is not None:
            self.timeout = timeout
        else:
            env_timeout = os.environ.get("MINI_CLAUDE_TIMEOUT")
            self.timeout = float(env_timeout) if env_timeout else DEFAULT_TIMEOUT
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=self.timeout)
        self._last_health_check: Optional[float] = None
        self._is_healthy: bool = False

    def health_check(self) -> dict:
        """
        Check if Ollama is running and the model is available.
        """
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return {
                    "healthy": False,
                    "error": f"Ollama returned status {response.status_code}",
                    "suggestion": "Is Ollama running? Try: ollama serve"
                }

            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            model_available = any(
                self.model in name or name in self.model
                for name in model_names
            )

            if not model_available:
                return {
                    "healthy": False,
                    "error": f"Model '{self.model}' not found",
                    "available_models": model_names,
                    "suggestion": f"Try: ollama pull {self.model}"
                }

            self._is_healthy = True
            self._last_health_check = time.time()

            return {
                "healthy": True,
                "model": self.model,
                "available_models": model_names
            }

        except httpx.ConnectError:
            return {
                "healthy": False,
                "error": "Cannot connect to Ollama",
                "suggestion": "Start Ollama with: ollama serve"
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        timeout: Optional[float] = None,
    ) -> dict:
        """
        Generate a response from the local model.

        Args:
            prompt: The prompt to send to the model
            system: Optional system prompt
            temperature: Sampling temperature (default 0.1)
            timeout: Override timeout for this call (seconds). Default uses client timeout.

        Returns a dict with:
        - success: bool
        - response: str (if successful)
        - error: str (if failed)
        - retries_used: int
        - time_taken_ms: int
        """
        start_time = time.time()
        last_error = None
        call_timeout = timeout if timeout is not None else self.timeout

        for attempt in range(self.max_retries):
            try:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": 0,  # Unload model after use to free GPU memory
                    "options": {
                        "temperature": temperature,
                    }
                }

                if system:
                    payload["system"] = system

                response = self._client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=call_timeout,
                )

                if response.status_code == 200:
                    result = response.json()
                    return {
                        "success": True,
                        "response": result.get("response", ""),
                        "retries_used": attempt,
                        "time_taken_ms": int((time.time() - start_time) * 1000),
                    }
                else:
                    last_error = f"HTTP {response.status_code}: {response.text}"

            except httpx.TimeoutException:
                last_error = f"Timeout after {call_timeout}s"
            except httpx.ConnectError:
                last_error = "Connection refused - is Ollama running?"
            except Exception as e:
                last_error = str(e)

            # Wait before retry (exponential backoff)
            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        return {
            "success": False,
            "error": last_error,
            "retries_used": self.max_retries,
            "time_taken_ms": int((time.time() - start_time) * 1000),
        }

    def analyze_code(self, code: str, question: str) -> dict:
        """Ask the model to analyze code and answer a question about it."""
        system_prompt = """You are Mini Claude, a code analysis assistant.
Analyze the provided code and answer questions about it.
Be concise but thorough. Focus on what's actually in the code.
If you're uncertain, say so. Don't make things up."""

        prompt = f"""## Code to Analyze
```
{code}
```

## Question
{question}

## Your Analysis
Provide a clear, factual analysis:"""

        return self.generate(prompt, system=system_prompt)

    def summarize_file(self, content: str, filepath: str) -> dict:
        """Get a brief summary of what a file does."""
        system_prompt = """You are Mini Claude, a code analysis assistant.
Summarize what this file does in 1-2 sentences.
Focus on the main purpose, not implementation details."""

        prompt = f"""## File: {filepath}
```
{content[:4000]}
```

## Summary (1-2 sentences):"""

        return self.generate(prompt, system=system_prompt, temperature=0.0)

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
