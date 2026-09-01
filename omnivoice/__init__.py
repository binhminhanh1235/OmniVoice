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
from omnivoice.voice_library import VoiceEntry, VoiceLibrary, VoiceVariant

__all__ = [
    "OmniVoice",
    "OmniVoiceConfig",
    "OmniVoiceGenerationConfig",
    "VoiceClonePrompt",
    "RobustLongFormConfig",
    "RobustLongFormGenerator",
    "RobustLongFormResult",
    "generate_robust_longform",
    "OmniVoiceProject",
    "ProjectManifest",
    "ProjectSection",
    "ProjectBeat",
    "ProjectChunk",
    "StyleProfile",
    "OmniVoiceStyleResolver",
    "DEFAULT_STYLE_PROFILES",
    "parse_project_script",
    "VoiceLibrary",
    "VoiceEntry",
    "VoiceVariant",
]
