"""Verify operator-pinned preinstalled bytes, not submission compliance or merit.

This Linux-image inspector requires /bin/sh and /usr/bin/{timeout,readlink,sha256sum}.
These are trusted inspection prerequisites, NOT additional submitter allowances.
No missing prerequisite is installed; no image is pulled and no host path is mounted.
"""

import re
import subprocess
import threading
import time

IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PATH = re.compile(r"/(?:usr|bin|sbin|lib|lib64|opt)/[A-Za-z0-9_+@.,=:%/-]+")
MAX_OUTPUT, TIMEOUT = 256 << 10, 25
INSPECT = r"""set -eu
for requested do
    resolved=$(/usr/bin/readlink -f -- "$requested")
    case "$resolved" in
        /usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|/opt/*) ;;
        *) exit 21 ;;
    esac
    case "$resolved" in *'/../'*|*'/./'*|*'//'*) exit 22 ;; esac
    [ -f "$resolved" ] && [ ! -L "$resolved" ] || exit 23
    checksum=$(/usr/bin/sha256sum -- "$resolved")
    printf '%s\t%s\n' "$resolved" "${checksum%% *}"
done
"""


def _path(value):
    return (
        isinstance(value, str)
        and len(value) <= 1024
        and PATH.fullmatch(value)
        and not {"", ".", ".."}.intersection(value.split("/")[1:])
    )


def _run(command):
    """Bound both pipe memory and wall time, including failed Docker commands."""
    process, reader = None, None
    output = []
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def read():
            try:
                output.append(process.stdout.read(MAX_OUTPUT + 1))
            except OSError:
                pass

        reader = threading.Thread(target=read, daemon=True)
        deadline = time.monotonic() + TIMEOUT
        reader.start()
        reader.join(TIMEOUT)
        if reader.is_alive() or not output or len(output[0]) > MAX_OUTPUT:
            raise ValueError("dependency inspection timed out or exceeded output bound")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            raise ValueError("dependency inspection command failed")
        return output[0].decode("ascii", errors="strict")
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise ValueError("dependency inspection unavailable or malformed") from error
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            if reader is not None:
                reader.join(2)
            # Do not block on a pipe lock if a descendant unexpectedly retained it.
            if reader is None or not reader.is_alive():
                process.stdout.close()


def validate_receipt(policy, image, value):
    """Check pinned receipt consistency only; live inspection still must establish truth."""
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "image_id", "artifacts"}
        or value["schema"] != "preinstalled-artifact-verification-v1"
        or value["image_id"] != image
        or not isinstance(value["artifacts"], dict)
        or set(value["artifacts"]) != set(policy.items(image))
    ):
        raise ValueError("dependency inspection receipt is malformed")
    for key, expected in policy.items(image).items():
        actual = value["artifacts"][key]
        if (
            not isinstance(actual, dict)
            or actual != {**expected, "resolved_path": actual.get("resolved_path")}
            or not _path(actual["resolved_path"])
        ):
            raise ValueError(
                "dependency inspection receipt differs from the artifact pins"
            )


def verify_image(policy, image):
    """Recompute pinned facts with no retries/fallback; errors prohibit paid launch."""
    if (
        not isinstance(image, str)
        or not IMAGE.fullmatch(image)
        or image not in policy.images
    ):
        raise ValueError("dependency inspection requires an allowlisted image ID")
    expected = policy.items(image)
    if not isinstance(expected, dict) or not 0 < len(expected) <= 32:
        raise ValueError("dependency inspection artifact inventory is invalid")
    for key, value in expected.items():
        if (
            not isinstance(key, str)
            or len(key) > 256
            or not isinstance(value, dict)
            or set(value) != {"path", "sha256"}
            or not _path(value["path"])
            or not isinstance(value["sha256"], str)
            or not SHA256.fullmatch(value["sha256"])
        ):
            raise ValueError("dependency inspection artifact pin is invalid")
    identity = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    if identity != image + "\n":
        raise ValueError("dependency inspection image identity mismatch")
    ordered = sorted(expected)
    command = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "1000:1000",
        "--memory",
        "64m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "16",
        "--ulimit",
        "fsize=1048576:1048576",
        "--ulimit",
        "nofile=32:32",
        "--workdir",
        "/",
        "--entrypoint",
        "/usr/bin/timeout",
        image,
        "--signal=KILL",
        "20",
        "/bin/sh",
        "-c",
        INSPECT,
        "dependency-inspector",
        *[expected[key]["path"] for key in ordered],
    ]
    rows = _run(command).splitlines()
    if len(rows) != len(ordered):
        raise ValueError("dependency inspection artifact count mismatch")
    artifacts = {}
    for key, row in zip(ordered, rows):
        fields = row.split("\t")
        if (
            len(fields) != 2
            or not _path(fields[0])
            or fields[1] != expected[key]["sha256"]
        ):
            raise ValueError("dependency inspection artifact path or hash mismatch")
        artifacts[key] = {**expected[key], "resolved_path": fields[0]}
    result = {
        "schema": "preinstalled-artifact-verification-v1",
        "image_id": image,
        "artifacts": artifacts,
    }
    validate_receipt(policy, image, result)
    return result
