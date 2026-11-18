"""Reconcile supported Nextcloud majors with stable CalenAI archives and GHCR."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

SCHEDULE = "https://raw.githubusercontent.com/wiki/nextcloud/server/Maintenance-and-Release-Schedule.md"
PACKAGE = "users/ajctrl/packages/container/nextcloud-calenai/versions"
VARIANTS = {"apache": "-apache", "fpm": "-fpm", "fpm-alpine": ""}
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+"
MANAGED = re.compile(
    rf"([1-9][0-9]*)(?:-(?:apache|fpm(?:-alpine)?)|"
    rf"-calenai-{VERSION}(?:-apache|-fpm)?(?:-r[0-9]+|-b[a-f0-9]{{64}})?)?"
)


def get(url):
    return subprocess.check_output(["curl", "-fsSL", "--retry", "3", url])


def pages(endpoint):
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", endpoint + "?per_page=100"],
                            capture_output=True)
    if result.returncode:
        if endpoint == PACKAGE and b"(HTTP 404)" in result.stderr:
            return []
        raise RuntimeError(result.stderr.decode())
    return [item for page in json.loads(result.stdout) for item in page]


def support(schedule):
    def rows(title):
        sections = re.findall(rf"^## {title}[ \t]*\n(.*?)(?=^## |\Z)", schedule, re.M | re.S)
        if len(sections) != 1:
            raise ValueError(f"Expected one schedule section for {title}")
        table = {}
        for line in sections[0].splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells[0] == "Version code" or re.fullmatch(r":?-+:?", cells[0]):
                continue
            major = int(cells[0].strip("*"))
            if major in table or len(cells) < 5:
                raise ValueError(f"Invalid schedule row for {major}")
            table[major] = cells
        if not table:
            raise ValueError(f"Empty schedule table for {title}")
        return table

    patches = {}
    for major, cells in rows("Currently supported versions").items():
        match = re.match(rf"\**({VERSION})\**(?:\s|$)", cells[4])
        if not match or int(match[1].split(".")[0]) != major:
            raise ValueError(f"Missing stable patch for {major}")
        patches[major] = tuple(map(int, match[1].split(".")))
    ended = set(rows("EOL Versions"))
    if max(ended) >= min(patches):
        raise ValueError("Inconsistent supported and EOL majors")
    return patches, ended


def compatible_releases(active, releases):
    selected = {}
    stable = []
    for release in releases:
        match = re.fullmatch(rf"v({VERSION})", release["tag_name"])
        if match and not release["draft"] and not release["prerelease"]:
            stable.append((match[1], release))
    for version, release in sorted(stable, key=lambda row: tuple(map(int, row[0].split("."))), reverse=True):
        name = f"calenai-{version}.tar.gz"
        assets = [a for a in release["assets"] if a["name"] == name and a["state"] == "uploaded"]
        if not assets:
            continue
        asset, = assets
        archive = get(asset["browser_download_url"])
        checksum = hashlib.sha256(archive).hexdigest()
        if asset["digest"] != "sha256:" + checksum:
            raise ValueError(f"Invalid digest for {name}")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            manifest = ET.parse(tar.extractfile("calenai/appinfo/info.xml")).getroot()
        if manifest.findtext("id") != "calenai" or manifest.findtext("version", "").strip() != version:
            raise ValueError(f"Unexpected manifest in {name}")
        dep = manifest.find("dependencies/nextcloud")
        if dep is None:
            raise ValueError(f"Missing Nextcloud dependency in {name}")
        low, high = (tuple(map(int, dep.attrib[k].split("."))) for k in ("min-version", "max-version"))
        for target in active.keys() - selected.keys():
            patch = active[target]
            if low <= patch[:len(low)] and patch[:len(high)] <= high:
                selected[target] = (version, checksum)
        if selected.keys() == active.keys():
            break
    return selected


def tags_of(item):
    return item["metadata"]["container"]["tags"]


def expired(item, ended):
    tags = tags_of(item)
    return bool(tags) and all((m := MANAGED.fullmatch(t)) and int(m[1]) in ended for t in tags)


def base_image(major, base):
    tag = f"{major}-{base}"
    result = subprocess.run(["docker", "buildx", "imagetools", "inspect", "--raw", "docker.io/library/nextcloud:" + tag],
                            capture_output=True)
    if result.returncode:
        if b"manifest unknown" in result.stderr.lower() or f"nextcloud:{tag}: not found".encode() in result.stderr:
            return None
        raise RuntimeError(result.stderr.decode())
    entries = json.loads(result.stdout)["manifests"]
    entry, = [entry for entry in entries if entry["platform"]["os"] == "linux"
              and entry["platform"]["architecture"] == "amd64"]
    digest = entry["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid base digest for {tag}")
    version = entry["annotations"]["org.opencontainers.image.version"]
    match = re.fullmatch(rf"({VERSION})(?:-{base})?", version)
    if not match or int(match[1].split(".")[0]) != major:
        raise ValueError(f"Unexpected version {version} for {tag}")
    return digest, tuple(map(int, match[1].split(".")))


@lru_cache(maxsize=None)
def published_core(digest):
    image = "ghcr.io/ajctrl/nextcloud-calenai@" + digest
    config = subprocess.check_output(["docker", "buildx", "imagetools", "inspect", image,
                                      "--format", "{{json .Image.Config.Env}}"])
    versions = [v for v in json.loads(config) if v.startswith("NEXTCLOUD_VERSION=")]
    if len(versions) == 1:
        match = re.fullmatch(rf"NEXTCLOUD_VERSION=({VERSION})", versions[0])
        if match:
            return tuple(map(int, match[1].split(".")))
    return None


def can_update_core(alias, core, published):
    if alias not in published:
        return True
    current = published_core(published[alias])
    if current is None or current[0] != core[0] or core < current:
        print(f"Keeping {alias}: cannot verify a forward Nextcloud update", file=sys.stderr)
        return False
    return True


def can_promote(rolling, major, suffix, candidate, core, published):
    pattern = re.compile(rf"{major}-calenai-({VERSION}){suffix}(?:-r[0-9]+|-b[a-f0-9]{{64}})?")
    candidate_version = tuple(map(int, candidate.split(".")))
    for alias in rolling:
        if alias not in published:
            continue
        versions = {tuple(map(int, match[1].split("."))) for tag, digest in published.items()
                    if digest == published[alias] and (match := pattern.fullmatch(tag))}
        if len(versions) != 1 or max(versions) > candidate_version:
            print(f"Keeping {alias}: cannot verify a forward update to {candidate}", file=sys.stderr)
            return False
        if not can_update_core(alias, core, published):
            return False
    return True


def plan(active, releases, published, variants=VARIANTS):
    jobs = []
    images = {}
    for major in active:
        for base in variants:
            image = base_image(major, base)
            if image is not None:
                images[major, base] = image
    patches = {target: image[1] for target, image in images.items()}
    selected = compatible_releases(patches, releases)
    for major, base in images.keys() - selected.keys():
        print(f"No compatible CalenAI release for nextcloud:{major}-{base}", file=sys.stderr)
    recipe = [hashlib.sha256(Path(p).read_bytes()).hexdigest()
              for p in ("Dockerfile", "hooks/update-calenai.sh")]
    for (major, base), (version, checksum) in sorted(selected.items()):
        digest, core = images[major, base]
        base_tag = f"{major}-{base}"
        suffix = VARIANTS[base]
        fixed = f"{major}-calenai-{version}{suffix}"
        key = hashlib.sha256(" ".join([digest, checksum, *recipe]).encode()).hexdigest()
        revision = f"{fixed}-b{key}"
        rolling = [base_tag]
        if base == "apache":
            rolling.append(str(major))
        aliases = [fixed] if can_update_core(fixed, core, published) else []
        if can_promote(rolling, major, suffix, version, core, published):
            aliases.extend(rolling)
        pending = [t for t in aliases if revision not in published or published.get(t) != published[revision]]
        if pending:
            jobs.append(dict(major=major, base=base, version=version, checksum=checksum,
                             source=f"nextcloud@{digest}", revision=revision,
                             build=revision not in published, aliases=pending))
    return jobs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--check", nargs=3, metavar=("MAJOR", "BASE", "REVISION"))
    args = parser.parse_args()
    active, ended = support(get(SCHEDULE).decode())
    if args.cleanup:
        failed = []
        for item in pages(PACKAGE):
            if not expired(item, ended):
                continue
            version_id = int(item["id"])
            endpoint = f"{PACKAGE}/{version_id}"
            try:
                current = json.loads(subprocess.check_output(["gh", "api", endpoint]))
                if expired(current, ended):
                    print("Removing EOL tags", *tags_of(current), flush=True)
                    subprocess.run(["gh", "api", "-X", "DELETE", endpoint], check=True)
            except subprocess.CalledProcessError:
                print(f"EOL cleanup failed for version {version_id} ({', '.join(tags_of(item))})",
                      file=sys.stderr)
                failed.append(str(version_id))
        if failed:
            sys.exit("EOL cleanup failed for version IDs: " + ", ".join(failed))
        return
    if args.check:
        major, base, revision = args.check
        if int(major) not in active:
            print("[]")
            return
        active = {int(major): active[int(major)]}
    releases = pages("repos/ajctrl/CalenAI/releases")
    published = {tag: item["name"] for item in pages(PACKAGE) for tag in tags_of(item)}
    jobs = plan(active, releases, published, [base] if args.check else VARIANTS)
    if args.check:
        aliases = next((job["aliases"] for job in jobs if job["revision"] == revision), [])
        print(json.dumps(aliases))
        return
    print("jobs=" + json.dumps(jobs, separators=(",", ":")))


if __name__ == "__main__":
    main()
