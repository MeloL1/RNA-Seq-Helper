from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from threading import Event
from typing import Any, Callable, Mapping
from uuid import uuid4


ProgressCallback = Callable[[str, float | None, str], None]

_SENSITIVE_METADATA_PATTERN = re.compile(
    r"(?i)\b(?:patient|subject|participant|donor|mrn|medical[_ -]?record|hospital[_ -]?record|"
    r"date[_ -]?of[_ -]?birth|diagnosis|age|sex|gender)\b|"
    r"\b(?:patient|subject|participant|donor|case|sample|specimen)[_-][A-Za-z0-9]+|"
    r"\b(?:patient|subject|participant|donor|case|sample|specimen)[ _-]*\d+\b|"
    r"患者|病人|受试者|志愿者|供者|捐献者|姓名|身份证|病历号|住院号|出生日期|年龄|性别|诊断|临床病史|"
    r"(?:样本|标本)[ _-]*(?:id|编号|号|名称)?[ _-]*\d+|"
    r"样本(?:[_ -]?(?:id|编号|号|名称)[_ -]?[A-Za-z0-9]+)|标本(?:[_ -]?(?:id|编号|号|名称)[_ -]?[A-Za-z0-9]+)"
)


def may_contain_sensitive_metadata(value: str | Path) -> bool:
    """Conservative marker-based check; unlabelled personal names cannot be inferred reliably."""
    return bool(_SENSITIVE_METADATA_PATTERN.search(str(value)))


def persisted_local_path(value: str | Path) -> str:
    """Hide local paths with explicit patient/sample identifiers in project metadata."""
    if may_contain_sensitive_metadata(value):
        return "[含疑似个人/样本标识的本地路径已隐藏]"
    return str(value)


class MeasurementType(str, Enum):
    RAW_COUNT = "RAW_COUNT"
    TPM = "TPM"
    FPKM = "FPKM"
    RPKM = "RPKM"
    CPM = "CPM"
    OTHER_NORMALIZED = "OTHER_NORMALIZED"
    UNKNOWN = "UNKNOWN"


class ValueScale(str, Enum):
    LINEAR = "LINEAR"
    LOG2 = "LOG2"
    OTHER_TRANSFORM = "OTHER_TRANSFORM"
    UNKNOWN = "UNKNOWN"


class ObservationUnit(str, Enum):
    BULK_SAMPLE = "BULK_SAMPLE"
    CELL = "CELL"
    UNKNOWN = "UNKNOWN"


class IssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class ReferenceStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_NEEDED = "NOT_NEEDED"


@dataclass(frozen=True)
class Evidence:
    basis: str
    source: str
    score: float
    fact_key: str = ""
    fact_value: str = ""
    location: str = ""
    excerpt: str = ""
    evidence_level: str = "hint"
    excerpt_redacted: bool = False
    reported_transform: str = ""

    def as_dict(self) -> dict[str, Any]:
        sensitive = (
            self.excerpt_redacted
            or may_contain_sensitive_metadata(self.source)
            or may_contain_sensitive_metadata(self.location)
            or may_contain_sensitive_metadata(self.excerpt)
        )
        return {
            "basis": self.basis,
            "source": "[已隐藏原文来源路径]" if sensitive else self.source,
            "score": self.score,
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "location": "[已隐藏来源位置]" if sensitive else self.location,
            "excerpt": "[句子包含可能的个人或样本标识，已隐藏整句]" if sensitive else self.excerpt,
            "evidence_level": self.evidence_level,
            "excerpt_redacted": sensitive,
            "reported_transform": self.reported_transform,
        }


@dataclass(frozen=True)
class Issue:
    code: str
    severity: IssueSeverity
    message_zh: str
    operation_zh: str


@dataclass(frozen=True)
class DataAsset:
    asset_id: str
    source_paths: tuple[Path, ...]
    kind: str
    role: str = "UNKNOWN"
    reader_key: str = ""
    confidence: float = 0.0
    evidence: tuple[Evidence, ...] = ()
    shape_hint: tuple[int, int] | None = None
    measurement_hint: MeasurementType = MeasurementType.UNKNOWN
    scale_hint: ValueScale = ValueScale.UNKNOWN
    issues: tuple[Issue, ...] = ()
    observation_unit_hint: str | None = None
    parent_asset_id: str | None = None
    archive_member_paths: tuple[str, ...] = ()
    content_fingerprint: str | None = None
    platform_ids: tuple[str, ...] = ()
    species_hint: str | None = None
    dimension_confidences: Mapping[str, float] = field(default_factory=dict)
    related_asset_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        safe_paths = [persisted_local_path(path) for path in self.source_paths]
        return {
            "asset_id": self.asset_id,
            "source_paths": safe_paths,
            "source_paths_redacted": safe_paths != [str(path) for path in self.source_paths],
            "parent_asset_id": self.parent_asset_id,
            "archive_member_paths": [persisted_local_path(item) for item in self.archive_member_paths],
            "content_fingerprint": self.content_fingerprint,
            "kind": self.kind,
            "role": self.role,
            "reader_key": self.reader_key,
            "confidence": self.confidence,
            "evidence": [item.as_dict() for item in self.evidence],
            "shape_hint": list(self.shape_hint) if self.shape_hint else None,
            "observation_unit_hint": self.observation_unit_hint,
            "platform_ids": list(self.platform_ids),
            "species_hint": self.species_hint,
            "dimension_confidences": dict(self.dimension_confidences),
            "related_asset_ids": list(self.related_asset_ids),
            "measurement_hint": self.measurement_hint.value,
            "scale_hint": self.scale_hint.value,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "message_zh": issue.message_zh,
                    "operation_zh": issue.operation_zh,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True)
