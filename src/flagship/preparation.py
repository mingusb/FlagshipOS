"""Build bundled toolkit recipes before exposing their files through Distrobox."""

import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import tempfile

from . import cli as core


def load_recipe(profile):
    if not isinstance(profile, str) or not core.NAME_RE.fullmatch(profile):
        raise core.CommandError("Invalid profile name.", 2)
    resource = files("flagship").joinpath("recipes", f"{profile}.Containerfile")
    try:
        recipe = resource.read_bytes()
    except FileNotFoundError as exc:
        raise core.CommandError(f"No bundled build recipe for {profile}. Import its verified full root filesystem instead.") from exc
    if not recipe.strip():
        raise core.CommandError(f"The bundled recipe for {profile} is empty.")
    return recipe


def recipe_tag(profile, digest):
    return f"localhost/flagship/{profile}:recipe-{digest}"


def build_argv(profile, digest, context):
    return ["podman", "build", "--tag", recipe_tag(profile, digest),
            "--iidfile", str(context / "image-id"),
            "--file", str(context / "Containerfile"), str(context)]


def built_image(context):
    try:
        value = (context / "image-id").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise core.CommandError("Build did not produce a valid immutable image ID.") from exc
    if re.fullmatch(r"[a-f0-9]{64}", value):
        value = "sha256:" + value
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise core.CommandError("Build did not produce a valid immutable image ID.")
    image = core.image_identity(value, registry=False)
    if image != value:
        raise core.CommandError("Built image inspection does not match the build receipt.")
    return image


def prepare(ctx, profile, recipe):
    if core.inspect_container(f"flagship-{profile}") is not None:
        raise core.CommandError(f"Remove the existing flagship-{profile} container before preparing its replacement image.")
    digest = hashlib.sha256(recipe).hexdigest()
    tag = recipe_tag(profile, digest)
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=ctx.state_dir) as temporary:
        context = Path(temporary)
        recipe_path = context / "Containerfile"
        recipe_path.write_bytes(recipe)
        recipe_path.chmod(0o600)
        core.checked_stream(build_argv(profile, digest, context))
        image = built_image(context)
    install = core.installation(ctx, create=True)
    core.atomic_json(ctx.record_path(profile), {
        "schema_version": 1, "profile": profile, "container": f"flagship-{profile}",
        "installation_id": install["installation_id"], "imported_image": image,
        "recipe_sha256": digest, "build_tag": tag, "status": "prepared"})
    print(f"Prepared {profile}: {image} (recipe SHA-256 {digest})")
    return 0


def main(ctx, profile):
    recipe = load_recipe(profile)
    if ctx.dry_run:
        digest = hashlib.sha256(recipe).hexdigest()
        print(json.dumps({"profile": profile, "recipe_sha256": digest,
                          "steps": [{"argv": build_argv(profile, digest, Path("${private_build_context}"))}],
                          "notes": ["Planning only: no commands, files or state changes.",
                                    "Copy only the bundled recipe into a private context; reject an existing container.",
                                    "After a successful build, inspect and record the immutable image ID."]}, indent=2))
        return 0
    core.require_runtime(build=True)
    with core.state_lock(ctx):
        return prepare(ctx, profile, recipe)
