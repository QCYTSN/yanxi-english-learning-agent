from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal


DEFAULT_TRACK_ID = "ielts-academic"


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """One versioned AI-assisted workflow owned by a learning track.

    A Capability is a product workflow, not a model, CLI process, Skill or
    tool. It owns the minimum context boundary and output contract while the
    Inference Broker chooses how that contract is executed.
    """

    capability_id: str
    title: str
    module: str
    output_contract: str
    skill: str
    privacy_scope: Literal["learning_record", "private_material"]
    media_types: tuple[Literal["image", "audio"], ...] = ()
    default_timeout_seconds: int = 300

    def descriptor(self, *, track_id: str | None = None) -> dict[str, object]:
        value = asdict(self)
        value["media_types"] = list(self.media_types)
        if track_id:
            value["track_id"] = track_id
        return value


@dataclass(frozen=True, slots=True)
class LearningDimensionSpec:
    dimension_id: str
    title: str
    description: str
    default_skill_id: str
    order: int

    def descriptor(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillNodeSpec:
    skill_id: str
    dimension_id: str
    title: str
    description: str
    parent_skill_id: str | None = None
    order: int = 0

    def descriptor(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssessmentScaleSpec:
    scale_id: str
    title: str
    minimum: float
    maximum: float
    step: float | None = None

    def descriptor(self) -> dict[str, object]:
        return asdict(self)

    def normalise(self, value: float) -> float:
        if self.maximum <= self.minimum:
            raise ValueError(f"Invalid assessment scale: {self.scale_id}")
        bounded = min(self.maximum, max(self.minimum, float(value)))
        return (bounded - self.minimum) / (self.maximum - self.minimum)


@dataclass(frozen=True, slots=True)
class EvidenceSkillMapping:
    dimension_id: str
    evidence_kind: str
    patterns: tuple[str, ...]
    skill_id: str

    def matches(self, label: str) -> bool:
        normalised = _normalise_label(label)
        return any(_normalise_label(pattern) in normalised for pattern in self.patterns)


@dataclass(frozen=True, slots=True)
class DomainPackSpec:
    track_id: str
    title: str
    short_title: str
    description: str
    language: str
    status: Literal["active", "preview", "disabled"]
    teaching_policy_id: str
    assessment_scale: AssessmentScaleSpec
    dimensions: tuple[LearningDimensionSpec, ...]
    skills: tuple[SkillNodeSpec, ...]
    capabilities: tuple[CapabilitySpec, ...]
    evidence_mappings: tuple[EvidenceSkillMapping, ...] = ()

    def descriptor(
        self,
        *,
        include_capabilities: bool = True,
        include_skills: bool = False,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "track_id": self.track_id,
            "title": self.title,
            "short_title": self.short_title,
            "description": self.description,
            "language": self.language,
            "status": self.status,
            "teaching_policy_id": self.teaching_policy_id,
            "assessment_scale": self.assessment_scale.descriptor(),
            "dimensions": [item.descriptor() for item in self.dimensions],
        }
        if include_capabilities:
            result["capabilities"] = [
                item.descriptor(track_id=self.track_id) for item in self.capabilities
            ]
        if include_skills:
            result["skills"] = [item.descriptor() for item in self.skills]
        return result

    def skill(self, skill_id: str) -> SkillNodeSpec:
        for item in self.skills:
            if item.skill_id == skill_id:
                return item
        raise ValueError(f"Unknown skill {skill_id!r} for learning track {self.track_id!r}")

    def dimension(self, dimension_id: str) -> LearningDimensionSpec:
        for item in self.dimensions:
            if item.dimension_id == dimension_id:
                return item
        raise ValueError(
            f"Unknown dimension {dimension_id!r} for learning track {self.track_id!r}"
        )

    def resolve_evidence_skill(
        self,
        *,
        dimension_id: str,
        evidence_kind: str,
        label: str | None,
    ) -> str:
        dimension = self.dimension(dimension_id)
        if label:
            for mapping in self.evidence_mappings:
                if (
                    mapping.dimension_id == dimension_id
                    and mapping.evidence_kind == evidence_kind
                    and mapping.matches(label)
                ):
                    return mapping.skill_id
        return dimension.default_skill_id


def _normalise_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


IELTS_CAPABILITIES = (
    CapabilitySpec(
        capability_id="writing_review",
        title="Writing evidence review",
        module="writing",
        output_contract="writing-review@1",
        skill="ielts-writing",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="writing_mock_review",
        title="Writing full mock review",
        module="writing",
        output_contract="writing-mock-review@1",
        skill="ielts-writing",
        privacy_scope="private_material",
        media_types=("image",),
        default_timeout_seconds=600,
    ),
    CapabilitySpec(
        capability_id="reading_explanation",
        title="Reading wrong-answer explanation",
        module="reading",
        output_contract="reading-review@1",
        skill="ielts-reading",
        privacy_scope="learning_record",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="study_material_help",
        title="Persistent IELTS teacher dialogue",
        module="cross_module",
        output_contract="study-help@1",
        skill="ielts-study-help",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="listening_review",
        title="Listening error review",
        module="listening",
        output_contract="listening-review@1",
        skill="ielts-progress",
        privacy_scope="learning_record",
        media_types=("audio",),
    ),
    CapabilitySpec(
        capability_id="speaking_evaluation",
        title="Speaking evidence evaluation",
        module="speaking",
        output_contract="speaking-evaluation@1",
        skill="ielts-speaking",
        privacy_scope="private_material",
        media_types=("audio",),
        default_timeout_seconds=600,
    ),
    CapabilitySpec(
        capability_id="study_plan",
        title="Evidence-aware study plan",
        module="cross_module",
        output_contract="study-plan@1",
        skill="ielts",
        privacy_scope="learning_record",
    ),
    CapabilitySpec(
        capability_id="diagnostic_summary",
        title="Diagnostic summary",
        module="cross_module",
        output_contract="diagnostic-summary@1",
        skill="ielts",
        privacy_scope="learning_record",
    ),
    CapabilitySpec(
        capability_id="weekly_coaching",
        title="Weekly coaching explanation",
        module="progress",
        output_contract="weekly-coaching@1",
        skill="ielts-progress",
        privacy_scope="learning_record",
    ),
)


IELTS_DIMENSIONS = (
    LearningDimensionSpec(
        "listening",
        "Listening",
        "Understand spoken English under IELTS Academic task conditions.",
        "listening.detail",
        10,
    ),
    LearningDimensionSpec(
        "reading",
        "Reading",
        "Read academic passages accurately, efficiently and with evidence.",
        "reading.locate_evidence",
        20,
    ),
    LearningDimensionSpec(
        "writing",
        "Writing",
        "Produce and revise Task 1 and Task 2 responses against IELTS criteria.",
        "writing.task_response",
        30,
    ),
    LearningDimensionSpec(
        "speaking",
        "Speaking",
        "Develop spoken responses across Parts 1, 2 and 3.",
        "speaking.fluency_coherence",
        40,
    ),
)


IELTS_SKILLS = (
    SkillNodeSpec("listening.gist", "listening", "Main idea", "Identify the main point and purpose of a recording.", order=10),
    SkillNodeSpec("listening.detail", "listening", "Detail recognition", "Capture names, numbers, facts and qualifying detail.", order=20),
    SkillNodeSpec("listening.paraphrase", "listening", "Spoken paraphrase", "Connect spoken wording with paraphrased question language.", order=30),
    SkillNodeSpec("listening.signposting", "listening", "Discourse signposting", "Use transitions and speaker organisation to anticipate answers.", order=40),
    SkillNodeSpec("listening.form_completion", "listening", "Form and note completion", "Apply word limits, grammar and spelling accurately.", order=50),
    SkillNodeSpec("reading.gist", "reading", "Passage and paragraph gist", "Identify central ideas and paragraph functions.", order=10),
    SkillNodeSpec("reading.locate_evidence", "reading", "Evidence location", "Locate the exact passage evidence relevant to a question.", order=20),
    SkillNodeSpec("reading.paraphrase", "reading", "Written paraphrase", "Recognise synonymy and structural paraphrase between question and passage.", order=30),
    SkillNodeSpec("reading.inference", "reading", "Inference and logical status", "Distinguish stated facts, contradictions and unsupported claims.", order=40),
    SkillNodeSpec("reading.writer_position", "reading", "Writer position", "Identify attitude, claim ownership and rhetorical purpose.", order=50),
    SkillNodeSpec("reading.question_strategy", "reading", "Question strategy", "Apply task-specific instructions without compromising evidence accuracy.", order=60),
    SkillNodeSpec("writing.task_response", "writing", "Task response", "Address every requirement with a clear, sufficiently developed position or overview.", order=10),
    SkillNodeSpec("writing.coherence_cohesion", "writing", "Coherence and cohesion", "Organise ideas and connect them accurately without mechanical overuse.", order=20),
    SkillNodeSpec("writing.lexical_resource", "writing", "Lexical resource", "Use precise, flexible and context-appropriate vocabulary.", order=30),
    SkillNodeSpec("writing.grammatical_range_accuracy", "writing", "Grammar", "Use varied structures with controlled accuracy.", order=40),
    SkillNodeSpec("writing.revision", "writing", "Evidence-led revision", "Diagnose and improve a draft before comparing a model alternative.", order=50),
    SkillNodeSpec("speaking.fluency_coherence", "speaking", "Fluency and coherence", "Sustain, organise and develop spoken responses naturally.", order=10),
    SkillNodeSpec("speaking.lexical_resource", "speaking", "Lexical resource", "Use flexible and precise vocabulary in spontaneous speech.", order=20),
    SkillNodeSpec("speaking.grammatical_range_accuracy", "speaking", "Grammar", "Use varied spoken structures with appropriate control.", order=30),
    SkillNodeSpec("speaking.pronunciation", "speaking", "Pronunciation", "Remain intelligible through sound, stress, rhythm and intonation choices.", order=40),
    SkillNodeSpec("speaking.development", "speaking", "Answer development", "Extend answers with relevant explanation and examples.", order=50),
)


IELTS_EVIDENCE_MAPPINGS = (
    EvidenceSkillMapping("listening", "question_type", ("form completion", "note completion", "table completion", "sentence completion"), "listening.form_completion"),
    EvidenceSkillMapping("listening", "question_type", ("matching", "multiple choice"), "listening.paraphrase"),
    EvidenceSkillMapping("listening", "question_type", ("map", "plan", "diagram", "number", "short answer"), "listening.detail"),
    EvidenceSkillMapping("reading", "question_type", ("heading", "paragraph information"), "reading.gist"),
    EvidenceSkillMapping("reading", "question_type", ("true false", "yes no", "not given", "inference"), "reading.inference"),
    EvidenceSkillMapping("reading", "question_type", ("summary completion", "sentence completion", "note completion", "table completion"), "reading.paraphrase"),
    EvidenceSkillMapping("reading", "question_type", ("writer", "claim", "view"), "reading.writer_position"),
    EvidenceSkillMapping("reading", "question_type", ("matching", "short answer", "multiple choice"), "reading.locate_evidence"),
    EvidenceSkillMapping("writing", "criterion", ("task achievement", "task response", "task fulfilment"), "writing.task_response"),
    EvidenceSkillMapping("writing", "criterion", ("coherence", "cohesion"), "writing.coherence_cohesion"),
    EvidenceSkillMapping("writing", "criterion", ("lexical", "vocabulary"), "writing.lexical_resource"),
    EvidenceSkillMapping("writing", "criterion", ("grammar", "grammatical"), "writing.grammatical_range_accuracy"),
    EvidenceSkillMapping("speaking", "criterion", ("fluency", "coherence"), "speaking.fluency_coherence"),
    EvidenceSkillMapping("speaking", "criterion", ("lexical", "vocabulary"), "speaking.lexical_resource"),
    EvidenceSkillMapping("speaking", "criterion", ("grammar", "grammatical"), "speaking.grammatical_range_accuracy"),
    EvidenceSkillMapping("speaking", "criterion", ("pronunciation",), "speaking.pronunciation"),
)


IELTS_ACADEMIC_PACK = DomainPackSpec(
    track_id=DEFAULT_TRACK_ID,
    title="IELTS Academic",
    short_title="IELTS",
    description="Evidence-led preparation for IELTS Academic Listening, Reading, Writing and Speaking.",
    language="en",
    status="active",
    teaching_policy_id="ielts-academic-policy@1",
    assessment_scale=AssessmentScaleSpec("ielts-band", "IELTS Band", 0.0, 9.0, 0.5),
    dimensions=IELTS_DIMENSIONS,
    skills=IELTS_SKILLS,
    capabilities=IELTS_CAPABILITIES,
    evidence_mappings=IELTS_EVIDENCE_MAPPINGS,
)


GENERAL_TRACK_ID = "general-english"

GENERAL_CAPABILITIES = (
    CapabilitySpec(
        capability_id="study_help",
        title="General English teacher dialogue",
        module="cross_module",
        output_contract="general-study-help@1",
        skill="general-study-help",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="writing_feedback",
        title="Writing feedback",
        module="writing",
        output_contract="general-writing-feedback@1",
        skill="general-writing",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="speaking_prompt",
        title="Speaking practice prompt and evaluation",
        module="speaking",
        output_contract="general-speaking-prompt@1",
        skill="general-speaking",
        privacy_scope="private_material",
    ),
    CapabilitySpec(
        capability_id="vocabulary_lesson",
        title="Vocabulary teaching",
        module="vocabulary",
        output_contract="general-vocabulary@1",
        skill="general-vocabulary",
        privacy_scope="private_material",
    ),
    CapabilitySpec(
        capability_id="reading_coach",
        title="Reading comprehension coaching",
        module="reading",
        output_contract="general-reading-coach@1",
        skill="general-reading",
        privacy_scope="private_material",
        media_types=("image",),
    ),
    CapabilitySpec(
        capability_id="grammar_lesson",
        title="Grammar teaching in context",
        module="grammar",
        output_contract="general-grammar@1",
        skill="general-grammar",
        privacy_scope="private_material",
    ),
)


GENERAL_DIMENSIONS = (
    LearningDimensionSpec(
        "listening",
        "Listening",
        "Understand everyday and workplace spoken English.",
        "listening.gist",
        10,
    ),
    LearningDimensionSpec(
        "reading",
        "Reading",
        "Read daily and work documents with confidence.",
        "reading.comprehension",
        20,
    ),
    LearningDimensionSpec(
        "writing",
        "Writing",
        "Write clear everyday and workplace messages.",
        "writing.expression",
        30,
    ),
    LearningDimensionSpec(
        "speaking",
        "Speaking",
        "Speak naturally in daily and work situations.",
        "speaking.fluency",
        40,
    ),
    LearningDimensionSpec(
        "vocabulary",
        "Vocabulary",
        "Use high-frequency words accurately and idiomatically.",
        "vocabulary.usage",
        50,
    ),
    LearningDimensionSpec(
        "grammar",
        "Grammar",
        "Use grammar accurately in real communication.",
        "grammar.accuracy",
        60,
    ),
)


GENERAL_SKILLS = (
    SkillNodeSpec("listening.gist", "listening", "Daily conversation", "Follow everyday spoken exchanges and key messages.", order=10),
    SkillNodeSpec("listening.workplace", "listening", "Workplace listening", "Handle calls, meetings and instructions in English.", order=20),
    SkillNodeSpec("reading.comprehension", "reading", "Document comprehension", "Understand emails, notices and short articles.", order=10),
    SkillNodeSpec("reading.inference", "reading", "Inference and tone", "Read between the lines for intent and attitude.", order=20),
    SkillNodeSpec("writing.expression", "writing", "Clear expression", "Get ideas across clearly in everyday writing.", order=10),
    SkillNodeSpec("writing.organization", "writing", "Organization", "Structure messages and paragraphs coherently.", order=20),
    SkillNodeSpec("writing.revision", "writing", "Self-revision", "Find and fix your own writing mistakes.", order=30),
    SkillNodeSpec("speaking.fluency", "speaking", "Fluency", "Keep conversations going without long pauses.", order=10),
    SkillNodeSpec("speaking.clarity", "speaking", "Pronunciation clarity", "Be understood through clear sound and stress.", order=20),
    SkillNodeSpec("vocabulary.usage", "vocabulary", "Word usage", "Use everyday vocabulary precisely.", order=10),
    SkillNodeSpec("vocabulary.collocation", "vocabulary", "Collocation", "Combine words the way native speakers do.", order=20),
    SkillNodeSpec("grammar.accuracy", "grammar", "Sentence accuracy", "Use correct sentence structure.", order=10),
    SkillNodeSpec("grammar.tense", "grammar", "Tense and modality", "Express time and possibility accurately.", order=20),
)


GENERAL_EVIDENCE_MAPPINGS = (
    EvidenceSkillMapping("listening", "evidence_kind", ("daily", "conversation"), "listening.gist"),
    EvidenceSkillMapping("listening", "evidence_kind", ("work", "meeting", "call", "phone"), "listening.workplace"),
    EvidenceSkillMapping("reading", "evidence_kind", ("email", "notice", "article", "document"), "reading.comprehension"),
    EvidenceSkillMapping("reading", "evidence_kind", ("intent", "tone", "inference"), "reading.inference"),
    EvidenceSkillMapping("writing", "criterion", ("clarity", "clear", "understandable"), "writing.expression"),
    EvidenceSkillMapping("writing", "criterion", ("organization", "coherence", "structure"), "writing.organization"),
    EvidenceSkillMapping("writing", "criterion", ("revision", "correct"), "writing.revision"),
    EvidenceSkillMapping("speaking", "criterion", ("fluency", "flow"), "speaking.fluency"),
    EvidenceSkillMapping("speaking", "criterion", ("pronunciation", "clarity"), "speaking.clarity"),
    EvidenceSkillMapping("vocabulary", "evidence_kind", ("usage", "word choice"), "vocabulary.usage"),
    EvidenceSkillMapping("vocabulary", "evidence_kind", ("collocation", "phrasal"), "vocabulary.collocation"),
    EvidenceSkillMapping("grammar", "evidence_kind", ("sentence", "structure"), "grammar.accuracy"),
    EvidenceSkillMapping("grammar", "evidence_kind", ("tense", "modality"), "grammar.tense"),
)


GENERAL_ENGLISH_PACK = DomainPackSpec(
    track_id=GENERAL_TRACK_ID,
    title="General English",
    short_title="English",
    description="Daily and workplace English learning across the four skills plus vocabulary and grammar.",
    language="en",
    status="active",
    teaching_policy_id="general-english-policy@1",
    assessment_scale=AssessmentScaleSpec("cefr", "CEFR", 1.0, 6.0, 1.0),
    dimensions=GENERAL_DIMENSIONS,
    skills=GENERAL_SKILLS,
    capabilities=GENERAL_CAPABILITIES,
    evidence_mappings=GENERAL_EVIDENCE_MAPPINGS,
)


DOMAIN_PACKS = {
    IELTS_ACADEMIC_PACK.track_id: IELTS_ACADEMIC_PACK,
    GENERAL_ENGLISH_PACK.track_id: GENERAL_ENGLISH_PACK,
}


def get_domain_pack(track_id: str = DEFAULT_TRACK_ID) -> DomainPackSpec:
    try:
        return DOMAIN_PACKS[track_id]
    except KeyError as exc:
        raise ValueError(f"Unknown learning track: {track_id}") from exc


def domain_pack_descriptors(
    *,
    include_capabilities: bool = True,
    include_skills: bool = False,
) -> list[dict[str, object]]:
    return [
        pack.descriptor(
            include_capabilities=include_capabilities,
            include_skills=include_skills,
        )
        for pack in DOMAIN_PACKS.values()
        if pack.status != "disabled"
    ]


def all_capabilities() -> tuple[tuple[str, CapabilitySpec], ...]:
    return tuple(
        (pack.track_id, capability)
        for pack in DOMAIN_PACKS.values()
        for capability in pack.capabilities
    )


def _validate_registry() -> None:
    capability_ids: set[str] = set()
    contracts: set[str] = set()
    for pack in DOMAIN_PACKS.values():
        dimension_ids = {item.dimension_id for item in pack.dimensions}
        skill_ids = {item.skill_id for item in pack.skills}
        if len(skill_ids) != len(pack.skills):
            raise RuntimeError(f"Duplicate skill IDs in learning track {pack.track_id}")
        for dimension in pack.dimensions:
            if dimension.default_skill_id not in skill_ids:
                raise RuntimeError(
                    f"Missing default skill {dimension.default_skill_id} in {pack.track_id}"
                )
        for skill in pack.skills:
            if skill.dimension_id not in dimension_ids:
                raise RuntimeError(
                    f"Skill {skill.skill_id} uses unknown dimension {skill.dimension_id}"
                )
            if skill.parent_skill_id and skill.parent_skill_id not in skill_ids:
                raise RuntimeError(
                    f"Skill {skill.skill_id} uses unknown parent {skill.parent_skill_id}"
                )
        for mapping in pack.evidence_mappings:
            if mapping.dimension_id not in dimension_ids or mapping.skill_id not in skill_ids:
                raise RuntimeError(f"Invalid evidence mapping in {pack.track_id}")
        for capability in pack.capabilities:
            if capability.capability_id in capability_ids:
                raise RuntimeError(f"Duplicate Capability ID: {capability.capability_id}")
            if capability.output_contract in contracts:
                raise RuntimeError(
                    f"Duplicate Capability contract: {capability.output_contract}"
                )
            capability_ids.add(capability.capability_id)
            contracts.add(capability.output_contract)


_validate_registry()
