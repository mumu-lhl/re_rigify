"""Blender Extension entry point."""

from .re_rigify import bl_info, register, unregister

__all__ = ("bl_info", "register", "unregister")
