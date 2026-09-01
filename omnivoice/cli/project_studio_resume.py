#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Project Studio launcher with persistent section resume and version history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.cli import project_studio as studio_module
from omnivoice.cli import project_studio_live as live_module
from omnivoice.cli import project_studio_plus as plus_module
from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.cli.section_history_ui import build_section_history_demo
from omnivoice.project import OmniVoiceProject
from omnivoice.section_history import (
    SectionVersion,
    create_section_snapshot,
    list_section_versions,
    restore_section_version,
    section_version_audio,
)
from omnivoice.section_status import (
    ensure_section_status,
    incomplete_section_ids,
    restore_section_status,
    set_section_status,
    write_section_status,
)


class SectionResumeProjectStudioController(ProjectStudioController):
    """Project Studio controller backed by section checkpoints and history."""

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

        if not resume:
            for section_id in targets:
                create_section_snapshot(
                    project,
                    section_id,
                    reason="before forced section regeneration",
                )

        if not targets:
            write_section_status(project)
            return project

        for section_id in targets:
            set_section_status(
                project,
                section_id,
                "queued",
                save_manifest=False,
            )
        project.save()

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
        if not chunk_choice or "/" not in chunk_choice:
            raise ValueError("Select a chunk to regenerate")
        target = chunk_choice.split(" ", 1)[0]
        section_id, chunk_id = target.split("/", 1)

        project = self.load_project(project_path)
        create_section_snapshot(
            project,
            section_id,
            reason=f"before regenerating {chunk_id}",
        )
        set_section_status(
            project,
            section_id,
            "pending",
            save_manifest=False,
        )
        project.mark_chunk_for_regeneration(section_id, chunk_id)

        generated = self.generate(
            project.root,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            section_ids=[section_id],
            resume=True,
            strict=strict,
        )
        write_section_status(generated)
        return generated

    def section_versions(
        self,
        project_path: str | Path,
        section_id: str,
    ) -> list[SectionVersion]:
        project = self.load_project(project_path)
        return list_section_versions(project, section_id)

    def snapshot_section(
        self,
        project_path: str | Path,
        section_id: str,
        *,
        reason: str = "manual snapshot",
    ) -> Optional[SectionVersion]:
        project = self.load_project(project_path)
        return create_section_snapshot(project, section_id, reason=reason)

    def section_version_audio(
        self,
        project_path: str | Path,
        section_id: str,
        version_id: str,
    ) -> Path:
        project = self.load_project(project_path)
        return section_version_audio(project, section_id, version_id)

    def restore_section_version(
        self,
        project_path: str | Path,
        section_id: str,
        version_id: str,
        *,
        snapshot_current: bool = True,
    ) -> OmniVoiceProject:
        project = self.load_project(project_path)
        restore_section_version(
            project,
            section_id,
            version_id,
            snapshot_current=snapshot_current,
        )
        return self.load_project(project.root)


def _install_resume_controller() -> None:
    """Inject the resume/history-aware controller into existing Studio builders."""

    studio_module.ProjectStudioController = SectionResumeProjectStudioController
    live_module.ProjectStudioController = SectionResumeProjectStudioController
    plus_module.ProjectStudioController = SectionResumeProjectStudioController


def build_demo(model: Any, workspace: str | Path):
    import gradio as gr

    _install_resume_controller()
    studio = live_module.build_demo(model, workspace)
    history = build_section_history_demo(
        model,
        workspace,
        controller_cls=SectionResumeProjectStudioController,
    )
    return gr.TabbedInterface(
        [studio, history],
        ["Studio", "Section History"],
        title="OmniVoice Project Studio",
    )


def main(argv=None) -> int:
    _install_resume_controller()
    return live_module.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
