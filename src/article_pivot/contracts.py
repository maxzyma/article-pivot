from __future__ import annotations

from typing import Any, Protocol

from .model import CanonicalDocument, TranslationOverlay
from .package import CanonicalPackage
from .validation import ValidationReport


class SourceAdapter(Protocol):
    def match(self, url: str) -> bool: ...

    def fetch(self, request: Any) -> Any: ...

    def parse(self, snapshot: Any) -> CanonicalDocument: ...

    def validate(self, document: CanonicalDocument) -> ValidationReport: ...


class DiscoveryAdapter(Protocol):
    def discover(self, cursor: Any | None) -> Any: ...


class Translator(Protocol):
    def translate(self, document: CanonicalDocument, policy: Any) -> TranslationOverlay: ...


class Renderer(Protocol):
    def capabilities(self) -> Any: ...

    def render(
        self,
        document: CanonicalDocument,
        overlay: TranslationOverlay | None,
        policy: Any,
    ) -> Any: ...


class ArchiveAdapter(Protocol):
    def plan(self, package: CanonicalPackage, **policy: Any) -> Any: ...

    def write(self, plan: Any) -> Any: ...

    def verify(self, receipt: Any) -> None: ...


class PublisherAdapter(Protocol):
    def capabilities(self) -> Any: ...

    def validate(self, artifact: Any) -> ValidationReport: ...

    def plan(self, artifact: Any, destination: Any) -> Any: ...

    def publish(self, plan: Any, idempotency_key: str) -> Any: ...

    def read_back(self, receipt: Any) -> Any: ...

    def reconcile(self, receipt: Any) -> Any: ...

    def rollback(self, receipt: Any) -> Any: ...

