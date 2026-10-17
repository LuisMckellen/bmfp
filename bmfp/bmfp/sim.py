"""The discrete-event simulation of one BMFP cell.

``Config`` lists every knob; each field's metadata says whether the value is an input
taken from the journal (``JOURNAL vX``), an assumption of this simulator
(``ASSUMPTION``), a choice made where the journal was ambiguous (``FORMALISATION``), or a
proposed fix that is not in the journal (``PROPOSED FIX``). See SPEC.md for the rules.

Determinism: all randomness comes from ``random.Random`` instances seeded from
``Config.seed`` (one independent stream per concern, so e.g. changing the routing mode does
not change who sends to whom, and changing the initial STANDBY share does not change the
hotspot node or the checkpoint phase). No wall clock is read.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import asdict, dataclass, field, fields

from . import events as ev
from .cell import (
    ACTIVE,
    DEAD_CHAR,
    GHOST,
    STANDBY,
    STATE_CHARS,
    Node,
    components,
    find_swap,
    is_cds,
    repair_cds,
)
from .metrics import (
    DROP_REASONS,
    RunResult,
    Series,
    per,
    percentile,
    recovery_metrics,
)
from .routing import (
    ADAPTIVE_DUPLICATE,
    ADAPTIVE_STRIPE,
    CHILL,
    DUPLICATE,
    ROUTINGS,
    STRIPE,
    TokenBucket,
    bfs_counts,
    disjoint_paths,
    sample_path,
)
from .topology import cage, far_triple, stem_triple

VSEPR_MODES = ("naive", "damped", "off")
VSEPR_AVERAGES = ("active", "cell")
ROTATION_SOURCES = ("vsepr", "vsepr_repair", "fairness", "resonance")
FLAP_CYCLES = 2  # a reversal within this many VSEPR periods counts as a flap (spec)


def _f(default, src: str, doc: str):
    return field(default=default, metadata={"src": src, "doc": doc})


@dataclass
class Config:
    """Simulation parameters. ``src`` metadata: JOURNAL / ASSUMPTION / FORMALISATION / FIX."""

    cage: str = _f("C60", "JOURNAL v1.0, v1.7", "cell topology (C12, C20, C24, C60)")
    duration: float = _f(600.0, "ASSUMPTION", "simulated seconds")
    seed: int = _f(0, "ASSUMPTION", "seed for every random stream")
    send_rate: float = _f(20.0, "ASSUMPTION", "messages/s for the whole cell, Poisson")
    hotspot_fraction: float = _f(
        0.3, "ASSUMPTION", "share of messages addressed to one popular node"
    )
    hotspot_node: int | None = _f(None, "ASSUMPTION", "popular node id; None = drawn from the seed")
    routing: str = _f(
        "chill",
        "JOURNAL v1.2 (readings: FORMALISATION)",
        "chill | duplicate | stripe | adaptive_duplicate | adaptive_stripe",
    )
    k_paths: int = _f(3, "JOURNAL v1.0/v1.2", "max node-disjoint paths ('3 exits per node')")
    adaptive_threshold: float = _f(
        0.9,
        "ASSUMPTION",
        "switch to hell above this relay utilisation (borrows v1.7a's 90% flash-wake trigger, "
        "which grows the cell; the journal gives no hell-mode trigger)",
    )
    path_rotation: bool = _f(True, "JOURNAL v1.4", "uniform choice among equal shortest paths")
    relay_capacity: float = _f(
        40.0, "ASSUMPTION", "relayed msg-equivalents/s per relay (token bucket rate)"
    )
    relay_burst: float = _f(10.0, "ASSUMPTION", "token bucket burst")
    hop_latency: float = _f(
        0.005,
        "ASSUMPTION",
        "s per hop (derived from v1.7a's 'edge cluster under 5 ms RTT', a whole-path bound)",
    )
    link_loss: float = _f(0.0, "ASSUMPTION", "per-hop loss probability")
    max_retries: int = _f(2, "JOURNAL v1.3 (count: ASSUMPTION)", "end-to-end ARQ resends")
    retry_timeout: float = _f(0.2, "ASSUMPTION", "s before an ARQ resend")
    active_fraction: float = _f(0.35, "ASSUMPTION", "initial ACTIVE share of slots")
    standby_fraction: float = _f(
        0.3, "ASSUMPTION", "initial STANDBY share of the slots left after ACTIVE"
    )
    stem_count: int = _f(3, "JOURNAL v1.7e", "permanent ACTIVE stem nodes")
    resonance: str = _f("on", "JOURNAL v1.7b", "on | off")
    resonance_period: float = _f(
        10.0, "ASSUMPTION", "s between resonance rounds (journal: 'continuously')"
    )
    resonance_phase: float | None = _f(
        None, "FORMALISATION", "first resonance time; None = period/2 (between VSEPR ticks)"
    )
    resonance_swaps: int = _f(2, "ASSUMPTION", "max ACTIVE<->STANDBY swaps per round")
    vsepr: str = _f("naive", "JOURNAL v1.7d", "naive | damped | off")
    vsepr_period: float = _f(30.0, "JOURNAL v1.7d", "s between VSEPR cycles")
    vsepr_factor: float = _f(2.0, "JOURNAL v1.7d", "demote above factor x average load")
    vsepr_average: str = _f(
        "active",
        "FORMALISATION",
        "the 'cell average' of v1.7d: active = mean over ACTIVE relays | cell = mean over "
        "every believed-alive node (sleeping ones carry 0)",
    )
    vsepr_promote: int = _f(2, "JOURNAL v1.7d", "GHOSTs promoted per demotion (naive)")
    vsepr_cooldown_cycles: int = _f(2, "PROPOSED FIX", "damped: hysteresis/cooldown cycles")
    vsepr_max_demotions_frac: float = _f(
        0.1, "PROPOSED FIX", "damped: max demotions per cycle / |ACTIVE|"
    )
    fairness_max_ghost_cycles: int = _f(2, "JOURNAL v1.7c", "max consecutive GHOST cycles")
    captain_count: int = _f(3, "JOURNAL v1.7c", "captains per cell")
    captain_term: float = _f(300.0, "JOURNAL v1.7c", "s per captain term (5 minutes)")
    detect_delay: float = _f(3.0, "JOURNAL v1.7e", "s from failure to detection (input)")
    checkpoint_period: float = _f(10.0, "JOURNAL v1.7e", "s between STATE_CHECKPOINTs")
    checkpoint_phase: float | None = _f(
        None, "ASSUMPTION", "first checkpoint time; None = uniform in [0, period) from the seed"
    )
    death_threshold: float = _f(
        0.5, "JOURNAL v1.7e", "CELL_DEATH_EVENT when MORE than this share is unreachable"
    )
    mitosis_time: float = _f(1.5, "JOURNAL v1.7e", "s to rebuild after partial death (input)")
    meiosis_time: float = _f(1.5, "JOURNAL v1.7e", "s to respawn after total death (input)")
    churn_rate: float = _f(0.0, "ASSUMPTION (Part IX)", "node leaves/s for the cell, Poisson")
    rejoin_delay: float = _f(20.0, "ASSUMPTION", "s until a vacant slot gets a fresh node")
    kill_at: float | None = _f(None, "JOURNAL Part IX", "scripted failure time (None = off)")
    kill_fraction: float = _f(0.5, "JOURNAL Part IX", "share of slots killed ('kill half')")
    record_frames: bool = _f(False, "ASSUMPTION", "record per-second frames for the website")

    def __post_init__(self) -> None:
        if self.routing not in ROUTINGS:
            raise ValueError(f"routing must be one of {ROUTINGS}")
        if self.vsepr not in VSEPR_MODES:
            raise ValueError(f"vsepr must be one of {VSEPR_MODES}")
        if self.vsepr_average not in VSEPR_AVERAGES:
            raise ValueError(f"vsepr_average must be one of {VSEPR_AVERAGES}")
        if self.resonance not in ("on", "off"):
            raise ValueError("resonance must be 'on' or 'off'")
        if self.duration <= 0:
            raise ValueError("duration must be positive")
        if not 0 <= self.hotspot_fraction <= 1 or not 0 <= self.link_loss <= 1:
            raise ValueError("fractions must be in [0, 1]")
        cage(self.cage)  # validates the name

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def provenance(cls) -> list[dict]:
        """One row per field: name, default, source label, description."""
        out = []
        for f in fields(cls):
            out.append(
                {
                    "name": f.name,
                    "default": f.default,
                    "src": f.metadata["src"],
                    "doc": f.metadata["doc"],
                }
            )
        return out


class Msg:
    __slots__ = (
        "id",
        "src",
        "dst",
        "seq",
        "t0",
        "attempts",
        "dst_alive",
        "bin",
        "src_inc",
        "to_asleep",
    )

    def __init__(self, mid, src, dst, seq, t0, dst_alive, b, src_inc=0, to_asleep=False):
        self.id = mid
        self.src = src
        self.dst = dst
        self.seq = seq
        self.t0 = t0
        self.attempts = 0
        self.dst_alive = dst_alive
        self.bin = b
        self.src_inc = src_inc  # the sending device's incarnation: a fresh node never resends
        self.to_asleep = to_asleep  # addressed to a believed-GHOST device when first sent


def _nodes(ids, empty: str = "no nodes") -> str:
    """Node ids named as ids: 'node 4', 'nodes 4, 9' (never a bare number that reads as a
    count)."""
    ids = list(ids)
    if not ids:
        return empty
    return ("node " if len(ids) == 1 else "nodes ") + ", ".join(str(i) for i in ids)


def _count(k: int, noun: str = "node") -> str:
    """A count named as a count: '1 node', '9 nodes'."""
    return f"{k} {noun}{'' if k == 1 else 's'}"


class Simulation:
    """One cell, one run. Call :meth:`run` once."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.g = cage(cfg.cage)
        self.adj = self.g.adj
        self.n = self.g.n
        s = cfg.seed
        self.traffic_rng = random.Random(f"bmfp-{s}-traffic")
        self.route_rng = random.Random(f"bmfp-{s}-route")
        self.loss_rng = random.Random(f"bmfp-{s}-loss")
        self.setup_rng = random.Random(f"bmfp-{s}-setup")  # the initial STANDBY sample only
        self.hotspot_rng = random.Random(f"bmfp-{s}-hotspot")
        self.checkpoint_rng = random.Random(f"bmfp-{s}-checkpoint")
        self.kill_rng = random.Random(f"bmfp-{s}-kill")
        self.churn_rng = random.Random(f"bmfp-{s}-churn")
        self.q = ev.EventQueue()
        self.series = Series(cfg.duration)
        self.events: list[dict] = []
        self.now = 0.0
        self.cycle = 0
        self.term = 0
        self.captains: list[int] = []
        self.stems: list[int] = []
        self.believed = [True] * self.n
        self.vacancy_gen = [0] * self.n
        self.relay_version = 0
        self._relay_cache_v = -1
        self._relay_mask: list[bool] = []
        self._bfs_cache: dict[int, tuple[list[int], list[int]]] = {}
        self.util_prev = 0.0
        self.bin_demand = 0.0
        # counters
        self.sent = 0
        self.delivered = 0
        self.drops: Counter[str] = Counter()
        self.fail_by_bin: Counter[tuple[int, str]] = Counter()
        self.attempts = 0
        self.retries = 0
        self.tx = 0.0
        self.duplicates = 0
        self.out_of_order = 0
        self.hops_sum = 0
        self.lat_sum = 0.0
        self.latencies: list[float] = []
        self.addressed_asleep = 0
        self.to_asleep_delivered = 0
        self.skipped_sends = 0
        self.hell_attempts = 0
        self.hell_paths = 0
        self.hell_single = 0
        self.flows: dict[tuple[int, int], int] = {}
        self.flow_max: dict[tuple[int, int], int] = {}
        self.msgs: dict[int, Msg] = {}
        self._next_mid = 0
        # rotation bookkeeping
        self.changes: Counter[str] = Counter()  # any A/S/G transition, by source
        self.active_changes: Counter[str] = Counter()  # ACTIVE boundary crossings, by source
        self.flaps = 0
        self.vsepr_flaps = 0
        self.demotions = 0
        self.promotions = 0
        self.vsepr_candidates = 0  # hot non-stem ACTIVE nodes above the threshold, per cycle
        self.vsepr_cooldown_skips = 0  # damped: candidates skipped by the cooldown
        self.vsepr_capped = 0  # damped: candidates left over by the per-cycle cap
        self.vsepr_no_swap = 0  # damped: no allowed one-for-one swap keeps a CDS
        self.vsepr_no_swap_any = 0  # ... nor any swap with any non-ACTIVE node
        self.vsepr_cycles = 0
        self.skipped_cycles = 0
        self.skipped_resonance = 0
        self.resonance_swaps_done = 0
        self.fairness_wakes = 0
        self.load_ratios: list[float] = []
        self.cycle_peaks: list[float] = []  # max window_load per VSEPR cycle
        self.cycle_avgs: list[float] = []  # mean window_load per VSEPR cycle
        self.cds_repairs = 0
        self.cds_impossible = 0
        self.skipped_repairs = 0
        self.split_since: float | None = None  # believed-alive graph disconnected since
        self.split_s = 0.0
        self.captain_reelections = 0
        self.captain_terms = 1
        self.checkpoints = 0
        self.last_cp: dict | None = None
        self.death_active = False
        self.death_events = 0
        self.leaves = 0
        self.joins = 0
        self.incident: dict | None = None
        self.frames: dict | None = (
            {"states": [], "loads": [], "stems": [], "captains": []} if cfg.record_frames else None
        )
        self._ran = False
        self._setup()

    # ------------------------------------------------------------------ helpers
    def log(self, t: float, kind: str, text: str) -> None:
        self.events.append({"t": round(t, 3), "kind": kind, "text": text})

    def believed_alive(self) -> list[int]:
        return [v for v in range(self.n) if self.believed[v]]

    def active_set(self) -> set[int]:
        nodes = self.nodes
        return {v for v in range(self.n) if self.believed[v] and nodes[v].state == ACTIVE}

    def _relay(self) -> list[bool]:
        if self._relay_cache_v != self.relay_version:
            nodes = self.nodes
            self._relay_mask = [
                self.believed[v] and nodes[v].state == ACTIVE for v in range(self.n)
            ]
            self._relay_cache_v = self.relay_version
            self._bfs_cache = {}
        return self._relay_mask

    def _bfs(self, src: int) -> tuple[list[int], list[int]]:
        relay = self._relay()
        hit = self._bfs_cache.get(src)
        if hit is None:
            hit = bfs_counts(self.adj, src, relay)
            self._bfs_cache[src] = hit
        return hit

    def _new_node(self, v: int, t: float, state: int, incarnation: int) -> Node:
        c = self.cfg
        return Node(
            id=v,
            alive=True,
            state=state,
            incarnation=incarnation,
            awake_since=t,
            bucket=TokenBucket(c.relay_capacity, c.relay_burst, t),
        )

    def set_state(self, v: int, new: int, t: float, source: str) -> None:
        node = self.nodes[v]
        old = node.state
        if old == new:
            return
        node.state = new
        node.state_changes += 1
        self.changes[source] += 1
        if old == GHOST:
            node.awake_since = t
            node.ghost_streak = 0
        if new == GHOST:
            node.ghost_streak = 0
        if (old == ACTIVE) != (new == ACTIVE):
            self.relay_version += 1
            self.active_changes[source] += 1
            d = 1 if new == ACTIVE else -1
            if (
                source in ROTATION_SOURCES
                and node.last_flip_src in ROTATION_SOURCES
                and node.last_flip_dir == -d
                and t - node.last_flip_t <= FLAP_CYCLES * self.cfg.vsepr_period + 1e-9
            ):
                self.flaps += 1
                if source.startswith("vsepr") or node.last_flip_src.startswith("vsepr"):
                    self.vsepr_flaps += 1
            node.last_flip_t = t
            node.last_flip_dir = d
            node.last_flip_src = source
            if d > 0:
                node.promoted_cycle = self.cycle
            else:
                node.demoted_cycle = self.cycle

    def repair(self, t: float, source: str) -> list[int]:
        """Captains restore the CDS invariant over the believed view.

        Like every captain job (VSEPR, resonance), it needs a captain that is truly alive.
        """
        if not self.captain_alive():
            self.skipped_repairs += 1
            return []
        alive = self.believed_alive()
        active = self.active_set()
        loads = [nd.total_load for nd in self.nodes]
        promoted, ok = repair_cds(self.adj, active, alive, loads)
        for v in promoted:
            self.set_state(v, ACTIVE, t, source)
        if promoted:
            self.cds_repairs += 1
        if not ok:
            self.cds_impossible += 1
        return promoted

    def elect(self, t: float, why: str) -> None:
        """Term k: the captain_count believed-alive non-GHOST nodes, smallest (id - k*c) mod n."""
        c = self.cfg.captain_count
        n = self.n
        k = self.term
        elig = [v for v in range(n) if self.believed[v] and self.nodes[v].state != GHOST]
        elig.sort(key=lambda v: ((v - k * c) % n, v))
        old = list(self.captains)
        self.captains = sorted(elig[:c])
        if why == "re-election":
            self.captain_reelections += 1
        if why != "init" and (self.captains != old or why == "elected"):
            self.log(
                t,
                ev.CAPTAIN_TERM,
                f"Captains {why} (term {k}): {_nodes(self.captains, 'none')}",
            )

    def captain_alive(self) -> bool:
        """One rule for every captain job: it needs a captain that is truly alive and awake.

        A dead captain cannot act, even while the stale view still lists it (FORMALISATION;
        the spec's "believed alive" would let a dead process run a cycle during the detection
        window), and a captain that VSEPR or fairness has put to sleep (GHOST) cannot act
        either (FORMALISATION: captains are elected awake but may be sent to sleep later).
        """
        nodes = self.nodes
        return any(nodes[c].alive and nodes[c].state != GHOST for c in self.captains)

    def track_split(self, t: float) -> None:
        """Accumulate the time the believed-alive nodes are split into several parts."""
        alive = self.believed_alive()
        split = len(components(self.adj, alive)) > 1 if alive else False
        if split and self.split_since is None:
            self.split_since = t
        elif not split and self.split_since is not None:
            self.split_s += t - self.split_since
            self.split_since = None

    def ensure_stems(self) -> None:
        want = self.cfg.stem_count
        self.stems = [s for s in self.stems if self.believed[s] and self.nodes[s].stem]
        while len(self.stems) < want:
            cand = sorted(
                (v for v in self.active_set() if not self.nodes[v].stem),
                key=lambda v: (self.nodes[v].total_load, v),
            )
            if not cand:
                break
            v = cand[0]
            self.nodes[v].stem = True
            self.stems.append(v)
        self.stems.sort()

    # ------------------------------------------------------------------ setup
    def _setup(self) -> None:
        c = self.cfg
        n = self.n
        self.nodes = [self._new_node(v, 0.0, GHOST, 0) for v in range(n)]
        try:
            stems = list(stem_triple(c.cage))
        except Exception:  # pragma: no cover
            stems = list(far_triple(self.adj))
        stems = stems[: c.stem_count]
        active = set(stems)
        for v in stems:
            self.nodes[v].stem = True
            self.nodes[v].state = ACTIVE
        self.stems = sorted(stems)
        promoted, _ = repair_cds(self.adj, active, range(n), [0.0] * n)
        active.update(promoted)
        target = int(round(c.active_fraction * n))
        for v in range(n):
            if len(active) >= target:
                break
            active.add(v)
        for v in active:
            self.nodes[v].state = ACTIVE
        rest = [v for v in range(n) if v not in active]
        n_standby = min(len(rest), int(round(c.standby_fraction * len(rest))))
        for v in self.setup_rng.sample(rest, n_standby):
            self.nodes[v].state = STANDBY
        if c.hotspot_node is not None:
            self.hotspot = int(c.hotspot_node) % n
        else:
            self.hotspot = self.hotspot_rng.randrange(n)
        self.relay_version += 1
        self.elect(0.0, "init")
        self.log(
            0.0,
            ev.CAPTAIN_TERM,
            f"Cell {c.cage} up: {len(active)} ACTIVE, {n_standby} STANDBY, "
            f"{n - len(active) - n_standby} GHOST; stems {_nodes(self.stems, 'none')}; "
            f"captains {_nodes(self.captains, 'none')}; hotspot node {self.hotspot}",
        )
        self.active_start = sum(1 for nd in self.nodes if nd.state == ACTIVE)
        # schedule: BIN events first so that a bin closes before same-time events
        for b in range(1, self.series.nb + 1):
            self.q.push(float(b), ev.BIN, b - 1)
        if c.kill_at is not None and 0 <= c.kill_at < c.duration:
            self.q.push(c.kill_at, ev.KILL, None)
        if c.resonance == "on":
            ph = c.resonance_phase if c.resonance_phase is not None else c.resonance_period / 2
            if ph < c.duration:
                self.q.push(ph, ev.RESONANCE, None)
        if c.vsepr_period < c.duration:
            self.q.push(c.vsepr_period, ev.VSEPR, None)
        ph = (
            c.checkpoint_phase
            if c.checkpoint_phase is not None
            else self.checkpoint_rng.uniform(0.0, c.checkpoint_period)
        )
        if ph < c.duration:
            self.q.push(ph, ev.CHECKPOINT, None)
        if c.captain_term < c.duration:
            self.q.push(c.captain_term, ev.CAPTAIN_TERM, None)
        if c.send_rate > 0:
            t0 = self.traffic_rng.expovariate(c.send_rate)
            if t0 < c.duration:
                self.q.push(t0, ev.SEND, None)
        if c.churn_rate > 0:
            t0 = self.churn_rng.expovariate(c.churn_rate)
            if t0 < c.duration:
                self.q.push(t0, ev.LEAVE, None)

    # ------------------------------------------------------------------ main loop
    def run(self) -> RunResult:
        if self._ran:
            raise RuntimeError("a Simulation runs once")
        self._ran = True
        handlers = {
            ev.SEND: self._on_send,
            ev.RETRY: self._on_retry,
            ev.DELIVER: self._on_deliver,
            ev.RESONANCE: self._on_resonance,
            ev.VSEPR: self._on_vsepr,
            ev.CHECKPOINT: self._on_checkpoint,
            ev.CAPTAIN_TERM: self._on_term,
            ev.KILL: self._on_kill,
            ev.LEAVE: self._on_leave,
            ev.DETECT: self._on_detect,
            ev.DEATH_EVENT: self._on_death,
            ev.MITOSIS_DONE: self._on_mitosis,
            ev.MEIOSIS_DONE: self._on_meiosis,
            ev.JOIN: self._on_join,
            ev.BIN: self._on_bin,
        }
        drain_kinds = (ev.RETRY, ev.DELIVER, ev.BIN)
        dur = self.cfg.duration
        q = self.q
        guard = 0
        while q:
            t, _, kind, payload = q.pop()
            if t >= dur and kind not in drain_kinds:
                continue
            guard += 1
            if guard > 50_000_000:  # pragma: no cover - defensive bound
                raise RuntimeError("event bound exceeded")
            self.now = t
            handlers[kind](t, payload)
        return self.result()

    # ------------------------------------------------------------------ traffic
    def _on_send(self, t: float, _payload) -> None:
        c = self.cfg
        rng = self.traffic_rng
        nxt = t + rng.expovariate(c.send_rate)
        if nxt < c.duration:
            self.q.push(nxt, ev.SEND, None)
        nodes = self.nodes
        alive = [v for v in range(self.n) if nodes[v].alive]
        if not alive:
            # Offered load with no live device to carry it. Not counted in ``sent`` (there
            # is no source), but counted as unserved in the recovery-time windows.
            self.skipped_sends += 1
            self.series.unserved[self.series.bin(t)] += 1
            self.series.fine_outage[self.series.fine(t)] += 1
            return
        src = rng.choice(alive)
        if rng.random() < c.hotspot_fraction and self.hotspot != src:
            dst = self.hotspot
        else:
            d = rng.randrange(self.n - 1)
            dst = d + 1 if d >= src else d
        key = (src, dst)
        seq = self.flows.get(key, 0)
        self.flows[key] = seq + 1
        mid = self._next_mid
        self._next_mid += 1
        b = self.series.bin(t)
        asleep = self.believed[dst] and nodes[dst].state == GHOST
        msg = Msg(mid, src, dst, seq, t, nodes[dst].alive, b, nodes[src].incarnation, asleep)
        self.msgs[mid] = msg
        self.sent += 1
        self.series.sent[b] += 1
        if asleep:
            self.addressed_asleep += 1
        self._attempt(msg, t)

    def _on_retry(self, t: float, mid: int) -> None:
        self._attempt(self.msgs[mid], t)

    def _mode(self) -> str:
        r = self.cfg.routing
        if r == ADAPTIVE_DUPLICATE:
            return DUPLICATE if self.util_prev > self.cfg.adaptive_threshold else CHILL
        if r == ADAPTIVE_STRIPE:
            return STRIPE if self.util_prev > self.cfg.adaptive_threshold else CHILL
        return r

    def _walk(self, path: list[int], cost: float, t: float, dst: int, b: int) -> str | None:
        nodes = self.nodes
        loss = self.cfg.link_loss
        last = len(path) - 1
        tx_bins = self.series.tx
        for i in range(1, last + 1):
            v = path[i]
            self.tx += cost
            tx_bins[b] += cost
            node = nodes[v]
            if not node.alive:
                return "dst_dead" if v == dst else "stale_view"
            if loss > 0 and self.loss_rng.random() < loss:
                return "link_loss"
            if i < last:
                self.bin_demand += cost
                if not node.bucket.take(t, cost):
                    return "congestion"
                node.window_load += cost
                node.total_load += cost
                node.bin_load += cost
        return None

    def _attempt(self, msg: Msg, t: float) -> None:
        c = self.cfg
        b = self.series.bin(t)
        dst = msg.dst
        src = msg.src
        sender = self.nodes[src]
        if not sender.alive or sender.incarnation != msg.src_inc:
            # The sending device died while its ARQ resend was pending: nothing is resent.
            self.fail_by_bin[(b, "src_dead")] += 1
            self._drop(msg, "src_dead", t)
            return
        msg.attempts += 1
        self.attempts += 1
        reason: str | None = None
        hops = 0
        dup = 0
        if not self.believed[dst]:
            reason = "dst_dead"  # the view already says the slot is vacant: nothing sent
        elif self.nodes[dst].state == GHOST:
            reason = "dst_asleep"
        else:
            relay = self._relay()
            rng = self.route_rng if c.path_rotation else None
            mode = self._mode()
            if mode == CHILL:
                dist, cnt = self._bfs(src)
                path = sample_path(self.adj, dist, cnt, src, dst, relay, rng)
                if path is None:
                    reason = "no_route"
                else:
                    reason = self._walk(path, 1.0, t, dst, b)
                    hops = len(path) - 1
            else:
                self.hell_attempts += 1
                paths = disjoint_paths(
                    self.adj, src, dst, relay, c.k_paths, rng, first=self._bfs(src)
                )
                self.hell_paths += len(paths)
                if len(paths) == 1:
                    self.hell_single += 1
                if not paths:
                    reason = "no_route"
                elif mode == DUPLICATE:
                    results = [self._walk(p, 1.0, t, dst, b) for p in paths]
                    ok = [len(p) - 1 for p, r in zip(paths, results, strict=True) if r is None]
                    if ok:
                        hops = min(ok)
                        dup = len(ok) - 1
                    else:
                        reason = results[0]
                else:  # STRIPE
                    cost = 1.0 / len(paths)
                    results = [self._walk(p, cost, t, dst, b) for p in paths]
                    failed = [r for r in results if r is not None]
                    if failed:
                        reason = failed[0]
                    else:
                        hops = max(len(p) - 1 for p in paths)
        if reason is None:
            self.duplicates += dup
            self.q.push(t + hops * c.hop_latency, ev.DELIVER, (msg.id, hops))
            return
        self.fail_by_bin[(b, reason)] += 1
        if msg.attempts <= c.max_retries:
            self.retries += 1
            self.q.push(t + c.retry_timeout, ev.RETRY, msg.id)
        else:
            self._drop(msg, reason, t)

    def _drop(self, msg: Msg, reason: str, t: float) -> None:
        """Final drop at time ``t`` (the last attempt): the outcome time for recovery bins."""
        del self.msgs[msg.id]
        self.drops[reason] += 1
        if msg.dst_alive and reason != "dst_asleep":
            self.series.dsent[msg.bin] += 1
            self.series.fine_ds[self.series.fine(t)] += 1

    def _on_deliver(self, t: float, payload) -> None:
        mid, hops = payload
        msg = self.msgs.pop(mid)
        self.delivered += 1
        if msg.to_asleep:
            self.to_asleep_delivered += 1
        s = self.series
        s.delivered[msg.bin] += 1
        s.hops[msg.bin] += hops
        self.hops_sum += hops
        lat = t - msg.t0
        self.lat_sum += lat
        self.latencies.append(lat)
        key = (msg.src, msg.dst)
        mx = self.flow_max.get(key, -1)
        if msg.seq < mx:
            self.out_of_order += 1
        else:
            self.flow_max[key] = msg.seq
        if msg.dst_alive:
            s.dsent[msg.bin] += 1
            s.ddel[msg.bin] += 1
            f = s.fine(t)  # outcome time: the arrival
            s.fine_ds[f] += 1
            s.fine_dd[f] += 1
            if s.fine_first[f] is None:
                s.fine_first[f] = t
        inc = self.incident
        if inc is not None and inc["first_delivery_t"] is None and msg.t0 >= inc["kill_t"]:
            inc["first_delivery_t"] = t

    # ------------------------------------------------------------------ rotation
    def _on_resonance(self, t: float, _payload) -> None:
        c = self.cfg
        nxt = t + c.resonance_period
        if nxt < c.duration:
            self.q.push(nxt, ev.RESONANCE, None)
        if not self.captain_alive():
            self.skipped_resonance += 1
            return
        nodes = self.nodes
        alive = set(self.believed_alive())
        active = self.active_set()
        hot = sorted(
            (v for v in active if not nodes[v].stem), key=lambda v: (-nodes[v].window_load, v)
        )
        cold = sorted(
            (v for v in alive if nodes[v].state == STANDBY),
            key=lambda v: (nodes[v].total_load, v),
        )
        swaps = []
        for h in hot:
            if len(swaps) >= c.resonance_swaps or not cold:
                break
            r = find_swap(self.adj, active, alive, h, cold)
            if r is None:
                continue
            self.set_state(h, STANDBY, t, "resonance")
            self.set_state(r, ACTIVE, t, "resonance")
            active.discard(h)
            active.add(r)
            cold.remove(r)
            swaps.append((h, r))
        self.resonance_swaps_done += len(swaps)
        if swaps:
            self.log(
                t,
                ev.RESONANCE,
                "Resonance swapped "
                + "; ".join(
                    f"node {h} (ACTIVE->STANDBY) with node {r} (STANDBY->ACTIVE)" for h, r in swaps
                ),
            )

    def _coldest(self, pool, k: int, exclude: set[int]) -> list[int]:
        nodes = self.nodes
        cand = sorted((v for v in pool if v not in exclude), key=lambda v: (nodes[v].total_load, v))
        return cand[:k]

    def _on_vsepr(self, t: float, _payload) -> None:
        c = self.cfg
        nxt = t + c.vsepr_period
        if nxt < c.duration:
            self.q.push(nxt, ev.VSEPR, None)
        self.cycle += 1
        nodes = self.nodes
        if not self.captain_alive():
            self.skipped_cycles += 1
            for nd in nodes:
                nd.window_load = 0.0
            return
        self.vsepr_cycles += 1
        alive = set(self.believed_alive())
        for v in alive:
            nd = nodes[v]
            nd.ghost_streak = nd.ghost_streak + 1 if nd.state == GHOST else 0
        active = self.active_set()
        loads = [nodes[v].window_load for v in active]
        avg = sum(loads) / len(loads) if loads else 0.0
        if avg > 0:
            # the load metrics are always over ACTIVE relays, whichever average VSEPR uses
            self.load_ratios.append(max(loads) / avg)
            self.cycle_peaks.append(max(loads))
            self.cycle_avgs.append(avg)
        if c.vsepr_average == "cell" and alive:
            # the journal's literal 'cell average': sleeping and STANDBY nodes count with the
            # little or no relayed load they carry
            avg = sum(nodes[v].window_load for v in alive) / len(alive)
        demoted: list[tuple[int, float]] = []
        promoted: list[int] = []
        if c.vsepr != "off" and avg > 0:
            cands = sorted(
                (
                    v
                    for v in active
                    if not nodes[v].stem and nodes[v].window_load > c.vsepr_factor * avg
                ),
                key=lambda v: (-nodes[v].window_load, v),
            )
            self.vsepr_candidates += len(cands)
            if c.vsepr == "naive":
                for v in cands:
                    self.set_state(v, GHOST, t, "vsepr")
                    demoted.append((v, nodes[v].window_load / avg))
                done = {v for v, _ in demoted}
                for _ in demoted:
                    for _k in range(c.vsepr_promote):
                        ghosts = [u for u in alive if nodes[u].state == GHOST]
                        pick = self._coldest(ghosts, 1, done)
                        if not pick:
                            standby = [u for u in alive if nodes[u].state == STANDBY]
                            pick = self._coldest(standby, 1, done)
                        if not pick:
                            break
                        self.set_state(pick[0], ACTIVE, t, "vsepr")
                        promoted.append(pick[0])
                        done.add(pick[0])
            else:  # damped (PROPOSED FIX)
                cd = c.vsepr_cooldown_cycles
                max_d = math.ceil(c.vsepr_max_demotions_frac * len(active))
                done: set[int] = set()
                for i, v in enumerate(cands):
                    if len(demoted) >= max_d:
                        self.vsepr_capped += len(cands) - i
                        break
                    if self.cycle - nodes[v].promoted_cycle <= cd:
                        self.vsepr_cooldown_skips += 1
                        continue  # hysteresis: recently promoted nodes are not demoted
                    ok_pool = [
                        u
                        for u in alive
                        if u not in done
                        and self.cycle - nodes[u].demoted_cycle > cd
                        and nodes[u].state != ACTIVE
                    ]
                    ghosts = sorted(
                        (u for u in ok_pool if nodes[u].state == GHOST),
                        key=lambda u: (nodes[u].total_load, u),
                    )
                    standby = sorted(
                        (u for u in ok_pool if nodes[u].state == STANDBY),
                        key=lambda u: (nodes[u].total_load, u),
                    )
                    r = find_swap(self.adj, active, alive, v, ghosts + standby)
                    if r is None:
                        # the demotion would break the CDS: skip it. Would any non-ACTIVE node
                        # (cooldown or not) have done? Counted to tell "no move exists" apart
                        # from "the cooldown blocked it".
                        self.vsepr_no_swap += 1
                        anyone = sorted(u for u in alive if nodes[u].state != ACTIVE)
                        if find_swap(self.adj, active, alive, v, anyone) is None:
                            self.vsepr_no_swap_any += 1
                        continue
                    ratio_v = nodes[v].window_load / avg
                    self.set_state(v, GHOST, t, "vsepr")
                    self.set_state(r, ACTIVE, t, "vsepr")
                    active.discard(v)
                    active.add(r)
                    done.update((v, r))
                    demoted.append((v, ratio_v))
                    promoted.append(r)
        self.demotions += len(demoted)
        self.promotions += len(promoted)
        # fairness (v1.7c): nobody stays GHOST for more than N cycles in a row. ghost_streak
        # counts the VSEPR periods a node has completed as GHOST; staying GHOST into the next
        # period would make it streak + 1, so a node is woken once streak reaches N.
        woken = sorted(
            v
            for v in alive
            if nodes[v].state == GHOST and nodes[v].ghost_streak >= c.fairness_max_ghost_cycles
        )
        slept: list[int] = []
        if woken:
            for v in woken:
                self.set_state(v, STANDBY, t, "fairness")
            wset = set(woken)
            pool = sorted(
                (v for v in alive if nodes[v].state == STANDBY and v not in wset),
                key=lambda v: (nodes[v].awake_since, v),
            )
            slept = pool[: len(woken)]
            for v in slept:
                self.set_state(v, GHOST, t, "fairness")
            self.fairness_wakes += len(woken)
        repaired = self.repair(t, "vsepr_repair")
        if demoted or promoted:
            txt = "VSEPR demoted " + ", ".join(f"node {v} (load {r:.1f}x avg)" for v, r in demoted)
            txt += f"; promoted {_nodes(promoted)}"
            if repaired:
                txt += f"; CDS repair promoted {_nodes(repaired)}"
            self.log(t, ev.VSEPR, txt)
        elif repaired:
            self.log(t, ev.VSEPR, f"VSEPR cycle: CDS repair promoted {_nodes(repaired)}")
        if woken:
            self.log(
                t,
                ev.VSEPR,
                f"Fairness woke {_nodes(woken)} to STANDBY; {_nodes(slept)} went GHOST",
            )
        for nd in nodes:
            nd.window_load = 0.0

    # ------------------------------------------------------------------ failures
    def _kill_nodes(self, t: float, victims: list[int]) -> list[tuple[int, int]]:
        out = []
        for v in victims:
            nd = self.nodes[v]
            if nd.alive:
                nd.alive = False
                out.append((v, nd.incarnation))
        return out

    def _on_kill(self, t: float, _payload) -> None:
        c = self.cfg
        m = int(round(c.kill_fraction * self.n))
        victims = sorted(self.kill_rng.sample(range(self.n), m))
        killed = self._kill_nodes(t, victims)
        rpo = (t - self.last_cp["t"]) if self.last_cp is not None else None
        self.incident = {
            "kill_t": t,
            "killed": len(killed),
            "rpo_s": rpo,
            "detect_t": None,
            "death_event": False,
            "path": "none",
            "recovered_t": None,
            "first_delivery_t": None,
            "refill_t": None,
        }
        self.log(
            t,
            ev.KILL,
            f"Killed {len(killed)} of {self.n} nodes ({100 * len(killed) / self.n:.0f}%), "
            f"incl. stems: {_nodes((s for s in self.stems if not self.nodes[s].alive), 'none')}"
            f"; captains: "
            f"{_nodes((x for x in self.captains if not self.nodes[x].alive), 'none')}; "
            f"the view stays stale until detection",
        )
        if killed:
            self.q.push(t + c.detect_delay, ev.DETECT, ("kill", killed))

    def _on_leave(self, t: float, _payload) -> None:
        c = self.cfg
        nxt = t + self.churn_rng.expovariate(c.churn_rate)
        if nxt < c.duration:
            self.q.push(nxt, ev.LEAVE, None)
        alive = [v for v in range(self.n) if self.nodes[v].alive]
        if not alive:
            return
        v = self.churn_rng.choice(alive)
        killed = self._kill_nodes(t, [v])
        self.leaves += 1
        self.log(t, ev.LEAVE, f"Node {v} left (churn)")
        self.q.push(t + c.detect_delay, ev.DETECT, ("leave", killed))

    def _on_detect(self, t: float, payload) -> None:
        c = self.cfg
        why, items = payload
        nodes = self.nodes
        gone = []
        vacancies = []
        for v, inc in items:
            nd = nodes[v]
            if nd.incarnation == inc and not nd.alive and self.believed[v]:
                self.believed[v] = False
                gone.append(v)
                self.vacancy_gen[v] += 1
                vacancies.append((v, self.vacancy_gen[v]))
        if not gone:
            return
        # Slots that went vacant together are refilled together, by one JOIN batch.
        self.q.push(t + c.rejoin_delay, ev.JOIN, tuple(vacancies))
        self.relay_version += 1
        self.track_split(t)
        if why == "kill" and self.incident is not None and self.incident["detect_t"] is None:
            self.incident["detect_t"] = t
        gset = set(gone)
        lost_captains = [x for x in self.captains if x in gset]
        lost_stems = [s for s in self.stems if s in gset]
        for v in gone:
            nodes[v].stem = False
        if lost_captains:
            self.elect(t, "re-election")
        self.ensure_stems()
        repaired = self.repair(t, "recovery")
        txt = f"Detected {len(gone)} dead after {c.detect_delay:g} s; removed from the view"
        if lost_stems:
            txt += f"; stems now {_nodes(self.stems, 'none')}"
        if repaired:
            txt += f"; CDS repair promoted {_nodes(repaired)}"
        if why == "kill" or lost_captains or len(gone) > 1:
            self.log(t, ev.DETECT, txt)
        dead = self.n - sum(self.believed)
        if dead > c.death_threshold * self.n and not self.death_active:
            self.death_active = True
            self.q.push(t, ev.DEATH_EVENT, dead)
        elif why == "kill" and dead <= c.death_threshold * self.n:
            self.log(
                t,
                ev.DETECT,
                f"No CELL_DEATH_EVENT: {dead} of {self.n} unreachable is not MORE than "
                f"{c.death_threshold:g} of the cell",
            )

    def _on_death(self, t: float, dead: int) -> None:
        c = self.cfg
        self.death_events += 1
        alive_view = sum(self.believed)
        if self.incident is not None and self.incident["recovered_t"] is None:
            self.incident["death_event"] = True
        if alive_view > 0:
            self.q.push(t + c.mitosis_time, ev.MITOSIS_DONE, None)
            path = "mitosis"
        else:
            self.q.push(t + c.meiosis_time, ev.MEIOSIS_DONE, None)
            path = "meiosis"
        if self.incident is not None and self.incident["recovered_t"] is None:
            self.incident["path"] = path
        self.log(
            t,
            ev.DEATH_EVENT,
            f"CELL_DEATH_EVENT: {dead} of {self.n} unreachable; {path} started "
            f"({alive_view} survivors)",
        )

    def _on_mitosis(self, t: float, _payload) -> None:
        filled = []
        for v in range(self.n):
            if not self.believed[v] and not self.nodes[v].alive:
                self.nodes[v] = self._new_node(v, t, STANDBY, self.nodes[v].incarnation + 1)
                self.believed[v] = True
                filled.append(v)
        self.relay_version += 1
        self.track_split(t)
        self._after_refill(t)
        repaired = self.repair(t, "recovery")
        self.death_active = False
        if self.incident is not None and self.incident["recovered_t"] is None:
            self.incident["recovered_t"] = t
        self.log(
            t,
            ev.MITOSIS_DONE,
            f"Mitosis done: {len(filled)} fresh STANDBY nodes joined the survivors; "
            f"{_count(len(repaired))} promoted by CDS repair",
        )

    def _on_meiosis(self, t: float, _payload) -> None:
        cp = self.last_cp
        for v in range(self.n):
            st = STANDBY
            if cp is not None and cp["states"][v] is not None:
                st = cp["states"][v]
            self.nodes[v] = self._new_node(v, t, st, self.nodes[v].incarnation + 1)
            self.believed[v] = True
        self.stems = []
        if cp is not None:
            for s in cp["stems"]:
                self.nodes[s].stem = True
                self.nodes[s].state = ACTIVE
                self.stems.append(s)
        self.relay_version += 1
        self.track_split(t)
        self._after_refill(t)
        repaired = self.repair(t, "recovery")
        self.death_active = False
        if self.incident is not None and self.incident["recovered_t"] is None:
            self.incident["recovered_t"] = t
        src = f"checkpoint of t={cp['t']:.1f}" if cp is not None else "no checkpoint (fresh cell)"
        self.log(
            t,
            ev.MEIOSIS_DONE,
            f"Meiosis done: gateway respawned all {self.n} slots from the {src}; "
            f"{_count(len(repaired))} promoted by CDS repair",
        )

    def _after_refill(self, t: float) -> None:
        if len(self.captains) < self.cfg.captain_count or not self.captain_alive():
            self.elect(t, "re-election")
        self.ensure_stems()
        inc = self.incident
        if inc is not None and inc["refill_t"] is None and all(nd.alive for nd in self.nodes):
            inc["refill_t"] = t

    def _on_join(self, t: float, payload) -> None:
        filled = []
        for v, gen in payload:
            if self.vacancy_gen[v] != gen or self.believed[v] or self.nodes[v].alive:
                continue  # refilled already (mitosis/meiosis) or vacated again since
            self.nodes[v] = self._new_node(v, t, STANDBY, self.nodes[v].incarnation + 1)
            self.believed[v] = True
            filled.append(v)
        if not filled:
            return
        self.joins += len(filled)
        self.relay_version += 1
        self.track_split(t)
        self._after_refill(t)
        repaired = self.repair(t, "recovery")
        if len(filled) > 1:
            self.log(
                t,
                ev.JOIN,
                f"Rejoin after {self.cfg.rejoin_delay:g} s: {len(filled)} fresh STANDBY nodes "
                f"filled vacant slots; {_count(len(repaired))} promoted by CDS repair",
            )

    def _on_checkpoint(self, t: float, _payload) -> None:
        c = self.cfg
        nxt = t + c.checkpoint_period
        if nxt < c.duration:
            self.q.push(nxt, ev.CHECKPOINT, None)
        if not any(nd.alive for nd in self.nodes):
            return
        self.last_cp = {
            "t": t,
            "states": tuple(
                self.nodes[v].state if self.believed[v] else None for v in range(self.n)
            ),
            "stems": tuple(self.stems),
        }
        self.checkpoints += 1

    def _on_term(self, t: float, _payload) -> None:
        c = self.cfg
        nxt = t + c.captain_term
        if nxt < c.duration:
            self.q.push(nxt, ev.CAPTAIN_TERM, None)
        self.term += 1
        self.captain_terms += 1
        self.elect(t, "elected")

    # ------------------------------------------------------------------ bins
    def _on_bin(self, t: float, b: int) -> None:
        c = self.cfg
        s = self.series
        nodes = self.nodes
        na = ns = ng = nd_ = 0
        for nd in nodes:
            if not nd.alive:
                nd_ += 1
            elif nd.state == ACTIVE:
                na += 1
            elif nd.state == STANDBY:
                ns += 1
            else:
                ng += 1
        s.active[b], s.standby[b], s.ghost[b], s.dead[b] = na, ns, ng, nd_
        relay = self._relay()
        n_relay = sum(relay)
        if n_relay:
            self.util_prev = self.bin_demand / (c.relay_capacity * n_relay)
        else:
            self.util_prev = math.inf if self.bin_demand > 0 else 0.0
        self.bin_demand = 0.0
        act_loads = [nodes[v].bin_load for v in range(self.n) if relay[v]]
        mean = sum(act_loads) / len(act_loads) if act_loads else 0.0
        mx = max(nd.bin_load for nd in nodes)
        s.max_load_ratio[b] = mx / mean if mean > 0 else 0.0
        if self.frames is not None:
            self.frames["states"].append(
                "".join(STATE_CHARS[nd.state] if nd.alive else DEAD_CHAR for nd in nodes)
            )
            cap = c.relay_capacity
            self.frames["loads"].append(
                "".join(str(min(9, int(10 * nd.bin_load / cap))) for nd in nodes)
            )
            self.frames["stems"].append(list(self.stems))
            self.frames["captains"].append(list(self.captains))
        for nd in nodes:
            nd.bin_load = 0.0

    # ------------------------------------------------------------------ result
    def result(self) -> RunResult:
        c = self.cfg
        s = self.series
        n = self.n
        minutes = c.duration / 60.0
        d_sent = sum(s.dsent)
        d_del = sum(s.ddel)
        alive_bins = [n - x for x in s.dead]
        ghost_share = [(g / a) if a else 0.0 for g, a in zip(s.ghost, alive_bins, strict=True)]
        rot_active = sum(
            self.active_changes[k] for k in ("vsepr", "vsepr_repair", "fairness", "resonance")
        )
        rot_all = sum(self.changes[k] for k in ("vsepr", "vsepr_repair", "fairness", "resonance"))
        summary = {
            "cage": c.cage,
            "n": n,
            "duration": c.duration,
            "seed": c.seed,
            "routing": c.routing,
            "vsepr": c.vsepr,
            "vsepr_average": c.vsepr_average,
            "hotspot_node": self.hotspot,
            "sent": self.sent,
            "delivered": self.delivered,
            "delivery_ratio": per(self.delivered, self.sent),
            "deliverable_sent": d_sent,
            "deliverable_delivered": d_del,
            "deliverable_ratio": per(d_del, d_sent),
        }
        for r in DROP_REASONS:
            summary[f"drops_{r}"] = self.drops.get(r, 0)
        summary.update(
            {
                "drops_total": sum(self.drops.values()),
                "attempts": self.attempts,
                "retries": self.retries,
                "hell_attempts": self.hell_attempts,
                "mean_paths": per(self.hell_paths, self.hell_attempts),
                "single_path_share": per(self.hell_single, self.hell_attempts),
                "transmissions": self.tx,
                "tx_per_delivered": per(self.tx, self.delivered),
                "duplicates": self.duplicates,
                "duplicates_per_delivered": per(self.duplicates, self.delivered),
                "out_of_order": self.out_of_order,
                "out_of_order_per_delivered": per(self.out_of_order, self.delivered),
                "mean_hops": per(self.hops_sum, self.delivered),
                "mean_latency_ms": 1000 * per(self.lat_sum, self.delivered),
                "p95_latency_ms": (
                    1000 * percentile(self.latencies, 0.95) if self.latencies else None
                ),
                "share_to_asleep": per(self.addressed_asleep, self.sent),
                "addressed_asleep": self.addressed_asleep,
                # of those, the share a resend still delivered (the device woke in time)
                "to_asleep_delivered_share": per(self.to_asleep_delivered, self.addressed_asleep),
                "skipped_sends": self.skipped_sends,
                "vsepr_cycles": self.vsepr_cycles,
                "skipped_cycles": self.skipped_cycles,
                "skipped_resonance": self.skipped_resonance,
                "demotions": self.demotions,
                "promotions": self.promotions,
                "vsepr_repair_promotions": self.active_changes["vsepr_repair"],
                "vsepr_candidates": self.vsepr_candidates,
                "vsepr_cooldown_skips": self.vsepr_cooldown_skips,
                "vsepr_capped": self.vsepr_capped,
                "vsepr_no_swap": self.vsepr_no_swap,
                "vsepr_no_swap_any": self.vsepr_no_swap_any,
                "flaps": self.flaps,
                "vsepr_flaps": self.vsepr_flaps,
                "state_changes_per_min": rot_active / minutes,
                "state_changes_per_min_vsepr": (
                    self.active_changes["vsepr"] + self.active_changes["vsepr_repair"]
                )
                / minutes,
                "state_changes_per_min_vsepr_repair": self.active_changes["vsepr_repair"] / minutes,
                "state_changes_per_min_resonance": self.active_changes["resonance"] / minutes,
                "fairness_moves_per_min": self.changes["fairness"] / minutes,
                "all_state_changes_per_min": rot_all / minutes,
                "recovery_state_changes": self.changes["recovery"],
                "resonance_swaps": self.resonance_swaps_done,
                "fairness_wakes": self.fairness_wakes,
                "active_fraction_start": self.active_start / n,
                "active_fraction_end": s.active[-1] / n,
                "active_fraction_mean": sum(s.active) / (len(s.active) * n),
                "ghost_time_share": sum(ghost_share) / len(ghost_share),
                "mean_max_avg_load_ratio": (
                    sum(self.load_ratios) / len(self.load_ratios) if self.load_ratios else None
                ),
                # absolute loads (msg-equivalents relayed per s, per VSEPR cycle): the ratio's
                # numerator and denominator, so a changed ACTIVE set cannot hide behind it
                "mean_peak_relay_load": (
                    sum(self.cycle_peaks) / (len(self.cycle_peaks) * c.vsepr_period)
                    if self.cycle_peaks
                    else None
                ),
                "mean_avg_relay_load": (
                    sum(self.cycle_avgs) / (len(self.cycle_avgs) * c.vsepr_period)
                    if self.cycle_avgs
                    else None
                ),
                "captain_terms": self.captain_terms,
                "captain_reelections": self.captain_reelections,
                "checkpoints": self.checkpoints,
                "cds_repairs": self.cds_repairs,
                "cds_impossible": self.cds_impossible,
                "view_split_s": self.split_s
                + (c.duration - self.split_since if self.split_since is not None else 0.0),
                "cds_valid_end": is_cds(self.adj, self.active_set(), self.believed_alive()),
                "death_events": self.death_events,
                "leaves": self.leaves,
                "joins": self.joins,
            }
        )
        rec = {
            "kill_at": None,
            "killed": 0,
            "death_event": False,
            "path": "none",
            "detect_time_s": None,
            "detect_time": None,  # the spec's name for detect_time_s (same value)
            "rto_service_s": None,
            "rto_journal_formula_s": None,
            "rpo_s": None,
            "first_delivery_after_kill_s": None,
            "refill_after_kill_s": None,
            "baseline_ratio": None,
            "min_ratio_after_kill": None,
            "ratio_dip": None,
        }
        inc = self.incident
        if inc is not None:
            kt = inc["kill_t"]
            rm = recovery_metrics(s.offered(), s.fine_dd, kt, c.duration, first_served=s.fine_first)
            extra_t = {"mitosis": c.mitosis_time, "meiosis": c.meiosis_time}.get(inc["path"], 0.0)
            det = (inc["detect_t"] - kt) if inc["detect_t"] is not None else None
            rec.update(
                {
                    "kill_at": kt,
                    "killed": inc["killed"],
                    "death_event": inc["death_event"],
                    "path": inc["path"],
                    "detect_time_s": det,
                    "detect_time": det,
                    "rto_journal_formula_s": c.detect_delay + extra_t,
                    "rpo_s": inc["rpo_s"],
                    "first_delivery_after_kill_s": (
                        inc["first_delivery_t"] - kt
                        if inc["first_delivery_t"] is not None
                        else None
                    ),
                    "refill_after_kill_s": (
                        inc["refill_t"] - kt if inc["refill_t"] is not None else None
                    ),
                    **rm,
                }
            )
        summary.update(rec)
        res = RunResult(
            summary=summary,
            series=s.as_dict(),
            events=self.events,
            frames=self.frames,
            extra={
                "fail_by_bin": dict(self.fail_by_bin),
                "incident": inc,
                "outcome_seconds": s.outcome_seconds(),
            },
        )
        return res


def run(cfg: Config | None = None, **overrides) -> RunResult:
    """Run one simulation. ``run(seed=3, vsepr="damped")`` overrides Config defaults."""
    if cfg is None:
        cfg = Config(**overrides)
    elif overrides:
        d = cfg.to_dict()
        d.update(overrides)
        cfg = Config(**d)
    return Simulation(cfg).run()
