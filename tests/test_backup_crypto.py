import pytest
from cryptography.exceptions import InvalidTag
from transcoder import backup


def test_encrypt_decrypt_roundtrip():
    text = "SONARR_URL=http://x\nAPP_PASSWORD=secret\n"
    ct, crypto = backup.encrypt_env(text, "hunter2")
    assert ct != text.encode()
    assert crypto["cipher"] == "AES-256-GCM" and crypto["kdf"] == "scrypt"
    assert backup.decrypt_env(ct, "hunter2", crypto) == text


def test_wrong_passphrase_raises():
    ct, crypto = backup.encrypt_env("X=1\n", "right")
    with pytest.raises(InvalidTag):
        backup.decrypt_env(ct, "wrong", crypto)


def test_tampered_ciphertext_raises():
    ct, crypto = backup.encrypt_env("X=1\n", "pw")
    bad = bytearray(ct); bad[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        backup.decrypt_env(bytes(bad), "pw", crypto)
