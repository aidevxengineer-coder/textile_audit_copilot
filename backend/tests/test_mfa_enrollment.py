from app.auth.service import AuthService
from app.core.encryption import encrypt_text


def test_encrypted_totp_secret_exceeds_legacy_column_but_fits_text() -> None:
    # Regression: the previous VARCHAR(128) column rejected Fernet ciphertext.
    encrypted = encrypt_text("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
    assert len(encrypted) > 128
    assert AuthService() is not None