class TablePreview:
    source_path: Path
    sheet_name: str | None
    rows: tuple[tuple[str, ...], ...]
    row_count_hint: int | None
    column_count_hint: int | None
    candidate_header_rows: tuple[int, ...]
    transposed: bool = False


@dataclass(frozen=True)
class PreparationRecipe:
    asset_id: str
    source_path: Path
    sheet_name: str | None
    header_row: int
    data_start_row: int
    transpose: bool
    feature_id_column: int
    sample_columns: tuple[int, ...]
    annotation_columns: tuple[int, ...] = ()
    ignored_columns: tuple[int, ...] = ()
    measurement_type: MeasurementType = MeasurementType.UNKNOWN
    value_scale: ValueScale = ValueScale.UNKNOWN
    input_transform: str = ""
    species_taxid: str | None = None
    sample_ids: tuple[str, ...] = ()
    notes: str = ""
    fact_confirmations: tuple[Mapping[str, Any], ...] = ()
    reported_transform: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "source_path": persisted_local_path(self.source_path),
            "source_path_redacted": may_contain_sensitive_metadata(self.source_path),
            "sheet_name": "[疑似敏感工作表名称已隐藏]" if may_contain_sensitive_metadata(self.sheet_name or "") else self.sheet_name,
            "header_row": self.header_row,
            "data_start_row": self.data_start_row,
            "transpose": self.transpose,
            "feature_id_column": self.feature_id_column,
            "sample_columns": list(self.sample_columns),
            "annotation_columns": list(self.annotation_columns),
            "ignored_columns": list(self.ignored_columns),
            "measurement_type": self.measurement_type.value,
            "value_scale": self.value_scale.value,
            "input_transform": self.input_transform,
            "species_taxid": self.species_taxid,
            "sample_ids": list(self.sample_ids),
            "notes": self.notes,
            "fact_confirmations": [dict(item) for item in self.fact_confirmations],
            "reported_transform": self.reported_transform,
        }


@dataclass(frozen=True)
class ValidationSummary:
    passed: bool
    issues: tuple[Issue, ...]
    feature_count: int
    sample_count: int
    numeric_cell_count: int

    @property
    def blockers(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == IssueSeverity.BLOCKING)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "feature_count": self.feature_count,
            "sample_count": self.sample_count,
            "numeric_cell_count": self.numeric_cell_count,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "message_zh": issue.message_zh,
                    "operation_zh": issue.operation_zh,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True)
class ExpressionFilterSpec:
    """记录过滤规则本身，避免把启发式阈值藏在 runner 里。"""

    scale: str
    threshold: float | None
    unit: str | None
    min_samples: int | None
    reason_zh: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "threshold": self.threshold,
            "unit": self.unit,
            "min_samples": self.min_samples,
            "reason_zh": self.reason_zh,
        }


