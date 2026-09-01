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
from omnivoice.robust_longform import (
    RobustLongFormConfig,
    RobustLongFormGenerator,
    RobustLongFormResult,
    generate_robust_longform,
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
    "OmniVoiceProject",
    "ProjectManifest",
    "ProjectSection",
    "ProjectBeat",
    "ProjectChunk",
    "StyleProfile",
    "OmniVoiceStyleResolver",
    "DEFAULT_STYLE_PROFILES",
    "parse_project_script",
    "SECTION_STATUS_NAME",
    "SectionStatusRestore",
    "ensure_section_status",
    "restore_section_status",
    "write_section_status",
    "set_section_status",
    "section_is_complete",
    "incomplete_section_ids",
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