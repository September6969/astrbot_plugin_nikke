"""内存激活与磁盘发布确认的独立状态和稳定业务指纹。"""

import hashlib
import json
from dataclasses import dataclass


def _stable(value):
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items() if key not in {
            "fetched_at", "updated_at", "observed_at", "status", "fingerprint",
            "display_relevance", "identity_match",
        }}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    return value


def revision(value) -> str:
    return hashlib.sha256(json.dumps(_stable(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass
class SnapshotState:
    active_display_revision: str = ""
    active_source_revision: str = ""
    persisted_display_revision: str = ""
    persisted_source_revision: str = ""
    generation: str = ""
    dirty: bool = True
    durability_error: str = ""

    def activate(self, service) -> None:
        self.active_display_revision = service._compute_batch_hash(list(service._events.values()))
        self.active_source_revision = revision({
            source: {
                "events": sorted((event.to_dict() for event in events), key=lambda item: item["id"]),
                "dataset_version": getattr(service._source_health.get(source), "dataset_version", 1),
            }
            for source, events in service._source_datasets.items()
        })
        if (self.active_display_revision != self.persisted_display_revision
                or self.active_source_revision != self.persisted_source_revision):
            self.dirty = True

    def acknowledge(self, generation: str) -> None:
        self.persisted_display_revision = self.active_display_revision
        self.persisted_source_revision = self.active_source_revision
        self.generation = generation
        self.dirty = False
        self.durability_error = ""
