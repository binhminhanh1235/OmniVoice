#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Project Studio launcher with persistent section-level resume checkpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.cli import project_studio as studio_module
from omnivoice.cli import project_studio_live as live_module
from omnivoice.cli import project_studio_plus as plus_module
from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.project import OmniVoiceProject
from omnivoice.section_status import (
    ensure_section_status,
    incomplete_section_ids,
    restore_section_status,
    set_section_status,
    write_section_status,
)


class SectionResumeProjectStudioController(ProjectStudioController):
    """Project Studio controller backed by ``section-status.json`` checkpoints."""

    def create_project(
        self,
        script: str,
        *,
        overwrite: bool = False,
    ) -> OmniVoiceProject:
        project = super().create_project(script, overwrite=overwrite)
        ensure_section_status(project)
        return project

    def load_project(self, project_path: str | Path) -> OmniVoiceProject:
        project = super().load_project(project_path)
        ensure_section_status(project)
        restore_section_status(project, sync_manifest=True)
        return project

    def generate(
        self,
        project_path: str | Path,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        section_ids: Optional[Iterable[str]] = None,
        resume: bool = True,
        strict: bool = False,
    ) -> OmniVoiceProject:
        project = self.load_project(project_path)
        requested = (
            [item.upper() for item in section_ids]
            if section_ids is not None
            else [section.id for section in project.manifest.sections]
        )
        targets = incomplete_section_ids(project, requested) if resume else requested

        # Nothing to synthesize.  Returning immediately is important after a
        # Colab restart because completed sections must never be rendered again.
        if not targets:
            write_section_status(project)
            return project

        # Queue the selected incomplete sections before expensive inference.
        # If the runtime dies here, queued is recovered to pending on next load.
        for section_id in targets:
            set_section_status(
                project,
                section_id,
                "queued",
                save_manifest=False,
            )
        project.save()
        write_section_status(project)

        try:
            generated = super().generate(
                project.root,
                voice_name=voice_name,
                voice_variant=voice_variant,
                language=language,
                section_ids=targets,
                resume=resume,
                strict=strict,
            )
        except Exception:
            # Preserve whatever chunk/project checkpoints were successfully
            # written before the failure.  Queued/generating sections are
            # deliberately recoverable as pending on the next load.
            try:
                failed = super().load_project(project.root)
                write_section_status(failed)
            except Exception:
                pass
            raise

        write_section_status(generated)
        return generated

    def regenerate_chunk(
        self,
        project_path: str | Path,
        chunk_choice: str,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        strict: bool = False,
    ) -> OmniVoiceProject:
        project = super().regenerate_chunk(
            project_path,
            chunk_choice,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            strict=strict,
        )
        write_section_status(project)
        return project


def _install_resume_controller() -> None:
    """Inject the resume-aware controller into the existing Studio builders."""

    studio_module.ProjectStudioController = SectionResumeProjectStudioController
    live_module.ProjectStudioController = SectionResumeProjectStudioController
    plus_module.ProjectStudioController = SectionResumeProjectStudioController


def build_demo(model: Any, workspace: str | Path):
    _install_resume_controller()
    return live_module.build_demo(model, workspace)


def main(argv=None) -> int:
    _install_resume_controller()
    return live_module.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
