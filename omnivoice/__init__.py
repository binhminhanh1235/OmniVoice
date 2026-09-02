import warnings
from importlib.metadata import PackageNotFoundError, version

warnings.filterwarnings("ignore", module="torchaudio")
warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    message="invalid escape sequence",
    module="pydub.utils",
)
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module="torch.distributed.algorithms.ddp_comm_hooks",
)

try:
    __version__ = version("omnivoice")
except PackageNotFoundError:
    __version__ = "0.0.0"

from omnivoice.models.omnivoice import (
    OmniVoice,
    OmniVoiceConfig,
    OmniVoiceGenerationConfig,
    VoiceClonePrompt,
)
from omnivoice.adaptive_quality import (
    AdaptiveChunkReport,
    AdaptiveQualityConfig,
    AdaptiveRobustLongFormGenerator,
    PacingMetrics,
    analyze_pacing,
)
from omnivoice.hardware_quality import (
    HARDWARE_SETTINGS_FILE,
    QUALITY_PRESETS,
    HardwareCapabilities,
    HardwareQualitySettings,
    HardwareQualitySettingsStore,
    QualityPresetPolicy,
    detect_hardware,
    normalize_quality_preset,
    quality_policy,
    quality_preset_rows,
)
from omnivoice.preview import (
    PreviewResult,
    PreviewTarget,
    ProjectPreviewGenerator,
    generate_project_previews,
    select_preview_targets,
)
from omnivoice.project import (
    DEFAULT_STYLE_PROFILES,
    OmniVoiceProject,
    OmniVoiceStyleResolver,
    ProjectBeat,
    ProjectChunk,
    ProjectManifest,
    ProjectSection,
    StyleProfile,
    parse_project_script,
)
from omnivoice.project_queue import (
    QUEUE_FILE_NAME,
    ProjectQueueItem,
    ProjectQueueManifest,
    ProjectQueueRunner,
    ProjectQueueStore,
    QueueEvent,
    queue_rows,
)
from omnivoice.project_status import (
    DEFAULT_QUEUE_PROJECT_STATUSES,
    PROJECT_STATUSES,
    ProjectStatusSummary,
    filter_project_statuses,
    project_status_rows,
    scan_project_statuses,
    summarize_project,
)
from omnivoice.reference_segment import (
    ReferenceSegmentCandidate,
    ReferenceSegmentConfig,
    ReferenceSegmentResult,
    export_reference_segment,
    find_reference_segments,
    save_reference_segment_report,
)
from omnivoice.robust_longform import (
    RobustLongFormConfig,
    RobustLongFormGenerator,
    RobustLongFormResult,
    generate_robust_longform,
)
from omnivoice.runtime_workspace import (
    RuntimeWorkspace,
    default_execution_workspace,
    detect_runtime_environment,
    detect_runtime_workspace,
    ensure_runtime_workspace,
)
from omnivoice.services.studio_service import StudioService
from omnivoice.server.app import create_studio_app
from omnivoice.section_history import (
    HISTORY_DIR_NAME,
    HISTORY_INDEX_NAME,
    SectionVersion,
    create_section_snapshot,
    list_section_versions,
    restore_section_version,
    section_version_audio,
)
from omnivoice.section_status import (
    SECTION_STATUS_NAME,
    SectionStatusRestore,
    ensure_section_status,
    incomplete_section_ids,
    restore_section_status,
    section_is_complete,
    set_section_status,
    write_section_status,
)
from omnivoice.style_bank import (
    StyleBankProjectRunner,
    generate_project_with_style_bank,
)
from omnivoice.voice_doctor import (
    VoiceDoctorConfig,
    VoiceDoctorReport,
    analyze_voice_reference,
)
from omnivoice.voice_stability import (
    DEFAULT_STABILITY_TEXTS,
    VoiceStabilityConfig,
    VoiceStabilityReport,
    VoiceStabilitySample,
    evaluate_voice_stability,
)
from omnivoice.voice_library import (
    STYLE_VARIANT_FALLBACKS,
    VoiceEntry,
    VoiceLibrary,
    VoicePromptResolution,
    VoiceVariant,
)

__all__ = [
    "OmniVoice",
    "OmniVoiceConfig",
    "OmniVoiceGenerationConfig",
    "VoiceClonePrompt",
    "RobustLongFormConfig",
    "RobustLongFormGenerator",
    "RobustLongFormResult",
    "generate_robust_longform",
    "AdaptiveQualityConfig",
    "AdaptiveRobustLongFormGenerator",
    "AdaptiveChunkReport",
    "PacingMetrics",
    "analyze_pacing",
    "QUALITY_PRESETS",
    "HARDWARE_SETTINGS_FILE",
    "HardwareCapabilities",
    "QualityPresetPolicy",
    "HardwareQualitySettings",
    "HardwareQualitySettingsStore",
    "detect_hardware",
    "normalize_quality_preset",
    "quality_policy",
    "quality_preset_rows",
    "RuntimeWorkspace",
    "detect_runtime_environment",
    "detect_runtime_workspace",
    "default_execution_workspace",
    "ensure_runtime_workspace",
    "StudioService",
    "create_studio_app",
    "OmniVoiceProject",
    "ProjectManifest",
    "ProjectSection",
    "ProjectBeat",
    "ProjectChunk",
    "StyleProfile",
    "OmniVoiceStyleResolver",
    "DEFAULT_STYLE_PROFILES",
    "parse_project_script",
    "QUEUE_FILE_NAME",
    "ProjectQueueItem",
    "ProjectQueueManifest",
    "ProjectQueueStore",
    "ProjectQueueRunner",
    "QueueEvent",
    "queue_rows",
    "PROJECT_STATUSES",
    "DEFAULT_QUEUE_PROJECT_STATUSES",
    "ProjectStatusSummary",
    "summarize_project",
    "scan_project_statuses",
    "filter_project_statuses",
    "project_status_rows",
    "ReferenceSegmentConfig",
    "ReferenceSegmentCandidate",
    "ReferenceSegmentResult",
    "find_reference_segments",
    "export_reference_segment",
    "save_reference_segment_report",
    "SECTION_STATUS_NAME",
    "SectionStatusRestore",
    "ensure_section_status",
    "restore_section_status",
    "write_section_status",
    "set_section_status",
    "section_is_complete",
    "incomplete_section_ids",
    "HISTORY_DIR_NAME",
    "HISTORY_INDEX_NAME",
    "SectionVersion",
    "create_section_snapshot",
    "list_section_versions",
    "restore_section_version",
    "section_version_audio",
    "VoiceLibrary",
    "VoiceEntry",
    "VoiceVariant",
    "VoicePromptResolution",
    "STYLE_VARIANT_FALLBACKS",
    "VoiceDoctorConfig",
    "VoiceDoctorReport",
    "analyze_voice_reference",
    "DEFAULT_STABILITY_TEXTS",
    "VoiceStabilityConfig",
    "VoiceStabilitySample",
    "VoiceStabilityReport",
    "evaluate_voice_stability",
    "StyleBankProjectRunner",
    "generate_project_with_style_bank",
    "PreviewTarget",
    "PreviewResult",
    "ProjectPreviewGenerator",
    "select_preview_targets",
    "generate_project_previews",
]
