"""Site-reality clustering: graph walk over entities + edges.

Algorithm
---------

1. **Seed.** Find every entity whose ``canonical_key`` starts with
   ``site:``. These are the candidate sites.
2. **Merge by edge.** Build a union-find structure keyed by
   ``site:*`` entity keys. For every edge of type ``co_mention``
   or ``same_as`` whose endpoints both anchor to a site key,
   union them. The envelope's ``edges`` array uses atom_id
   endpoints; we resolve those via ``atoms_by_entity_key`` index.
3. **Walk atoms.** For each cluster, gather every atom whose
   entity_keys touch any of the cluster's site keys.
4. **Name reconciliation.** A cluster's canonical name is the
   majority canonical_name among its member entities. Ties or
   single-vote clusters with multiple competing names trigger an
   LLM call (logged with
   :class:`EscalationReason.SITE_REALITY_AMBIGUOUS_NAME`). A
   cluster with zero candidate names triggers
   :class:`SITE_REALITY_UNNAMED_CLUSTER`.

Determinism
-----------

* All sets are converted to sorted tuples before being placed in
  the state.
* Cluster ids are derived from the smallest site key in the
  cluster (``cluster_<sha8>``-style would also work; we pick
  literal-key naming so ids are human-readable in tests).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.inference.client import ChatClient, ChatMessage
from orbitbrief_core.world_model.escalation import (
    EscalationLog,
    EscalationReason,
)
from orbitbrief_core.world_model.site_reality.state import (
    SiteCluster,
    SiteRealityState,
)


# Edge types that imply two atoms refer to the same real-world site.
# Phase-3 spec called for ``co_mention`` but the actual envelope
# EdgeType enum (parser-os) emits ``same_as`` and ``located_in`` for
# the equivalent semantics. ``contradicts`` is excluded — those
# edges mean the atoms disagree, not that they co-locate.
_MERGING_EDGE_TYPES: frozenset[str] = frozenset({"same_as", "located_in"})
_SITE_KEY_PREFIX = "site:"


@dataclass
class SiteRealityEngine:
    """Site-reality engine. Stateless aside from the chat client."""

    chat_client: ChatClient | None = None
    chat_model_id: str = "qwen3:14b"

    def compute(
        self,
        runtime: EvidenceRuntime,
        *,
        key: RuntimeKey | None = None,
    ) -> SiteRealityState:
        rk = key or runtime.default_key
        if rk is None:
            raise ValueError(
                "SiteRealityEngine.compute: no default key on runtime"
            )
        envelope = runtime.to_envelope_dict(rk)
        log = EscalationLog()

        site_entities = self._collect_site_entities(envelope)
        if not site_entities:
            return SiteRealityState(
                project_id=rk.project_id,
                compile_id=rk.compile_id,
                clusters=(),
                cluster_count=0,
                escalation_log=log.to_dict(),
                merged_keys=0,
            )

        # Atom → site_keys reverse index for O(1) lookups during merge.
        indexes = envelope.get("indexes") or {}
        atoms_by_key: dict[str, list[str]] = indexes.get(
            "atoms_by_entity_key"
        ) or {}
        atom_to_site_keys: dict[str, list[str]] = defaultdict(list)
        for site_key in site_entities:
            for atom_id in atoms_by_key.get(site_key, []):
                atom_to_site_keys[atom_id].append(site_key)

        # Union-find over site keys. We initialize parents to self so
        # singleton sites still produce a cluster.
        parent: dict[str, str] = {k: k for k in site_entities}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            # Pick lexicographically smallest as parent → stable cluster ids.
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

        # Edge-driven merges.
        for edge in envelope.get("edges") or ():
            if edge.get("edge_type") not in _MERGING_EDGE_TYPES:
                continue
            from_keys = atom_to_site_keys.get(edge.get("from_atom_id") or "", [])
            to_keys = atom_to_site_keys.get(edge.get("to_atom_id") or "", [])
            if not from_keys or not to_keys:
                continue
            for fk in from_keys:
                for tk in to_keys:
                    union(fk, tk)

        # Same-canonical-name implicit merges: if two site keys share a
        # canonical_name (case-insensitive normalized), treat them as
        # the same real site even without an explicit edge. Matches
        # how parser-os' entity normalizer fans out aliases.
        name_to_keys: dict[str, list[str]] = defaultdict(list)
        for site_key, ent in site_entities.items():
            norm = (ent.get("canonical_name") or "").strip().lower()
            if norm:
                name_to_keys[norm].append(site_key)
        for keys in name_to_keys.values():
            if len(keys) > 1:
                anchor = keys[0]
                for other in keys[1:]:
                    union(anchor, other)

        # Build clusters keyed by representative site key.
        groups: dict[str, list[str]] = defaultdict(list)
        for sk in site_entities:
            groups[find(sk)].append(sk)

        clusters: list[SiteCluster] = []
        merged = 0
        for rep, members in groups.items():
            if len(members) > 1:
                merged += len(members) - 1
            members.sort()
            cluster = self._build_cluster(
                rep,
                members,
                site_entities,
                atoms_by_key,
                envelope,
                log=log,
            )
            clusters.append(cluster)

        clusters.sort(key=lambda c: c.cluster_id)
        return SiteRealityState(
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            clusters=tuple(clusters),
            cluster_count=len(clusters),
            escalation_log=log.to_dict(),
            merged_keys=merged,
        )

    # ───── internals ─────

    @staticmethod
    def _collect_site_entities(
        envelope: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Return ``{canonical_key: entity_dict}`` for every site:* entity."""
        out: dict[str, dict[str, Any]] = {}
        for ent in envelope.get("entities") or ():
            ck = ent.get("canonical_key") or ""
            if ck.startswith(_SITE_KEY_PREFIX):
                out[ck] = ent
        return out

    def _build_cluster(
        self,
        rep: str,
        members: list[str],
        site_entities: dict[str, dict[str, Any]],
        atoms_by_key: dict[str, list[str]],
        envelope: dict[str, Any],
        *,
        log: EscalationLog,
    ) -> SiteCluster:
        # Collect atom ids and artifact ids across all member site keys.
        atom_ids: set[str] = set()
        for sk in members:
            atom_ids.update(atoms_by_key.get(sk, []))

        atoms_by_id = {a["id"]: a for a in envelope.get("atoms") or ()}
        artifact_ids: set[str] = set()
        for aid in atom_ids:
            atom = atoms_by_id.get(aid)
            if atom and atom.get("artifact_id"):
                artifact_ids.add(atom["artifact_id"])

        # Name reconciliation: vote across member entities.
        name_votes = Counter(
            (site_entities[sk].get("canonical_name") or "").strip()
            for sk in members
        )
        name_votes.pop("", None)
        candidate_names: list[str] = sorted(name_votes.keys())

        canonical_name, escalated = self._pick_canonical_name(
            members,
            site_entities,
            name_votes,
            candidate_names,
            log=log,
        )

        # Cluster confidence = majority share of canonical name votes,
        # capped at 1.0. Single-vote clusters get 1.0.
        if name_votes:
            top = max(name_votes.values())
            confidence = top / sum(name_votes.values())
        else:
            confidence = 0.5  # truly unnamed; midpoint to flag downstream

        return SiteCluster(
            cluster_id=f"site_cluster::{rep}",
            canonical_name=canonical_name,
            candidate_names=tuple(candidate_names),
            site_keys=tuple(members),
            member_atom_ids=tuple(sorted(atom_ids)),
            artifact_ids=tuple(sorted(artifact_ids)),
            name_resolved_by_llm=escalated,
            confidence=float(min(1.0, max(0.0, confidence))),
        )

    def _pick_canonical_name(
        self,
        members: list[str],
        site_entities: dict[str, dict[str, Any]],
        name_votes: Counter,
        candidate_names: list[str],
        *,
        log: EscalationLog,
    ) -> tuple[str, bool]:
        """Return ``(canonical_name, escalated_to_llm)``."""
        if not candidate_names:
            # Unnamed cluster — escalate if we can.
            if self.chat_client is None:
                # No client; emit a synthesized name so state is well-formed.
                return f"unnamed_{members[0]}", False
            log.record(
                engine="site_reality",
                reason=EscalationReason.SITE_REALITY_UNNAMED_CLUSTER,
                detail=f"members={members}",
                model_id=self.chat_model_id,
            )
            try:
                guess = self._ask_llm_name(members, site_entities, [])
            except Exception:
                return f"unnamed_{members[0]}", False
            return (guess or f"unnamed_{members[0]}"), bool(guess)

        # Single clear winner.
        top_count = max(name_votes.values())
        winners = [n for n, c in name_votes.items() if c == top_count]
        if len(winners) == 1:
            return winners[0], False

        # Tie among multiple distinct names — escalate.
        if self.chat_client is None:
            # Deterministic tiebreak: lexicographically smallest wins.
            return sorted(winners)[0], False
        log.record(
            engine="site_reality",
            reason=EscalationReason.SITE_REALITY_AMBIGUOUS_NAME,
            detail=f"members={members} candidates={candidate_names}",
            model_id=self.chat_model_id,
        )
        try:
            pick = self._ask_llm_name(members, site_entities, candidate_names)
        except Exception:
            return sorted(winners)[0], False
        if pick and pick in candidate_names:
            return pick, True
        return sorted(winners)[0], False

    def _ask_llm_name(
        self,
        members: list[str],
        site_entities: dict[str, dict[str, Any]],
        candidate_names: list[str],
    ) -> str | None:
        """LLM resolves the canonical name from competing candidates."""
        assert self.chat_client is not None
        evidence_lines = []
        for sk in members[:8]:
            ent = site_entities[sk]
            aliases = ent.get("aliases") or []
            evidence_lines.append(
                f"- key={sk} name={ent.get('canonical_name')!r} "
                f"aliases={list(aliases)[:5]}"
            )
        sys = (
            "You normalize site names for OrbitBrief. From the candidate "
            "names below, return the one that best represents the physical "
            "site. Reply with only the chosen name verbatim, no prose."
        )
        if candidate_names:
            usr = (
                "Candidates:\n"
                + "\n".join(f"- {c}" for c in candidate_names)
                + "\n\nEvidence:\n"
                + "\n".join(evidence_lines)
                + "\n\nReturn one candidate name verbatim."
            )
        else:
            usr = (
                "No candidate names; propose a short site label from the "
                "evidence below. Reply with only the proposed name.\n\n"
                "Evidence:\n" + "\n".join(evidence_lines)
            )
        # Generous budget for Qwen3's ``<think>`` block; we strip
        # it out below.
        reply = self.chat_client.complete(
            [ChatMessage("system", sys), ChatMessage("user", usr)],
            model=self.chat_model_id,
            temperature=0.0,
            max_tokens=512,
        )
        return _last_nonblank_line(reply) if reply else None


def _last_nonblank_line(text: str) -> str | None:
    """Strip Qwen3 ``<think>`` content and return the final answer line."""
    # Qwen3 thinking models emit ``<think>...</think>\n<answer>``.
    # Take everything after the last ``</think>`` if present.
    s = text
    if "</think>" in s:
        s = s.rsplit("</think>", 1)[1]
    for line in reversed(s.splitlines()):
        line = line.strip()
        if line:
            return line
    return None
