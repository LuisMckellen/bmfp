# BMFP cell: the protocol as implemented

The design review in the journal (Part VII) says: *"It is a vision, not a spec. No state
machine, no message formats beyond one line, no failure semantics, no threat model. A second
engineer could not implement this from the document."* This file is the missing spec for the
parts the simulator implements: one cell, its node states, its rotation rules and its failure
semantics. Everything here is what `bmfp/sim.py` does; the tests in `tests/test_sim_rules.py`
check each rule.

Every rule is tagged with where it comes from:

| Tag | Meaning |
|---|---|
| **v1.x** | Taken from that journal version. Numbers tagged this way are *inputs from the journal*, never results. |
| **FORMALISATION** | The journal said something ambiguous; this is the precise reading chosen here. |
| **ASSUMPTION** | Not in the journal at all; a simulator choice. Every one is a `Config` field you can change. |
| **PROPOSED FIX** | Not the journal's rule: a change suggested by the review, simulated for comparison. |

Out of scope (not simulated): encryption and receipts (v1.1), groups, sharding, multicast and
gateways between shards (v1.5), group tokens (v1.6), hibernation and cell resizing (v1.7),
graphite mode (v1.7), flash wake (v1.7a), message formats, a threat model, real gossip, and
real wall-clock networking.

---

## 1. Topology (v1.0, v1.7 Figure 3)

* A cell is a 3-regular cage built from 3D vertex coordinates: C12 truncated tetrahedron,
  C20 dodecahedron, C24 truncated octahedron, C60 truncated icosahedron. Edges are the vertex
  pairs at the minimum pairwise distance. Node ids come from sorting the rounded coordinates.
  (C12 and C24 are not in the journal; they are the other small cubic cages, added as
  ASSUMPTION for comparison. Figure 6 draws its "twelve-node cell" as a ring, not as C12;
  E1 analyses that ring separately.)
* The number in a cage's name counts **nodes** (FORMALISATION of the Part VII question
  "what does the number in C20 count").
* Each slot holds at most one device. A slot whose device died is *vacant* once the death is
  detected, until a fresh device fills it.

## 2. Node state (v1.7, v1.7c)

| From | To | Caused by |
|---|---|---|
| ACTIVE | GHOST | VSEPR demotion (section 7) |
| ACTIVE | STANDBY | resonance swap (section 6) |
| STANDBY | ACTIVE | resonance swap, CDS repair, VSEPR promotion when no GHOST is left |
| GHOST | ACTIVE | VSEPR promotion, CDS repair |
| GHOST | STANDBY | fairness wake (section 7) |
| STANDBY | GHOST | fairness sleep (section 7) |
| any | dead | `KILL` or `LEAVE` (section 9) |
| vacant | STANDBY | mitosis, `JOIN`; meiosis restores the checkpointed state |

* `STATE_FLAG` byte (v1.7c): `GHOST = 0`, `ACTIVE = 1`, `STANDBY = 2`.
* **ACTIVE** relays other nodes' traffic, sends and receives. **STANDBY** is awake: it sends
  and receives but does not relay. **GHOST** is asleep: it cannot relay or receive, but it can
  originate a send (FORMALISATION: v1.7 says GHOST "carries nothing").