@dataclass(frozen=True)
class DEGConfig:
    control_group: str
    test_group: str
    fdr_threshold: float = 0.05
    lfc_threshold: float = 1.0
    expression_filter: ExpressionFilterSpec | None = None
    paired_subject_column: str | None = None
    batch_column: str | None = None
    lfc_shrinkage: str = "not_requested"
    top_heatmap_features: int = 30
    random_seed: int = 20260913

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_group": self.control_group,
            "test_group": self.test_group,
            "fdr_threshold": self.fdr_threshold,
            "lfc_threshold": self.lfc_threshold,
            "expression_filter": self.expression_filter.as_dict() if self.expression_filter else None,
            "paired_subject_column": self.paired_subject_column,
            "batch_column": self.batch_column,
            "lfc_shrinkage": self.lfc_shrinkage,
            "top_heatmap_features": self.top_heatmap_features,
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True)
class AnalysisPlan:
    plan_id: str
    matrix_hash: str
    method: str
    method_reason_zh: str
    analysis_basis: str
    method_profile_id: str
    resolved_method_parameters: Mapping[str, Any]
    design: Mapping[str, Any]
    contrast: Mapping[str, Any]
    preprocessing: Mapping[str, Any]
    config: DEGConfig
    limitations_zh: tuple[str, ...] = ()
    input_selection_reason_zh: str = ""
    warnings: tuple[str, ...] = ()
    blockers: tuple[Issue, ...] = ()
    confirmation_digest: str = ""
    reference_request: ReferenceRequest | None = None
    reference_required_for_fit: bool = False
    source_modality: str | None = None
    feature_metadata_hash: str | None = None

    @property
    def runnable(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "matrix_hash": self.matrix_hash,
            "method": self.method,
            "method_reason_zh": self.method_reason_zh,
            "analysis_basis": self.analysis_basis,
            "source_modality": self.source_modality,
            "feature_metadata_hash": self.feature_metadata_hash,
            "method_profile_id": self.method_profile_id,
            "resolved_method_parameters": dict(self.resolved_method_parameters),
            "design": dict(self.design),
            "contrast": dict(self.contrast),
            "preprocessing": dict(self.preprocessing),
            "config": self.config.as_dict(),
            "limitations_zh": list(self.limitations_zh),
            "input_selection_reason_zh": self.input_selection_reason_zh,
            "warnings": list(self.warnings),
            "blockers": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "message_zh": issue.message_zh,
                    "operation_zh": issue.operation_zh,
                }
                for issue in self.blockers
            ],
            "confirmation_digest": self.confirmation_digest,
            "reference_request": {
                "feature_ids_count": len(self.reference_request.feature_ids),
                "species_taxid": self.reference_request.species_taxid,
                "platform_id": self.reference_request.platform_id,
                "source_paths": [persisted_local_path(path) for path in self.reference_request.source_paths],
            } if self.reference_request else None,
            "reference_required_for_fit": self.reference_required_for_fit,
        }


@dataclass(frozen=True)
class ExpressionMatrix:
    matrix_id: str
    values: MatrixStoreRef
    feature_metadata: MatrixStoreRef
    sample_metadata: MatrixStoreRef
    observation_unit: ObservationUnit
    measurement_type: MeasurementType
    value_scale: ValueScale
    input_transform: str
    feature_id_type: str
    species_taxid: str | None
    source_asset_ids: tuple[str, ...]
    recipe_id: str
    validation: ValidationSummary
    content_hash: str
    measurement_provenance: str = ""
    platform_id: str | None = None
    source_modality: str | None = None


@dataclass(frozen=True)
class ReferenceRequest:
    """参考映射请求；只携带特征编号，不上传表达矩阵。"""

    feature_ids: tuple[str, ...]
    species_taxid: str | None = None
    platform_id: str | None = None
    source_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ReferenceResult:
    status: ReferenceStatus
    mapping: Mapping[str, tuple[str, ...]]
    provider: str | None
    species_taxid: str | None
    platform_id: str | None
    checksum: str | None
    coverage: float
    ambiguous_count: int
    unmapped_count: int
    guide_zh: str
    request: ReferenceRequest | None = None
    release: str | None = None
    retrieved_at: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class JobContext:
    """跨 UI、服务和 worker 边界传递的最小任务上下文。"""

    workdir: Path
    job_id: str = field(default_factory=lambda: str(uuid4()))
    cancel_event: Event = field(default_factory=Event, compare=False, repr=False)
    on_progress: ProgressCallback | None = field(default=None, compare=False, repr=False)
    # 大型真实矩阵（例如 GEO 芯片/表达矩阵）允许更长的 R 计算时间；
    # 取消按钮仍可随时终止任务。微型验证不会因此变慢。
    timeout_seconds: int = 600

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def emit(self, stage: str, fraction: float | None, message: str) -> None:
        if self.on_progress:
            self.on_progress(stage, fraction, message)


@dataclass(frozen=True)
class MatrixStoreRef:
    path: Path
    storage: str
    dtype: str
    shape: tuple[int, int]
    content_hash: str | None = None


@dataclass(frozen=True)
class TableStoreRef:
    path: Path
    schema: Mapping[str, str]
    content_hash: str | None = None


@dataclass(frozen=True)
class ArtifactRef:
    path: Path
    format: str
    purpose: str
    content_hash: str | None = None


@dataclass(frozen=True)
class RJobRequest:
    request_id: str
    method: str
    payload: Mapping[str, Any]
    profile_id: str = "stage0-micro-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "method": self.method,
            "profile_id": self.profile_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RJobResponse:
    request_id: str
    ok: bool
    result: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RJobResponse":
        return cls(
            request_id=str(value.get("request_id", "")),
            ok=bool(value.get("ok", False)),
            result=value.get("result"),
            error=value.get("error"),
        )
