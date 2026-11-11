"""scrypt com salt aleatório: N=2**15, r=8, p=3 (OWASP, 32 MiB)."""
import hashlib
import hmac
import secrets

N, R, P = 32768, 8, 3


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=N, r=R, p=P,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split('$')
        if algorithm != 'scrypt' or (int(n), int(r), int(p)) != (N, R, P):
            return False
        salt_bytes, expected_bytes = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt_bytes) != 16 or len(expected_bytes) != 32:
            return False
        actual = hashlib.scrypt(password.encode('utf-8'), salt=salt_bytes, n=N, r=R, p=P,
                                maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


# Mesmo trabalho criptográfico para endereço desconhecido, inativo ou sem senha.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
