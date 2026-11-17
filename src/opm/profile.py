# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Profile support for opm.

Profiles are reusable packages of templates, CSS, JavaScript, and configuration
that can be shared across multiple opm projects. They are inspired by jinks'
profile system but adapted for opm's static site generation model.

A profile is a directory containing:
- opm-profile.toml: Profile metadata and configuration
- templates/: Template files (.tpl)
- assets/: CSS, JavaScript, and other static assets
- README.md: Documentation

Profiles can be loaded from:
1. The project's local profiles/ directory
2. ~/.opm/profiles/ (user profiles)
3. Bundled profiles in opm.resources.profiles
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opm.template_frontmatter import merge_deep


# Default locations to search for profiles, in order of precedence
PROFILE_LOCATIONS = [
    # Project-local profiles
    Path("profiles"),
    # User profiles
    Path.home() / ".opm" / "profiles",
]


@dataclass
class ProfileConfig:
    """Configuration for a single profile.
    
    Loaded from opm-profile.toml in the profile directory.
    """
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    
    # Templates to include via 'use' directive
    templates: list[str] = field(default_factory=list)
    
    # Assets to copy to the output
    assets: list[str] = field(default_factory=list)
    
    # Configuration defaults to merge into project config
    config: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_path(cls, profile_path: Path) -> ProfileConfig:
        """Load a profile from its directory."""
        profile_file = profile_path / "opm-profile.toml"
        if not profile_file.is_file():
            raise FileNotFoundError(
                f"Profile {profile_path} is missing required opm-profile.toml"
            )
        
        with open(profile_file, "rb") as f:
            data = tomllib.load(f)
        
        # Extract known fields
        config_data = {}
        known_fields = {
            'name', 'version', 'description', 'author', 
            'templates', 'assets'
        }
        
        for key in known_fields:
            if key in data:
                config_data[key] = data[key]
        
        # Handle config: can be provided as [config] or individual top-level keys
        # Build the config dict from [config] section, plus handle [context] at top level
        profile_config = {}
        if 'config' in data:
            profile_config.update(data['config'])
        # Also check for top-level [context] and merge into config.context
        if 'context' in data:
            profile_config.setdefault('context', {}).update(data['context'])
        
        if profile_config:
            config_data['config'] = profile_config
        
        # Ensure name is set
        if 'name' not in config_data:
            config_data['name'] = profile_path.name
        
        return cls(**config_data)


def find_profile(profile_name: str, search_paths: list[Path] | None = None) -> Path:
    """Find a profile by name in the search paths.
    
    Args:
        profile_name: Name of the profile to find
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        Path to the profile directory
        
    Raises:
        FileNotFoundError: If the profile is not found in any search path
    """
    if search_paths is None:
        search_paths = PROFILE_LOCATIONS
    
    for base_path in search_paths:
        profile_path = base_path / profile_name
        if profile_path.is_dir():
            return profile_path
    
    raise FileNotFoundError(
        f"Profile '{profile_name}' not found in any of: "
        f"{', '.join(str(p) for p in search_paths)}"
    )


def load_profile(profile_name: str, search_paths: list[Path] | None = None) -> ProfileConfig:
    """Load a profile by name.
    
    Args:
        profile_name: Name of the profile to load
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        ProfileConfig for the profile
    """
    profile_path = find_profile(profile_name, search_paths)
    return ProfileConfig.from_path(profile_path)


def load_profiles(profile_names: list[str], search_paths: list[Path] | None = None) -> list[ProfileConfig]:
    """Load multiple profiles by name.
    
    Args:
        profile_names: List of profile names to load
        search_paths: List of paths to search (defaults to PROFILE_LOCATIONS)
        
    Returns:
        List of ProfileConfig objects
    """
    profiles = []
    for name in profile_names:
        profiles.append(load_profile(name, search_paths))
    return profiles


def get_profile_paths(profile_config: ProfileConfig, profile_path: Path) -> tuple[Path, ...]:
    """Get the full paths for a profile's assets.
    
    Args:
        profile_config: The profile configuration
        profile_path: Path to the profile directory
        
    Returns:
        Tuple of absolute paths to the profile's assets
    """
    assets = []
    for asset_pattern in profile_config.assets:
        asset_path = profile_path / asset_pattern
        if asset_path.is_file():
            assets.append(asset_path.resolve())
        elif asset_path.is_dir():
            # For directories, include all files recursively
            assets.extend(p.resolve() for p in asset_path.rglob("*") if p.is_file())
    return tuple(assets)


def merge_profile_configs(
    base_config: dict[str, Any],
    profile_configs: list[ProfileConfig]
) -> dict[str, Any]:
    """Merge configuration from multiple profiles into a base configuration.
    
    Profile configurations are merged in order, with later profiles overriding
    earlier ones. Each profile's config is merged deeply with the base.
    
    Args:
        base_config: Base configuration to merge into
        profile_configs: List of profile configurations to merge
        
    Returns:
        Merged configuration dictionary
    """
    merged = base_config.copy()
    for profile in profile_configs:
        merged = merge_deep(merged, profile.config)
    return merged
