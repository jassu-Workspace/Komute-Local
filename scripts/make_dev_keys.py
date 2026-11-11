"""Write dev keys to $LOCALAPPDATA/komute/dev.env once. Never prints key values."""
import base64
import os
import secrets
import sys
from pathlib import Path


def main() -> int:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "komute" / "dev.env"
    if path.exists():
        print(f"refusing to overwrite {path}", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    b64 = lambda: base64.b64encode(secrets.token_bytes(32)).decode()  # noqa: E731
    lines = [
        f"KOMUTE_API_KEY={secrets.token_urlsafe(32)}",
        f"KOMUTE_STORAGE_KEY_B64={b64()}",
        "KOMUTE_STORAGE_KEY_ID=dev-s1",
        f"KOMUTE_MANIFEST_KEY_B64={b64()}",
        "KOMUTE_MANIFEST_KEY_ID=dev-m1",
    ]
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
