"""Headless mode for rataGUI -- no Qt dependency required."""

from rataGUI.headless.runner import PipelineRunner
from rataGUI.headless.context import PipelineContext, HeadlessConfigManager

__all__ = ["PipelineRunner", "PipelineContext", "HeadlessConfigManager"]
