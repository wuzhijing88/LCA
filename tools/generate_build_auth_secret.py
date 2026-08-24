import argparse
import base64
import os
import secrets
import string


def _generate_secret(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _encode_b64x2(text: str) -> str:
    first = base64.b64encode(text.encode("utf-8")).decode("ascii")
    second = base64.b64encode(first.encode("utf-8")).decode("ascii")
    return second


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate dynamic build auth secret")
    parser.add_argument("--output", required=True)
    parser.add_argument("--length", type=int, default=48)
    args = parser.parse_args()

    length = int(args.length or 0)
    if length < 24:
        raise ValueError("length must be >= 24")

    output_path = os.path.abspath(args.output)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    secret = _generate_secret(length)
    encoded_secret = _encode_b64x2(secret)

    with open(output_path, "w", encoding="utf-8") as secret_file:
        secret_file.write(encoded_secret)

    print(f"Generated build auth secret file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
