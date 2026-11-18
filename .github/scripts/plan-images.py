"""Plan GHCR builds and alias repairs for stable CalenAI releases."""
import hashlib
import json
import os
import re
import subprocess
import sys
from functools import lru_cache


def read_pages(path):
    with open(path) as stream:
        return [item for page in json.load(stream) for item in page]


def version_key(version):
    return tuple(map(int, version.split(".")))


def stable_versions(releases):
    versions = set()
    for release in releases:
        match = re.fullmatch(r"v([0-9]+\.[0-9]+\.[0-9]+)", release["tag_name"])
        if release["draft"] or release["prerelease"]:
            continue
        if match and version_key(match[1]) >= (1, 2, 7):
            versions.add(match[1])
    return sorted(versions, key=version_key, reverse=True)


def registry_digests():
    repository = "docker://ghcr.io/ajctrl/nextcloud-calenai"
    result = subprocess.run(["skopeo", "list-tags", repository], capture_output=True, text=True)
    if result.returncode:
        # A first publish has no repository yet. Authentication and network errors must fail.
        if "name unknown" not in result.stderr.lower():
            sys.exit(result.stderr)
        tags = set()
    else:
        tags = set(json.loads(result.stdout)["Tags"] or [])

    @lru_cache(maxsize=None)
    def digest(tag):
        if tag not in tags:
            return None
        manifest = subprocess.check_output(["skopeo", "inspect", "--raw", f"{repository}:{tag}"])
        return hashlib.sha256(manifest).hexdigest()

    return digest


def plan(ordered, get_digest, requested):
    if requested is not None and requested not in ordered:
        raise ValueError(f"No matching stable release for {requested}")

    jobs = []
    for version in ([requested] if requested is not None else ordered):
        for base, suffix in (("fpm-alpine", ""), ("fpm", "-fpm"), ("apache", "-apache")):
            tag = f"35-calenai-{version}{suffix}"
            # Only images built and tested with the guarded upgrade hook get this revision tag.
            revision = tag + "-r3"
            digest = get_digest(revision)
            aliases = [tag]
            if version == ordered[0]:
                aliases.append(f"35-{base}")
                if base == "apache":
                    aliases.append("35")
            pending = [alias for alias in aliases if not digest or get_digest(alias) != digest]
            if pending:
                jobs.append({
                    "version": version,
                    "base": base,
                    "revision": revision,
                    "build": digest is None,
                    "aliases": pending,
                })
            if len(jobs) == 256:
                return jobs
    return jobs


if __name__ == "__main__":
    ordered = stable_versions(read_pages(sys.argv[1]))
    if sys.argv[2:] == ["--latest"]:
        print(ordered[0] if ordered else "")
        sys.exit(0)
    requested = None
    if os.environ["GITHUB_REF_TYPE"] == "tag":
        tag = os.environ["GITHUB_REF_NAME"]
        match = re.fullmatch(r"35-calenai-([0-9]+\.[0-9]+\.[0-9]+)(?:-r[0-9]+)?", tag)
        if match is None:
            raise ValueError(f"Invalid release tag {tag}")
        requested = match[1]
    jobs = plan(ordered, registry_digests(), requested)
    print("jobs=" + json.dumps(jobs, separators=(",", ":")))
