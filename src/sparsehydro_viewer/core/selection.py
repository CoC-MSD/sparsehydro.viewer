"""The solutions selected across the application (the model of the cross-chart selection).

A :class:`SolutionRef` names one solution: a member of a run's final Pareto
set, or of the front a run reported at an earlier *generation*. A
:class:`SolutionSelection` is an ordered set of them with a *primary* one (the
last clicked), which detail views - parameters, unit hydrographs, components -
follow. Selections are immutable values: every edit returns a new one, so the
session can compare, store and emit them safely.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SolutionRef:
    """Solution *index* of run *run_id*: of its final front, or of the front reported at *generation*
    (the position of the report in the run's history)."""

    run_id: str
    index: int
    generation: int | None = None

    @property
    def is_final(self) -> bool:
        return self.generation is None

    def label(self) -> str:
        return f"#{self.index}" if self.generation is None else f"#{self.index} (report {self.generation + 1})"


@dataclass(frozen=True)
class SolutionSelection:
    refs: tuple[SolutionRef, ...] = ()
    primary: SolutionRef | None = None

    def __post_init__(self) -> None:
        refs = tuple(dict.fromkeys(self.refs))  # ordered, unique
        primary = self.primary if self.primary in refs else (refs[-1] if refs else None)
        object.__setattr__(self, "refs", refs)
        object.__setattr__(self, "primary", primary)

    def __bool__(self) -> bool:
        return bool(self.refs)

    def __len__(self) -> int:
        return len(self.refs)

    def __contains__(self, ref: object) -> bool:
        return ref in self.refs

    # -- queries ---------------------------------------------------------------

    def of_run(self, run_id: str) -> list[SolutionRef]:
        """This run's selected solutions, the primary one first when it belongs to the run."""
        refs = [r for r in self.refs if r.run_id == run_id]
        if self.primary in refs:
            refs.remove(self.primary)
            refs.insert(0, self.primary)
        return refs

    def indices(self, run_id: str, generation: int | None = None) -> list[int]:
        """Selected indices of one front of a run (the final one by default), primary first."""
        return [r.index for r in self.of_run(run_id) if r.generation == generation]

    def run_ids(self) -> list[str]:
        return list(dict.fromkeys(r.run_id for r in self.refs))

    # -- edits (each returns a new selection) ------------------------------------

    def replaced(self, refs: Iterable[SolutionRef], primary: SolutionRef | None = None) -> SolutionSelection:
        return SolutionSelection(tuple(refs), primary)

    def with_run(self, run_id: str, refs: Iterable[SolutionRef], primary: SolutionRef | None = None,
                 *, add: bool = False) -> SolutionSelection:
        """Replace (or with *add*, extend) the selection of one run, leaving other runs' selections alone."""
        new = [r for r in refs if r.run_id == run_id]
        kept = [r for r in self.refs if r.run_id != run_id or add]
        chosen = primary if primary is not None else (new[0] if new else self.primary)
        return SolutionSelection((*kept, *new), chosen)

    def toggled(self, ref: SolutionRef) -> SolutionSelection:
        """Add *ref* (it becomes primary) or, if it is selected, remove it."""
        if ref in self.refs:
            rest = tuple(r for r in self.refs if r != ref)
            return SolutionSelection(rest, self.primary if self.primary != ref else None)
        return SolutionSelection((*self.refs, ref), ref)

    def pruned(self, valid_run_ids: Iterable[str]) -> SolutionSelection:
        valid = set(valid_run_ids)
        return SolutionSelection(tuple(r for r in self.refs if r.run_id in valid), self.primary)


__all__ = ["SolutionRef", "SolutionSelection"]
