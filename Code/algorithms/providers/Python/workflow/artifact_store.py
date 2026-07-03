from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import ArtifactRef


class ArtifactStore:
    def put(self, artifact: ArtifactRef, payload: object | None = None) -> ArtifactRef:
        raise NotImplementedError

    def get(self, artifact_id: str) -> ArtifactRef:
        raise NotImplementedError

    def load(self, artifact_id: str) -> object:
        raise NotImplementedError

    def exists(self, artifact_id: str) -> bool:
        raise NotImplementedError


@dataclass(slots=True)
class InMemoryArtifactStore(ArtifactStore):
    refs: dict[str, ArtifactRef] = field(default_factory=dict)
    payloads: dict[str, object] = field(default_factory=dict)

    def put(self, artifact: ArtifactRef, payload: object | None = None) -> ArtifactRef:
        self.refs[artifact.artifact_id] = artifact
        if payload is not None:
            self.payloads[artifact.artifact_id] = payload
        return artifact

    def get(self, artifact_id: str) -> ArtifactRef:
        if artifact_id not in self.refs:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return self.refs[artifact_id]

    def load(self, artifact_id: str) -> object:
        if artifact_id not in self.payloads:
            raise KeyError(f"Artifact payload not found: {artifact_id}")
        return self.payloads[artifact_id]

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self.refs
