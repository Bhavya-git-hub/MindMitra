"""Encryption, password storage and confidentiality separation."""

import pytest
from sqlalchemy import LargeBinary, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.crypto import DecryptionError, FieldCipher, generate_key
from app.core.security import hash_password, verify_password
from app.infrastructure.db import models as m
from app.infrastructure.db.base import Base
from app.infrastructure.db.enums import UserRole
from app.infrastructure.db.types import EncryptedText
from tests import helpers
from tests.conftest import SEED_PASSWORD


def test_cipher_roundtrip_and_context_binding() -> None:
    c = FieldCipher(generate_key())
    blob = c.encrypt("hello", "a.b.c")
    assert c.decrypt(blob, "a.b.c") == "hello"
    assert b"hello" not in blob
    with pytest.raises(DecryptionError):
        c.decrypt(blob, "a.b.other")  # copied into another column
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(DecryptionError):
        c.decrypt(tampered, "a.b.c")
    with pytest.raises(DecryptionError):
        FieldCipher(generate_key()).decrypt(blob, "a.b.c")  # wrong key
    assert c.encrypt("hello", "a.b.c") != blob  # fresh nonce every time


def test_cipher_rejects_bad_keys() -> None:
    with pytest.raises(ValueError):
        FieldCipher("c2hvcnQ=")


def test_password_hashing() -> None:
    h = hash_password("a-long-enough-password")
    assert h.startswith("$argon2id$") and "a-long-enough-password" not in h
    assert verify_password(h, "a-long-enough-password")
    assert not verify_password(h, "wrong-password-value")
    assert not verify_password("not-a-hash", "whatever-password")
    with pytest.raises(ValueError):
        hash_password("short")


async def test_seeded_passwords_are_argon2id_and_verify(session: AsyncSession) -> None:
    creds = (await session.execute(select(m.Credential))).scalars().all()
    assert creds
    assert all(c.password_hash.startswith("$argon2id$") for c in creds)
    assert all(SEED_PASSWORD not in c.password_hash for c in creds)
    assert verify_password(creds[0].password_hash, SEED_PASSWORD)


async def test_database_rejects_plaintext_password_hash(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    u = await helpers.new_user(session, inst, UserRole.STUDENT)
    with pytest.raises(IntegrityError, match="password_hash_is_argon2id"):
        async with session.begin_nested():
            session.add(m.Credential(user_id=u.id, password_hash="hunter2hunter2"))
            await session.flush()


def test_there_is_no_plaintext_password_column() -> None:
    cols = [
        (t.fullname, c.name)
        for t in Base.metadata.tables.values()
        for c in t.columns
        if "password" in c.name
    ]
    assert {c for _, c in cols} <= {"password_hash", "password_changed_at"}


def test_encrypted_columns_are_bytea() -> None:
    encrypted = [
        (t.fullname, c.name)
        for t in Base.metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, EncryptedText)
    ]
    assert len(encrypted) >= 8
    for t in Base.metadata.tables.values():
        for c in t.columns:
            if isinstance(c.type, EncryptedText):
                assert isinstance(c.type.impl, type(LargeBinary()))


async def test_confidential_text_is_ciphertext_at_rest(
    engine: AsyncEngine, session: AsyncSession
) -> None:
    note = await helpers.first(session, select(m.TherapyNote))
    assert note.body.startswith("SYNTHETIC NOTE")  # decrypts transparently via the ORM
    async with engine.connect() as conn:
        raw = (
            (await conn.execute(text("SELECT body FROM therapy.therapy_notes LIMIT 5")))
            .scalars()
            .all()
        )
        raw_msg = (
            (await conn.execute(text("SELECT body FROM comm.messages LIMIT 5"))).scalars().all()
        )
        raw_j = (
            (await conn.execute(text("SELECT body FROM wellness.journal_entries LIMIT 5")))
            .scalars()
            .all()
        )
        raw_ai = (
            (await conn.execute(text("SELECT content FROM ai.ai_messages LIMIT 5"))).scalars().all()
        )
        raw_alert = (
            (await conn.execute(text("SELECT excerpt FROM safety.risk_alerts LIMIT 5")))
            .scalars()
            .all()
        )
    for blobs in (raw, raw_msg, raw_j, raw_ai, raw_alert):
        assert blobs
        for b in blobs:
            assert isinstance(b, bytes | memoryview)
            assert b"SYNTHETIC" not in bytes(b) and bytes(b)[:1] == b"\x01"


async def test_ciphertext_cannot_be_moved_between_columns(session: AsyncSession) -> None:
    """AAD binds ciphertext to its column: copying a note body into a message fails to decrypt."""
    await session.execute(
        text("UPDATE comm.messages SET body = (SELECT body FROM therapy.therapy_notes LIMIT 1)")
    )
    session.expire_all()
    with pytest.raises(DecryptionError):
        await helpers.first(session, select(m.Message))


async def test_wellness_reader_role_cannot_read_therapy_schema(
    engine: AsyncEngine, seeded: object
) -> None:
    """Confidential therapy data sits in its own schema, so it can be granted separately."""
    async with engine.connect() as conn:
        is_super = (
            await conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
        ).scalar_one()
        if not is_super:
            pytest.skip("needs a superuser test role to create a temporary role")
        try:
            await conn.execute(text("CREATE ROLE mm_wellness_reader NOLOGIN"))
            await conn.execute(text("GRANT USAGE ON SCHEMA wellness, org TO mm_wellness_reader"))
            await conn.execute(
                text("GRANT SELECT ON ALL TABLES IN SCHEMA wellness TO mm_wellness_reader")
            )
            await conn.execute(text("SET LOCAL ROLE mm_wellness_reader"))
            assert (
                await conn.execute(text("SELECT count(*) FROM wellness.mood_entries"))
            ).scalar_one() > 0
            for forbidden in ("therapy.therapy_notes", "comm.messages", "safety.risk_alerts"):
                with pytest.raises(DBAPIError, match="permission denied"):
                    async with conn.begin_nested():
                        await conn.execute(text(f"SELECT 1 FROM {forbidden}"))  # noqa: S608
        finally:
            await conn.rollback()


def test_wellness_and_therapy_schemas_do_not_reference_each_other() -> None:
    """General wellness data never depends on confidential therapy tables (and vice versa)."""
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            target = fk.column.table.schema
            if table.schema == "wellness":
                assert target != "therapy", (table.fullname, fk)
            if table.schema == "therapy":
                assert target not in ("wellness", "ai"), (table.fullname, fk)
    assert inspect(m.TherapyNote).mapper.local_table.schema == "therapy"
