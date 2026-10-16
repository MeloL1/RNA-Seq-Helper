from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from rnaseq_helper.domain.models import Issue, IssueSeverity


@dataclass(frozen=True)
class GroupingSuggestion:
    pattern: str
    title_zh: str
    control_group: str | None
    test_group: str | None
    assignments: Mapping[str, str]
    evidence_zh: str
    confidence: float
    requires_confirmation: bool = True


@dataclass(frozen=True)
class GroupingValidation:
    passed: bool
    issues: tuple[Issue, ...]
    group_sizes: Mapping[str, int]


class GroupingService:
    """只生成可审查建议，不把列名猜测直接变成分析设计。"""

    PATTERNS = (
        ("untreated_sepsis", "未治疗与脓毒症", re.compile(r"(?i)(?:^|[_\-.])untreated(?:[_\-.]|$)"), re.compile(r"(?i)(?:^|[_\-.])sepsis(?:[_\-.]|$)"), "GEO 样本注释包含 untreated/Sepsis"),
        ("untreated_sirs", "未治疗与 SIRS", re.compile(r"(?i)(?:^|[_\-.])untreated(?:[_\-.]|$)"), re.compile(r"(?i)(?:^|[_\-.])sirs(?:[_\-.]|$)"), "GEO 样本注释包含 untreated/SIRS"),
        ("untreated_se_ards", "未治疗与 se/ARDS", re.compile(r"(?i)(?:^|[_\-.])untreated(?:[_\-.]|$)"), re.compile(r"(?i)(?:^|[_\-.])se_ards(?:[_\-.]|$)"), "GEO 样本注释包含 untreated/se-ARDS"),
        ("ctrl_treat", "对照组与处理组", re.compile(r"(?i)(?:^|[_\-.])(ctrl|control|vehicle)(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])(treat|treated|drug|model)(?:[_\-.]|\d|$)"), "列名包含清晰的对照/处理词边界"),
        ("normal_tumor", "正常组与肿瘤组", re.compile(r"(?i)(?:^|[_\-.])normal(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])tumou?r(?:[_\-.]|\d|$)"), "列名包含 Normal/Tumor"),
        ("wt_ko", "WT 与 KO", re.compile(r"(?i)(?:^|[_\-.])wt(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])ko(?:[_\-.]|\d|$)"), "列名包含 WT/KO"),
        ("vehicle_drug", "溶剂与用药", re.compile(r"(?i)(?:^|[_\-.])vehicle(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])drug(?:[_\-.]|\d|$)"), "列名包含 Vehicle/Drug"),
        ("sham_model", "假手术与模型", re.compile(r"(?i)(?:^|[_\-.])sham(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])model(?:[_\-.]|\d|$)"), "列名包含 Sham/Model"),
        ("healthy_disease", "健康与疾病", re.compile(r"(?i)(?:^|[_\-.])healthy(?:[_\-.]|\d|$)"), re.compile(r"(?i)(?:^|[_\-.])disease(?:[_\-.]|\d|$)"), "列名包含 Healthy/Disease"),
    )

    def suggest(
        self,
        sample_ids: tuple[str, ...] | list[str],
        sample_metadata: Mapping[str, Mapping[str, str]] | None = None,
    ) -> tuple[GroupingSuggestion, ...]:
        names = tuple(str(value) for value in sample_ids)
        metadata = sample_metadata or {}
        searchable_text = {
            name: re.sub(r"[^0-9A-Za-z]+", "_", " ".join(
                [name]
                + [str(value) for key, value in metadata.get(name, {}).items()
                   if key.casefold() not in {"sample_id", "geo_accession"} and str(value).strip()]
            )).strip("_")
            for name in names
        }
        metadata_used = any(searchable_text[name] != name for name in names)
        suggestions: list[GroupingSuggestion] = []
        for pattern, title, control_re, test_re, evidence in self.PATTERNS:
            assignments: dict[str, str] = {}
            control_hits = [name for name in names if control_re.search(searchable_text[name])]
            test_hits = [name for name in names if test_re.search(searchable_text[name])]
            if control_hits and test_hits and not set(control_hits).intersection(test_hits):
                assignments.update({name: "control" for name in control_hits})
                assignments.update({name: "test" for name in test_hits})
                source_evidence = evidence + ("；同时参考了样本注释" if metadata_used else "")
                suggestions.append(GroupingSuggestion(pattern, title, "control", "test", assignments, source_evidence, 0.9))
        paired = self._paired_suggestion(names)
        if paired:
            suggestions.append(paired)
        if not suggestions:
            if metadata_used:
                evidence = "样本注释中也没有识别出可靠的两组边界，软件不会仅凭 GSM 编号或注释猜测分组。"
            else:
                evidence = "样本编号自身不含足够实验含义，软件不会猜前半对后半。"
            suggestions.append(GroupingSuggestion("unresolved", "尚未识别出可靠分组", None, None, {}, evidence, 0.2))
        return tuple(suggestions)

    def validate(self, assignments: Mapping[str, str], sample_ids: tuple[str, ...] | list[str], paired_subjects: Mapping[str, str] | None = None, batch: Mapping[str, str] | None = None) -> GroupingValidation:
        issues: list[Issue] = []
        names = tuple(sample_ids)
        extra = [name for name in assignments if name not in names]
        if extra:
            issues.append(Issue("UNKNOWN_SAMPLE_ASSIGNMENT", IssueSeverity.BLOCKING, "分组表中包含不在表达矩阵里的样本。", "请按唯一样本 ID 重新匹配"))
        groups: dict[str, int] = {}
        # 未确认、空值和 excluded 都不进入本次两组比较；界面已把未确认直接显示为排除。
        for name in names:
            group = assignments.get(name) or "excluded"
            if group and group != "excluded":
                groups[group] = groups.get(group, 0) + 1
        if len(groups) != 2:
            issues.append(Issue("NOT_TWO_GROUPS", IssueSeverity.BLOCKING, "当前版本需要恰好两组独立样本。", "请合并前先确认实验含义，或暂缓复杂设计"))
        for group, count in groups.items():
            if count < 2:
                issues.append(Issue("TOO_FEW_REPLICATES", IssueSeverity.BLOCKING, f"组 {group} 只有 {count} 个样本。", "每组至少需要 2 个独立生物学样本"))
        if paired_subjects:
            active_names = [name for name in names if assignments.get(name) != "excluded"]
            missing_subjects = [name for name in active_names if not paired_subjects.get(name)]
            if missing_subjects:
                issues.append(Issue("INCOMPLETE_PAIR_METADATA", IssueSeverity.BLOCKING, "配对设计只填写了部分样本的个体编号。", "请为每个样本填写配对个体，或清空配对列按独立样本分析"))
            subjects = {}
            for sample, subject in paired_subjects.items():
                if sample in active_names and assignments.get(sample) in {"control", "test"}:
                    subjects.setdefault(subject, set()).add(assignments[sample])
            subject_samples: dict[str, list[str]] = {}
            for sample in active_names:
                subject = paired_subjects.get(sample)
                if subject:
                    subject_samples.setdefault(subject, []).append(sample)
            complete = [
                subject for subject, subject_groups in subjects.items()
                if len(subject_groups) == 2 and len(subject_samples.get(subject, ())) == 2
            ]
            if len(complete) < 2:
                issues.append(Issue("INCOMPLETE_PAIRS", IssueSeverity.BLOCKING, "完整配对数少于 2 对。", "请核实个体编号和前后测关系"))
            elif len(complete) < 3:
                issues.append(Issue("NON_ESTIMABLE", IssueSeverity.BLOCKING, "配对设计的残差自由度不足，当前至少需要 3 对完整样本。", "请补充完整配对，或改用有足够独立重复的设计"))
        if batch:
            active_names = [name for name in names if assignments.get(name) != "excluded"]
            missing_batches = [name for name in active_names if not batch.get(name)]
            if missing_batches:
                issues.append(Issue("INCOMPLETE_BATCH_METADATA", IssueSeverity.BLOCKING, "批次协变量只填写了部分样本。", "请为每个样本填写批次，或清空批次列"))
            else:
                active_batch_levels = {
                    str(batch.get(name, "")).strip()
                    for name in active_names
                    if str(batch.get(name, "")).strip()
                }
                if len(active_batch_levels) == 1:
                    issues.append(Issue(
                        "BATCH_NO_VARIATION",
                        IssueSeverity.WARNING,
                        "本次纳入的样本都属于同一个批次，无法估计批次差异；软件不会把这个批次列加入统计模型。",
                        "如批次信息填写有误，请返回修改；否则可继续分析，但结果不含批次校正",
                    ))
            group_batches: dict[str, set[str]] = {}
            for sample, value in batch.items():
                group = assignments.get(sample)
                if group in {"control", "test"}:
                    group_batches.setdefault(group, set()).add(str(value))
            batch_sets = list(group_batches.values())
            completely_separated = (
                len(batch_sets) == 2
                and all(len(values) == 1 for values in batch_sets)
                and batch_sets[0].isdisjoint(batch_sets[1])
            )
            if completely_separated:
                issues.append(Issue("BATCH_CONFOUNDING", IssueSeverity.BLOCKING, "批次与实验组完全重合，无法区分两者影响。", "请补充信息或暂停本次分析"))
        return GroupingValidation(not any(issue.severity == IssueSeverity.BLOCKING for issue in issues), tuple(issues), groups)

    @staticmethod
    def _paired_suggestion(names: tuple[str, ...]) -> GroupingSuggestion | None:
        matches: dict[str, dict[str, str]] = {}
        for name in names:
            match = re.match(r"(?i)^(.+?)[_-](pre|post|before|after)$", name)
            if match:
                subject, timepoint = match.group(1), match.group(2).lower()
                matches.setdefault(subject, {})[timepoint] = name
        complete = {subject: values for subject, values in matches.items() if len(values) >= 2}
        if not complete:
            return None
        assignments = {}
        for values in complete.values():
            for timepoint, name in values.items():
                assignments[name] = "pre" if timepoint in {"pre", "before"} else "post"
        return GroupingSuggestion("paired_pre_post", "前后测配对候选", "pre", "post", assignments, "样本名包含相同个体编号和 Pre/Post 后缀，需要逐项核实配对关系。", 0.78)
