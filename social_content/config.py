"""설정 로딩.

브랜드 설명·톤·출력 위치는 `config.json` 에서 읽는다.
**API 키만은 여기에 적지 않는다.** config.json 은 저장소에 올라가는 파일이라,
키를 적으면 "키를 코드에 쓰지 않는다"가 무너진다. 어느 환경 변수를 볼지만 적는다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.json"
PLACEHOLDERS = {"", "your-api-key", "changeme", "xxx", "todo"}
VALID_TONES = {"friendly", "professional"}


class ConfigError(Exception):
    """설정이 없거나 값이 어긋날 때."""


def load_dotenv(path: Path | None = None) -> None:
    """`.env` 를 읽어 환경 변수에 넣는다. 이미 있는 값은 덮어쓰지 않는다."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        # setdefault 만 쓰면 값이 빈 문자열인 환경 변수도 "이미 있음"으로 보아
        # .env 의 진짜 값을 덮지 못한다. CI 나 셸에 `GEMINI_API_KEY=` 가 남아 있으면
        # .env 에 키를 제대로 넣어 두고도 "키가 없습니다" 를 보게 된다.
        if not os.environ.get(key, "").strip():
            os.environ[key] = value


def _number(section: dict, key: str, default, cast):
    """설정에서 숫자를 읽는다. 숫자가 아니면 ConfigError 로 알린다.

    `int(...)` 를 그대로 쓰면 `"120초"` 같은 값에서 ValueError 가 나는데,
    main 은 ConfigError 만 잡으므로 이것만 raw traceback 으로 끝난다.
    """
    raw = section.get(key, default)
    try:
        return cast(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} 는 숫자여야 합니다: {raw!r}") from None


@dataclass(frozen=True)
class Config:
    brand: str
    tones: list[str]
    llm_provider: str
    llm_api_key_env: str
    timeout_sec: int
    output_dir: Path

    @property
    def llm_api_key(self) -> str | None:
        value = (os.environ.get(self.llm_api_key_env) or "").strip()
        return None if value.lower() in PLACEHOLDERS else value


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv()
    path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not path.exists():
        raise ConfigError(
            f"설정 파일이 없습니다: {path}\n"
            "     config.example.json 을 config.json 으로 복사한 뒤 값을 채우세요."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} 의 JSON 형식이 잘못되었습니다 ({exc.lineno}행): {exc.msg}") from None

    brand = str(data.get("brand", "")).strip()
    if not brand:
        raise ConfigError("config.json 에 'brand' 설명이 필요합니다. 프롬프트의 문맥이 됩니다.")

    tones = [str(tone).lower() for tone in (data.get("tones") or ["friendly"])]
    unknown = set(tones) - VALID_TONES
    if unknown:
        raise ConfigError(f"tones 는 {', '.join(sorted(VALID_TONES))} 만 쓸 수 있습니다: {unknown}")

    ai = data.get("ai", {})
    provider = str(ai.get("provider", "gemini")).lower()
    if provider not in {"gemini", "openai"}:
        raise ConfigError(f"ai.provider 는 gemini 또는 openai 여야 합니다: {provider!r}")

    # tones·provider 는 값을 검사하는데 timeout 만 빠져 있었다. 0 이나 음수를
    # 그대로 넘기면 requests 가 ValueError 를 던지는데, 그건 RequestException 이
    # 아니라 재시도 처리에 걸리지 않는다.
    timeout_sec = _number(ai, "timeout_sec", 120, int)
    if timeout_sec < 1:
        raise ConfigError(f"ai.timeout_sec 는 1 이상이어야 합니다: {timeout_sec}")

    return Config(
        brand=brand,
        tones=tones,
        llm_provider=provider,
        llm_api_key_env=str(ai.get("api_key_env", "GEMINI_API_KEY")),
        timeout_sec=timeout_sec,
        output_dir=(ROOT / str(data.get("output_dir", "output"))).resolve(),
    )
