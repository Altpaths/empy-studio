from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Literal, cast

TokenUsageSource = Literal["provider", "estimate", "mixed", "unknown"]

_VALID_SOURCES: set[str] = {"provider", "estimate", "mixed", "unknown"}
_INPUT_KEYS = (
    "input_tokens",
    "prompt_tokens",
    "tokens_in",
    "input",
    "prompt",
    "request_tokens",
)
_OUTPUT_KEYS = (
    "output_tokens",
    "completion_tokens",
    "tokens_out",
    "output",
    "completion",
    "response_tokens",
)
_CACHED_KEYS = (
    "cached_tokens",
    "cached_input_tokens",
    "input_cached_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
_TOTAL_KEYS = ("total_tokens", "total", "tokens_total")
_ESTIMATE_KEYS = (
    "estimated_tokens",
    "estimated_total_tokens",
    "token_estimate",
    "estimated_input_tokens",
    "estimated_output_tokens",
)


@dataclass(frozen=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    cached: int = 0
    total: int = 0
    source: TokenUsageSource = "unknown"
    provider: str | None = None

    @property
    def input_tokens(self) -> int:
        return self.input

    @property
    def output_tokens(self) -> int:
        return self.output

    @property
    def cached_input_tokens(self) -> int:
        return self.cached

    @property
    def total_tokens(self) -> int:
        return self.total

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for field_name, value in (
            ("input", self.input),
            ("output", self.output),
            ("cached", self.cached),
            ("total", self.total),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} tokens must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} tokens cannot be negative")
        if self.source not in _VALID_SOURCES:
            raise ValueError(f"unsupported token usage source: {self.source}")
        if self.total < max(self.input, self.output, self.cached):
            raise ValueError("total tokens cannot be smaller than component tokens")
        if self.provider is not None and not self.provider.strip():
            raise ValueError("token usage provider cannot be blank")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TokenUsage:
        input_tokens = _as_int(
            value.get("input", value.get("input_tokens", 0)),
            "input",
        )
        output_tokens = _as_int(
            value.get("output", value.get("output_tokens", 0)),
            "output",
        )
        cached_tokens = _as_int(
            value.get("cached", value.get("cached_input_tokens", 0)),
            "cached",
        )
        total = _as_int(
            value.get("total", value.get("total_tokens", input_tokens + output_tokens)),
            "total",
        )
        source = str(value.get("source", "unknown"))
        provider = value.get("provider")
        return cls(
            input=input_tokens,
            output=output_tokens,
            cached=cached_tokens,
            total=total,
            source=cast(TokenUsageSource, source),
            provider=str(provider) if provider is not None else None,
        )

    @classmethod
    def from_provider_mapping(
        cls,
        value: Mapping[str, object],
        *,
        default_provider: str | None = None,
    ) -> TokenUsage | None:
        usage = _usage_from_mapping(value, default_provider=default_provider)
        if usage is None:
            return None
        usage.validate()
        return usage

    @classmethod
    def extract_from_event(
        cls,
        event: Mapping[str, object],
        *,
        default_provider: str | None = None,
    ) -> TokenUsage | None:
        usages = cls.extract_all(event, default_provider=default_provider)
        if not usages:
            return None
        return cls.aggregate(usages)

    @classmethod
    def extract_all(
        cls,
        value: object,
        *,
        default_provider: str | None = None,
    ) -> tuple[TokenUsage, ...]:
        return tuple(_extract_usages(value, default_provider=default_provider))

    @classmethod
    def aggregate(
        cls,
        values: Iterable[TokenUsage | None],
        *,
        provider: str | None = None,
    ) -> TokenUsage | None:
        usages = [value for value in values if value is not None]
        if not usages:
            return None
        input_tokens = sum(value.input for value in usages)
        output_tokens = sum(value.output for value in usages)
        cached_tokens = sum(value.cached for value in usages)
        total = sum(value.total for value in usages)
        sources = {value.source for value in usages if value.source != "unknown"}
        if not sources:
            source: TokenUsageSource = "unknown"
        elif len(sources) == 1:
            source = sources.pop()
        else:
            source = "mixed"
        providers = {value.provider for value in usages if value.provider is not None}
        aggregate_provider = provider or (providers.pop() if len(providers) == 1 else None)
        return cls(
            input=input_tokens,
            output=output_tokens,
            cached=cached_tokens,
            total=total,
            source=source,
            provider=aggregate_provider,
        )


def _extract_usages(
    value: object,
    *,
    default_provider: str | None,
) -> Iterable[TokenUsage]:
    if isinstance(value, Mapping):
        direct = _usage_from_mapping(value, default_provider=default_provider)
        if direct is not None:
            yield direct
            return
        for item in value.values():
            yield from _extract_usages(item, default_provider=default_provider)
    elif isinstance(value, list):
        for item in value:
            yield from _extract_usages(item, default_provider=default_provider)


def _usage_from_mapping(
    value: Mapping[str, object],
    *,
    default_provider: str | None,
) -> TokenUsage | None:
    if not _looks_like_usage(value):
        return None
    input_tokens = _first_int(value, _INPUT_KEYS)
    output_tokens = _first_int(value, _OUTPUT_KEYS)
    cached_tokens = _first_int(value, _CACHED_KEYS)
    total = _first_int(value, _TOTAL_KEYS)

    details = value.get("prompt_tokens_details")
    if cached_tokens is None and isinstance(details, Mapping):
        cached_tokens = _first_int(details, _CACHED_KEYS)
    details = value.get("input_tokens_details") or value.get("input_token_details")
    if cached_tokens is None and isinstance(details, Mapping):
        cached_tokens = _first_int(details, _CACHED_KEYS)

    if input_tokens is None:
        input_tokens = _first_int(value, ("estimated_input_tokens",))
    if output_tokens is None:
        output_tokens = _first_int(value, ("estimated_output_tokens",))
    if total is None:
        total = _first_int(value, _ESTIMATE_KEYS)

    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    cached_tokens = cached_tokens or 0
    total = total if total is not None else input_tokens + output_tokens
    if total == 0 and input_tokens == 0 and output_tokens == 0 and cached_tokens == 0:
        return None

    raw_source = value.get("source") or value.get("usage_source")
    source = str(raw_source) if raw_source is not None else ""
    if source not in _VALID_SOURCES:
        source = (
            "estimate"
            if any(key in value for key in _ESTIMATE_KEYS)
            else "provider"
        )
    provider = (
        value.get("provider")
        or value.get("provider_id")
        or value.get("model_provider")
        or default_provider
    )
    return TokenUsage(
        input=input_tokens,
        output=output_tokens,
        cached=cached_tokens,
        total=max(total, input_tokens, output_tokens, cached_tokens),
        source=cast(TokenUsageSource, source),
        provider=str(provider) if provider is not None else None,
    )


def _looks_like_usage(value: Mapping[str, object]) -> bool:
    keys = set(value)
    return bool(
        keys.intersection(_INPUT_KEYS)
        or keys.intersection(_OUTPUT_KEYS)
        or keys.intersection(_CACHED_KEYS)
        or keys.intersection(_TOTAL_KEYS)
        or keys.intersection(_ESTIMATE_KEYS)
        or "prompt_tokens_details" in keys
        or "input_tokens_details" in keys
        or "input_token_details" in keys
    )


def _first_int(value: Mapping[str, object], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key not in value:
            continue
        parsed = _optional_int(value[key])
        if parsed is not None:
            return parsed
    return None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, Mapping):
        for key in ("total", "count", "tokens", "value"):
            if key in value:
                parsed = _optional_int(value[key])
                if parsed is not None:
                    return parsed
    return None


def _as_int(value: object, field_name: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise TypeError(f"{field_name} tokens must be an integer")
    return parsed
