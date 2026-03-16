#!/usr/bin/env python3
"""
One-time RSA key pair generation for DocuSign JWT Grant auth.

Usage:
    python scripts/generate_docusign_keys.py

Outputs:
    docusign_private.key  — add path to .env as DOCUSIGN_PRIVATE_KEY_PATH
    docusign_public.pem   — upload to DocuSign Integration Key in dev console
"""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PRIVATE_KEY_FILE = Path("docusign_private.key")
PUBLIC_KEY_FILE = Path("docusign_public.pem")


def main() -> None:
    if PRIVATE_KEY_FILE.exists():
        print(f"[!] {PRIVATE_KEY_FILE} already exists. Delete it first if you want to regenerate.")
        return

    print("Generating 2048-bit RSA key pair…")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Write private key (PEM, no passphrase)
    PRIVATE_KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PRIVATE_KEY_FILE.chmod(0o600)
    print(f"[+] Private key written to {PRIVATE_KEY_FILE} (mode 600)")

    # Write public key
    PUBLIC_KEY_FILE.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"[+] Public key written to {PUBLIC_KEY_FILE}")
    print()
    print("Next steps:")
    print(f"  1. Add to .env:  DOCUSIGN_PRIVATE_KEY_PATH={PRIVATE_KEY_FILE.resolve()}")
    print(f"  2. Upload {PUBLIC_KEY_FILE} to your DocuSign Integration Key (RSA Keys section)")
    print("  3. Grant user consent: https://account-d.docusign.com/oauth/auth?response_type=code"
          "&scope=signature%20impersonation"
          "&client_id=YOUR_INTEGRATION_KEY"
          "&redirect_uri=https://www.docusign.com")


if __name__ == "__main__":
    main()