* Liveness is separate from state: `alive` is the truth; the cell's **believed view** is
  what the captains know. A node that dies stays in the believed view, with its last state,
  until its death is detected (v1.7a: the state map is "eventually consistent and a sender may
  briefly route against a stale view").
* **Stem nodes** (v1.7e): 3 permanent ACTIVE nodes, exempt from resonance and VSEPR. At start
  they are the 3 nodes with the largest pairwise hop distance (ASSUMPTION). A dead stem is
  replaced, on detection, by the ACTIVE node with the lowest total relayed load (FORMALISATION).

### Valid ACTIVE set = connected dominating set (FORMALISATION of v1.7b)

v1.7b says the cell "moves continuously between valid ACTIVE sets" and Figure 6 shows three of
them. Since only ACTIVE nodes relay, a valid set must let every node reach every other through
relays. That is exactly a **connected dominating set (CDS)** over the believed-alive nodes:

1. every believed-alive node is ACTIVE or adjacent to an ACTIVE node, and
2. the ACTIVE nodes induce a connected subgraph.

A CDS is the standard "virtual backbone" of ad-hoc and sensor networking (Das & Bharghavan,
1997; Wu & Li, 1999). **Invariant:** after every state-changing step, captains run
`repair_cds` over the believed view. Repair promotes greedily and deterministically: the
candidate adjacent to the backbone that joins the most backbone pieces, then dominates the
most undominated nodes; ties go to the lowest total load, then the lowest id. If the
believed-alive nodes are themselves split, no single backbone exists: repair reports
"impossible" and gives each part its own backbone.

A consequence the journal could not see: in any 3-regular graph a CDS of size k has at most
k + 2 edges leaving it, so it can dominate at most k + 2 other nodes, hence
**k >= (n - 2) / 2**. A C60 cell needs at least 29 ACTIVE nodes; a 12-node cubic cell needs
at least 5 (E1 gives the exact minima). On the 12-node ring Figure 6 actually draws, its
"4 active, 8 resting" sets (every third node) dominate the ring but are not connected, and a
CDS needs 10 nodes: either way the figure's sets cannot be a relay backbone. `active_fraction
= 0.35` is below the floor, so the initial ACTIVE share is set by the greedy CDS construction
(see E1/E2 in the README), not by the setting; E1 also reports smaller CDSs a search finds.

## 3. Initial cell (ASSUMPTION)

1. Stems = the far triple; ACTIVE = stems.
2. `repair_cds` to a CDS.
3. Add lowest-id non-ACTIVE nodes until ACTIVE >= round(`active_fraction` x n).
4. STANDBY = round(`standby_fraction` x r) nodes drawn by the seed from the r nodes that
   are not ACTIVE ("standby_fraction of the remainder"). The rest are GHOST. In C60 with the
   defaults: 32 ACTIVE, 8 STANDBY, 20 GHOST.
5. Captains elected for term 0. The hotspot node (the popular destination) is drawn by the
   seed from its own random stream, so changing `standby_fraction` or `active_fraction`
   does not change it (section 11).

## 4. Events and time

Continuous time. A heap of `(time, seq, kind, payload)`; `seq` is an insertion counter so
ties pop in insertion order. All 1 s `BIN` events are pushed first, so a bin always closes
before other events at the same instant. Event kinds:

| Kind | When | Effect |
|---|---|---|
| `SEND` | Poisson, `send_rate` per cell | new message, first attempt |
| `RETRY` | attempt failed, + `retry_timeout` | next attempt |
| `DELIVER` | attempt time + hops x `hop_latency` | record latency, hops, order |
| `RESONANCE` | every `resonance_period` from `resonance_period/2` | swaps (section 6) |
| `VSEPR` | every `vsepr_period` | VSEPR + fairness + repair (section 7) |
| `CHECKPOINT` | every `checkpoint_period` from a seeded phase | snapshot (section 9) |
| `CAPTAIN_TERM` | every `captain_term` | next term's election |
| `KILL` | `kill_at` | scripted failure |
| `LEAVE` | Poisson, `churn_rate` | one random live node dies |
| `DETECT` | failure + `detect_delay` | view update, repairs |
| `DEATH_EVENT` | at detection, if the rule fires | starts mitosis or meiosis |
| `MITOSIS_DONE` / `MEIOSIS_DONE` | + `mitosis_time` / `meiosis_time` | refill |
| `JOIN` | detection + `rejoin_delay` | fresh STANDBY nodes in the slots that went vacant together (one batch, one repair) |
| `BIN` | every 1 s | metrics, frames, utilisation |

Sends stop at `duration`; after that only `RETRY`, `DELIVER` and the final `BIN` run, until
the queue is empty, so every message ends delivered or dropped (**sent = delivered + drops**).

## 5. Traffic and routing

**Workload (ASSUMPTION; Part IX asks for "a fixed send rate").** The source is uniform over
truly-alive nodes. With probability `hotspot_fraction` the destination is the hotspot (if it
is the source, fall back), otherwise uniform over all other slots. A dead slot is a real
destination: the user's device is gone. Each (source, destination) flow carries sequence
numbers (v1.2). If no node is alive, the offered send is not counted as sent (there is no
sender) but it is counted as unserved by the recovery metric (section 10).

**Attempt.** The sender uses the believed view and the state map.

0. Sender dead: an ARQ resend whose sending device has died (or whose slot now holds a fresh
   device) is dropped as `src_dead` with no transmission; a dead device cannot resend
   (FORMALISATION). The message still counts as deliverable and undelivered.
1. Destination believed vacant: drop `dst_dead`, no transmissions (FORMALISATION).
2. Destination believed GHOST: drop `dst_asleep`, no transmissions. Nothing stores and
   forwards (journal open problem "Offline delivery").
3. Relay set R = believed-alive ACTIVE nodes. A path may start and end at any node; every
   interior node must be in R. No path: drop `no_route`.
4. Walk each hop u -> v (one transmission of cost c each): v truly dead -> `dst_dead` if v is
   the destination, else `stale_view`; then with probability `link_loss` -> `link_loss`; an
   interior v without c tokens -> `congestion`; otherwise v spends c tokens and its
   `window_load`, `total_load` and per-second load grow by c.
5. A failed attempt is retried after `retry_timeout` while attempts <= `max_retries` (v1.3
   "automatic resend"; ARQ). Acks are assumed reliable and free, so ARQ creates no duplicates.
   The final drop reason is the last attempt's reason.

**Approximation:** a walk is evaluated at the attempt instant (tokens are spent then);
only the arrival is delayed by hops x `hop_latency`. `hop_latency` = 5 ms is an ASSUMPTION
derived from v1.7a's "edge cluster under 5 ms RTT", which bounds a whole round trip, not one
hop.

**Modes** (v1.2 "chill and hell"; the two hell readings are the Part VII ambiguity):

| Mode | Rule |
|---|---|
| `chill` | one shortest path over R. With `path_rotation` (v1.4) it is drawn uniformly among all shortest paths (predecessors sampled in proportion to their path counts); without it, lowest-id predecessors. |
| `duplicate` | hell, reading 1. Greedy node-disjoint paths: take a shortest path, remove its interior nodes (and the direct edge if used), repeat, up to `k_paths` = 3 ("3 exits per node", v1.0). A full copy (cost 1) on each. Delivered if any copy arrives; the first arrival delivers, later successful copies count as duplicates. If none arrives the reason is the first path's. |
| `stripe` | hell, reading 2. The same m paths; m fragments of cost 1/m. Delivered only if all m arrive; latency is the longest fragment's. |
| `adaptive_*` | chill while relay utilisation in the previous 1 s bin, demand / (`relay_capacity` x \|R\|), is <= `adaptive_threshold`, else the hell reading. The 0.9 default is an ASSUMPTION borrowed from v1.7a's flash-wake trigger ("load cross 90 percent of the cell's capacity", which grows the cell); the journal gives hell mode no trigger. No experiment uses these modes. |

**Rate limiting** (v1.3; token bucket from Part VIII): each relay has a bucket refilling at
`relay_capacity` tokens/s up to `relay_burst` (both ASSUMPTION).

## 6. Resonance (v1.7b; period and swap count ASSUMPTION)

Every `resonance_period` (journal: "continuously"; first round at half a period so it never
coincides with a VSEPR tick, FORMALISATION), if a captain is alive: up to `resonance_swaps`
swaps of a non-stem ACTIVE node (hottest `window_load` first) with a STANDBY node (lowest
`total_load` first). A swap is accepted only if the result is still a CDS. The swapped-out
node becomes STANDBY.

## 7. VSEPR and fairness (v1.7d, v1.7c)

Every `vsepr_period` = 30 s (v1.7d), if a captain is alive (else the cycle is skipped and
counted; see section 8 for the captain-job rule):

1. Ghost streaks: +1 for believed-alive GHOST nodes, 0 for the rest. A node's streak is the
   number of VSEPR periods it has completed as GHOST (it restarts at 0 when it enters GHOST).
2. avg = the journal's "cell average" (FORMALISATION, `vsepr_average`): by default
   (`active`) the mean `window_load` over believed-alive ACTIVE nodes, the ones that carry
   relay load; `cell` takes the mean over every believed-alive node, sleeping and STANDBY
   ones included (the literal wording; a lower threshold). Candidates = non-stem ACTIVE
   nodes with `window_load` > `vsepr_factor` x avg (2x, v1.7d), avg > 0, hottest first. The
   load metrics (`mean_max_avg_load_ratio` and friends) always use the ACTIVE mean.
3. Variant:
   * **naive** (the journal rule, with the average above): every candidate goes GHOST; for
     each demotion the `vsepr_promote` = 2 coldest GHOST nodes (lowest total load, then id)
     become ACTIVE, or the coldest STANDBY if no GHOST is left. No hysteresis, no cooldown,
     and no check that the demotion keeps a CDS (the repair in step 5 restores it).
   * **damped** (PROPOSED FIX, from the review's "add hysteresis and a cooldown"): skip
     candidates promoted within the last `vsepr_cooldown_cycles` cycles; at most
     ceil(`vsepr_max_demotions_frac` x \|ACTIVE\|) demotions per cycle; exactly one
     replacement per demotion (coldest GHOST, then STANDBY) that was not demoted within the
     cooldown; a demotion happens only if the swap keeps a CDS. The ACTIVE count is constant.
     Every candidate it does not demote is counted by reason: the cooldown
     (`vsepr_cooldown_skips`), the per-cycle cap (`vsepr_capped`), or no allowed swap that
     keeps a CDS (`vsepr_no_swap`; `vsepr_no_swap_any` when no non-ACTIVE node at all would
     do).
   * **off**: no demotions; fairness and repair still run.
4. Fairness (v1.7c, "no node may stay GHOST for more than two cycles in a row"): a GHOST
   node whose streak has reached `fairness_max_ghost_cycles` (2) wakes to STANDBY, since
   staying would make a third period in a row (FORMALISATION of the spec's "streak > max",
   counting the period about to start). The same number of longest-awake STANDBY nodes go to
   GHOST, so counts are kept; if fewer STANDBY nodes exist, all overdue GHOSTs still wake
   (the journal rule wins) and the GHOST pool shrinks to the STANDBY supply. A node demoted
   at cycle c is woken at cycle c + 2; while captains live, no node stays GHOST longer than
   `fairness_max_ghost_cycles` x `vsepr_period`. Waking to STANDBY rather than ACTIVE is a
   FORMALISATION: the woken node is awake but does not relay, so the rule limits sleep; it
   does not make a free rider carry load, which is the purpose v1.7c gives it.
5. `repair_cds` (its promotions are counted under VSEPR).
6. Every `window_load` resets.

## 8. Captains (v1.7c; election rule FORMALISATION)

The journal says three captains, five-minute terms, chosen from the SWIM membership view, and
that "the election rule is currently unwritten". Rule used here: in term k the captains are
the `captain_count` believed-alive non-GHOST nodes with the smallest `(id - k x
captain_count) mod n` (ties by id). This is "lowest id in the view", rotated each term so
the job moves around the cell. Terms start every `captain_term` = 300 s. When a captain's
death is detected the rule is re-run at once (same term). After mitosis, meiosis or a join,
the rule is re-run if fewer than `captain_count` captains are elected (the view had too few
eligible nodes at the last election) or if none of them is truly alive. The view is global:
**split-brain is not modelled**.

**Captain jobs need a live, awake captain** (FORMALISATION, one rule for every job: VSEPR,
resonance and CDS repair). The spec says a cycle is skipped when no captain is *believed*
alive; here a job is skipped when no captain is *truly* alive and awake, because a dead
process cannot act even while the stale view still lists it, and captains are elected among
awake nodes but VSEPR or fairness may later put one to sleep (GHOST); a sleeping captain
does not act. In E3 the kill at t = 120 s falls on a VSEPR
tick; the KILL event was queued first, so in kill100 (and whenever all three captains die)
that tick finds no live captain and is skipped.

## 9. Failure and recovery (v1.7e)

* `KILL` (round(`kill_fraction` x n) slots chosen by the seed, may include stems and
  captains) and `LEAVE` (churn) set `alive = False` at once. The view does not change until
  `DETECT` at + `detect_delay` (3 s, input). Between the two, routes through the dead nodes
  fail with `stale_view`.
* On `DETECT`: remove the dead from the view (their slots become vacant and schedule one
  `JOIN` batch at + `rejoin_delay`), re-elect captains if one died, replace dead stems,
  repair the CDS.
* **CELL_DEATH_EVENT** when believed-dead slots are **more than** `death_threshold` x n
  (v1.7e "more than half the nodes unreachable"); it fires once per incident. Killing exactly
  half does **not** fire it (literal semantics; reported as a finding).
* Then, if any node is believed alive: **mitosis**, done after `mitosis_time` (1.5 s, input):
  every vacant slot gets a fresh STANDBY node; repair. If none: **meiosis**, done after
  `meiosis_time` (1.5 s, input): the gateway respawns every slot from the last checkpoint
  (states and stems restored), then repair.
* Churn and partial kills without a death event: vacant slots are refilled by a fresh
  STANDBY node after `rejoin_delay` (20 s, ASSUMPTION), unless mitosis or meiosis got there
  first.
* `CHECKPOINT` every `checkpoint_period` (10 s, v1.7e) while any node is alive: a snapshot of
  the believed state map and the stems, stored at the gateway and two neighbour cells, which
  are external and never fail (ASSUMPTION). The first checkpoint time is drawn by the seed in
  [0, 10 s) (ASSUMPTION), so a kill at t = 120 s does not always land on a checkpoint tick.

## 10. Metrics

* **Deliverable** message: its destination was truly alive when it was sent and its final
  drop reason, if it is dropped, is not `dst_asleep` (sleep is judged at the last attempt).
  The deliverable ratio is the health metric for routing and recovery; `share_to_asleep`
  (messages whose destination the view showed asleep when first sent, over `sent`)
  measures the offline-delivery problem separately, and `to_asleep_delivered_share` is the
  part of those a resend still delivered because the device woke in time.
* In the 1 s `series`, outcomes are attributed to the bin in which the message was sent.
  `unserved` counts, per second, the sends offered while no node was alive: they are not in
  `sent` (there is no sender) but nobody served them, so
  `deliverable_delivered / (deliverable_sent + unserved)` is the per-second ratio that
  agrees with the recovery metric during total death.
* **Recovery bins (0.1 s) use outcome time instead**: a delivered message counts at its
  arrival, a dropped one at its last attempt, and a send offered while no node is alive
  (no sender, so not in `sent`) counts as unserved at its offer time. An ARQ resend that
  succeeds after recovery therefore counts after recovery, not at the earlier send.
* `rto_service_s`: from the kill to the first delivered message at which the service is
  back: the first 0.1 s step T >= kill such that (1) the step itself delivered at least one
  message at a ratio >= 95% of the baseline, (2) the first second [T, T + 1 s) is >= 95%,
  and (3) each of 10 forward 5 s windows [T + j, T + j + 5 s), j = 0..9 s, is >= 95%
  (baseline = deliverable ratio over the 60 s before the kill; FORMALISATION of "the 5 s
  rolling ratio is back to 95% of baseline and stays there for 10 bins"). The value is the
  first arrival inside step T. Conditions 1 and 2 stop a window that starts inside an
  outage from passing on the 95% tolerance, so no instant without service qualifies: after
  total death it is never earlier than the first delivery. It can precede a rebuild only
  where ARQ resends carry the last pre-rebuild messages across it (they succeed after it,
  so no message is lost from T on). `first_delivery_after_kill_s` and `refill_after_kill_s`
  (every slot occupied again; inputs: detection + mitosis/meiosis or + `rejoin_delay`) are
  reported next to it.
* `rto_journal_formula_s` = `detect_delay` + (`mitosis_time` or `meiosis_time` or 0).
  `detect_time_s` (alias `detect_time`) = detection time after the kill, the
  `detect_delay` input.
* `rpo_s` = kill time - last checkpoint time.
* `view_split_s`: seconds during which the believed-alive nodes themselves formed several
  components (no single backbone can exist). `cds_impossible` counts the repair calls that
  hit such a split.
* The E3 representative series (`recovery.cases.<id>.series`) is the recovery metric's own
  data per second: `offered`, `served` and `ratio` = served / offered in outcome time, so
  total death plots as 0.
* `state_changes_per_min` = ACTIVE <-> non-ACTIVE transitions made by VSEPR (with its
  repair), fairness and resonance, per minute; split by source. Fairness only moves
  GHOST <-> STANDBY, reported as `fairness_moves_per_min`.
* `flaps`: a node reverses its previous ACTIVE transition within 2 VSEPR cycles (60 s);
  `vsepr_flaps` counts those where VSEPR made one of the two moves.
* `mean_max_avg_load_ratio`: per VSEPR cycle, max / mean `window_load` over believed-alive
  ACTIVE nodes, averaged over cycles. `mean_peak_relay_load` and `mean_avg_relay_load` are
  the max and the mean themselves, per second of the cycle: the ratio alone falls or rises
  with the size of the ACTIVE set (more relays dilute the mean), so balancing is judged at an
  equal ACTIVE set.
* `ghost_time_share`: time-averaged GHOST share of live nodes (energy proxy).

## 11. Determinism

Separate `random.Random` streams, seeded from strings derived from `seed`, for traffic,
route sampling, link loss, the initial STANDBY sample, the hotspot node, the checkpoint
phase, the kill and churn. Same seed, same everything; changing the routing mode does not
change who sends to whom, and changing the initial STANDBY or ACTIVE share does not change
the hotspot node or the checkpoint phase (common random numbers across a sweep). No wall
clock, no global RNG.
