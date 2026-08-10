"""Config override layer for the self-optimization subsystem.

Turns a subset of ``settings`` fields into properties whose values resolve
through three layers, in order:

    .env / environment          → cold-start baseline (never written here)
      ↓
    champion row in state.db    → process-wide active config (set_champion)
      ↓
    ContextVar per-request      → challenger config for canary-bucketed traffic

Only the whitelisted ``TUNABLES`` are replaced (the spec's "targeted property
injection" from §3.1). A ``property`` is a data descriptor, so it shadows
Pydantic v2's instance ``__dict__`` for those names; every other attribute
(``cohere_api_key``, ``neo4j_password``, paths, flags) uses native lookup at
zero cost.

Requests already run in their own context, and ``run_in_threadpool`` /
``contextvars`` propagate that context, so canary and champion traffic coexist
without interference: a request under a challenger context reads the
challenger's values, every other request reads the champion.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

from ..config import Settings, settings

# name -> (low, high, is_int). Never tunable: secrets, credentials, paths, CORS,
# environment flags. If a field is tunable it MUST appear here with its range.
TUNABLES: dict[str, tuple[float, float, bool]] = {
    "chunk_size": (128, 2048, True),
    "chunk_overlap": (0, 512, True),
    "retrieve_top_k": (1, 50, True),
    "rerank_top_n": (1, 20, True),
    "rerank_min_score": (0.0, 0.9, False),
    "expand_hops": (1, 3, True),
    "graph_fusion_beta": (0.0, 1.0, False),
    "abstain_below_score": (0.0, 0.9, False),
    "entity_match_threshold": (0.5, 0.99, False),
    "graph_confidence_threshold": (0.5, 0.99, False),
    "expansion_relevance_threshold": (0.0, 0.9, False),
    "edge_decay": (0.0, 0.5, False),
    "graphsage_alpha": (0.0, 1.0, False),
    "graphsage_epochs": (5, 50, True),
}

# Cross-field invariants enforced by validate(). Only applied when the fields
# they reference are actually present in the proposed config, so an empty delta
# (valid: it means "keep the champion") never trips them.
_CROSS_FIELDS = (
    (
        "chunk_overlap must be < chunk_size",
        lambda c: "chunk_size" not in c or "chunk_overlap" not in c or c["chunk_overlap"] < c["chunk_size"],
    ),
    (
        "rerank_top_n must be <= retrieve_top_k",
        lambda c: "retrieve_top_k" not in c or "rerank_top_n" not in c or c["rerank_top_n"] <= c["retrieve_top_k"],
    ),
)


class InvalidConfigError(ValueError):
    """A challenger failed validation. Discarded at proposal time, never a cycle."""


# --- Override state ---------------------------------------------------------

_baseline: dict[str, float | int] = {}      # native .env values, captured at install
_champion: dict[str, float | int] = {}      # process-wide champion config
_champion_version: str | None = None        # version id the champion params belong to
# Per-request challenger context: {"params": {...}, "version": str|None} or None.
_ctx: contextvars.ContextVar = contextvars.ContextVar("selfopt_overrides", default=None)


def _effective_config() -> dict[str, float | int]:
    """Champion + challenger overlay over the hard-start baseline."""
    merged = dict(_baseline)
    merged.update(_champion)
    ctx = _ctx.get()
    if ctx:
        merged.update(ctx["params"])
    return merged


def _make_prop(name: str):
    def _get(self) -> float | int:
        return _effective_config().get(name, _baseline.get(name))
    return property(_get)


# --- Lifecycle --------------------------------------------------------------

def install() -> None:
    """Replace the tunable fields with override-aware properties (idempotent).

    Reads the current native values into ``_baseline`` so the fallback is
    always the original `.env` value, then drops the `property` in place. After
    this, ``getattr(settings, name)`` routes through the layer for every caller
    in the process, including threaded retrievals.
    """
    for name, (lo, hi, is_int) in TUNABLES.items():
        if name not in _baseline:
            _baseline[name] = getattr(settings, name)
        setattr(Settings, name, _make_prop(name))


def uninstall() -> None:
    """Contract: drop the override layer and restore native reads.

    Removing the class property leaves the value stored in the router instance's
    ``__dict__`` (the Pydantic-validated native value) visible again, so
    ``settings.<field>`` reads exactly as before ``install()``. Used by the
    self-destruct sequence to make the optimizer exit clean.
    """
    for name in TUNABLES:
        try:
            delattr(Settings, name)
        except AttributeError:
            pass
    _champion.clear()
    global _champion_version
    _champion_version = None
    _ctx.set(None)


def release_all() -> None:
    """Drop the override layer entirely (self-destruct / disabled start)."""
    uninstall()


def sync_champion_changes() -> None:
    """On boot, publish the persisted champion so the process serves it from
    the first request (spec §4: champion row → process-wide active config)."""
    from . import store

    params = store.get_champion()
    if params is None:
        return
    set_champion(params, store.get_champion_version())
    store.record_activity(
        store.KIND_SYSTEM,
        f"boot: published champion {store.get_champion_version()} as active config",
        store.get_champion_version(),
    )


def set_champion(params: dict, version: str | None = None) -> None:
    """Publish a new process-wide champion config. Raises if invalid.

    ``params`` becomes the default for every request not inside a challenger
    context. ``version`` is recorded for attribution (``current_version()``).
    """
    validate(params or {})
    _champion.update(params or {})
    global _champion_version
    _champion_version = version


def active_version() -> str | None:
    """The version this context belongs to: challenger's, or the champion's.

    Unstable ids (fresh per-call anonymous guests) must not plainly count as
    findings, so attribution comes from the override context when the request
    is a canary, else the champion version.
    """
    ctx = _ctx.get()
    if ctx is not None:
        return ctx.get("version") or _champion_version
    return _champion_version


def current_config() -> dict[str, float | int]:
    """Copy of the active config (champion + any challenger overlay)."""
    return dict(_effective_config())


@contextmanager
def challenger(params: dict, version: str | None = None):
    """Run a code block under a challenger config for canary-bucketed requests.

    ``params`` may be a partial overlay — keys not present fall through to the
    champion or the hard-start baseline. ``version`` labels the context so
    ``active_version()`` attributes collected metrics correctly.
    """
    validate(params or {})
    token = _ctx.set({"params": params, "version": version or _champion_version})
    try:
        yield
    finally:
        _ctx.reset(token)


# --- Validation -------------------------------------------------------------

def validate(cfg: dict) -> None:
    """Reject a challenger that violates the whitelist or range bounds.

    Raises ``InvalidConfigError`` (a ``ValueError``) on any violation. An empty
    dict passes: ``propose()`` can legitimately produce a no-op delta after
    clamping, and it means "keep the champion' as-is.
    """
    unknown = set(cfg) - set(TUNABLES)
    if unknown:
        raise InvalidConfigError(f"unknown tunable field(s): {sorted(unknown)}")

    for name in TUNABLES:
        if name not in cfg:
            continue
        value = cfg[name]
        if value is None:
            raise InvalidConfigError(f"{name} must not be None")
        low, high, is_int = TUNABLES[name]
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise InvalidConfigError(f"{name} must be numeric, got {value!r}")
        if is_int and float(value) != int(value):
            raise InvalidConfigError(f"{name} must be an integer, got {value!r}")
        if not (low <= numeric <= high):
            raise InvalidConfigError(
                f"{name} ({value!r}) out of range [{low}, {high}]"
            )

    for msg, fn in _CROSS_FIELDS:
        if not fn(cfg):
            raise InvalidConfigError(msg)