"""竞技场输入、证据与计算结果。"""

from dataclasses import dataclass
from typing import Literal

MODEL_VERSION = "arena-structural-v1"


@dataclass(frozen=True)
class Provenance:
    source: str
    version: str
    confidence: Literal["verified", "reference", "heuristic", "unknown"]
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class ArenaCharacter:
    key: str
    name: str
    name_code: str
    burst: int
    provenance: Provenance
    base_key: str = ""
    reenter: bool = False
    conditional_reenter: bool = False
    adaptive_b1: bool = False
    resource_id: str = ""


@dataclass(frozen=True)
class ArenaTeam:
    characters: tuple[ArenaCharacter, ...]

    def __post_init__(self) -> None:
        if len(self.characters) != 5:
            raise ValueError("每队必须有五人，并按 P1–P5 排列。")
        bases = [char.base_key or char.key for char in self.characters]
        if len(set(bases)) != 5:
            raise ValueError("同队包含重复角色，皮肤及珍藏变体也只能占一个位置。")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(char.key for char in self.characters)


@dataclass(frozen=True)
class BurstStep:
    stage: int
    position: int
    character_key: str
    name: str


@dataclass(frozen=True)
class BurstChain:
    steps: tuple[BurstStep, ...]
    valid: bool
    missing: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class SpeedEstimate:
    tier: float | None
    provenance: Provenance


@dataclass(frozen=True)
class MatchupEvidence:
    kind: Literal["mechanic", "statistic", "community", "heuristic", "personal"]
    text: str
    provenance: Provenance


@dataclass(frozen=True)
class ArenaRosterSnapshot:
    keys: frozenset[str]
    status: str
    unmapped: int
    fetched_at: str
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    team: ArenaTeam
    chain: BurstChain
    speed: SpeedEstimate
    score: int
    evidence: tuple[MatchupEvidence, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ArenaAnalysis:
    enemy: ArenaTeam
    chain: BurstChain
    speed: SpeedEstimate
    recommendations: tuple[Recommendation, ...]
    warnings: tuple[str, ...]
    roster_status: str
    searched: int
    model_version: str = MODEL_VERSION
    snapshot_date: str = ""

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.chain.provenance.missing_fields + self.speed.provenance.missing_fields))

    @property
    def data_status(self) -> Provenance:
        return self.speed.provenance


@dataclass(frozen=True)
class ArenaThreeTeamPlan:
    analyses: tuple[ArenaAnalysis, ...]
    teams: tuple[Recommendation, ...]
    objective: str
    searched: int
    truncated: bool
    warnings: tuple[str, ...]
    model_version: str = MODEL_VERSION
