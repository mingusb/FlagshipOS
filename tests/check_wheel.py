"""Check the built artifact rather than trusting source-tree resource loading."""

import json
import sys
from pathlib import Path
from zipfile import ZipFile


def main():
    wheels = list(Path(sys.argv[1]).glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one wheel, found {len(wheels)}")
    with ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        catalogs = [name for name in names if name.endswith("/profiles.json")]
        if len(catalogs) != 1:
            raise SystemExit("Wheel must contain exactly one bundled profiles.json")
        catalog = json.loads(wheel.read(catalogs[0]))
        profiles = catalog.get("profiles", catalog)
        if isinstance(profiles, list):
            ids = {profile["id"] for profile in profiles}
        else:
            ids = set(profiles)
        required = {"kali", "parrot", "backbox", "remnux", "caine", "tsurugi", "sift"}
        if ids != required:
            raise SystemExit(f"Incomplete distribution catalog: {sorted(ids)}")
        recipe_profiles = {"kali", "parrot", "backbox", "remnux", "sift"}
        for profile in recipe_profiles:
            recipe = f"flagship/recipes/{profile}.Containerfile"
            if recipe not in names or not wheel.read(recipe).strip():
                raise SystemExit(f"Wheel lacks the bundled full-install recipe: {profile}")
        if not any(name.endswith("/entry_points.txt") for name in names):
            raise SystemExit("Wheel has no console entry point metadata")
        entries = "\n".join(
            wheel.read(name).decode("utf-8")
            for name in names
            if name.endswith("/entry_points.txt")
        )
        if "flagship = flagship.cli:main" not in entries:
            raise SystemExit("Wheel lacks the flagship CLI entry point")
        if "flagship/mcp_server.py" not in names:
            raise SystemExit("Wheel lacks the optional MCP implementation")
        metadata = "\n".join(wheel.read(name).decode("utf-8") for name in names if name.endswith("/METADATA"))
        if 'Provides-Extra: mcp' not in metadata or 'mcp==2.3.0' not in metadata:
            raise SystemExit("Wheel lacks the pinned optional MCP dependency")
    print(f"Verified {wheels[0].name}: seven profiles, five build recipes and the flagship entry point")


if __name__ == "__main__":
    main()
