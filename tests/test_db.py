import asyncio


def test_state_roundtrip(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        assert await db.get_state("k", "d", db_path=p) == "d"
        await db.set_state("k", "v", db_path=p)
        assert await db.get_state("k", db_path=p) == "v"
    asyncio.run(run())


def test_pause_hmac_roundtrip(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        assert await db.get_paused(db_path=p) is False
        await db.set_paused(True, db_path=p)
        assert await db.get_paused(db_path=p) is True
        # Tampering: overwrite with garbage -> defaults to unpaused
        await db.set_state("_s", "deadbeef", db_path=p)
        assert await db.get_paused(db_path=p) is False
    asyncio.run(run())


def test_feedback_vote_idempotent_per_user(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        up, down = await db.record_feedback_vote(111, 1, -1, db_path=p)
        assert (up, down) == (0, 1)
        # Same user re-votes: updates, doesn't double count
        up, down = await db.record_feedback_vote(111, 1, 1, db_path=p)
        assert (up, down) == (1, 0)
        up, down = await db.record_feedback_vote(111, 2, -1, db_path=p)
        assert (up, down) == (1, 1)
    asyncio.run(run())


def test_log_answer_and_feedback(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        row = await db.log_answer(
            guild_id=1, channel_id=2, channel_name="general", author_id=3,
            author_name="bob", question="q?", answer="a", grounded=1,
            message_id=999, db_path=p,
        )
        assert row >= 1
        rec = await db.get_by_message_id(999, db_path=p)
        assert rec["question"] == "q?" and rec["grounded"] == 1
        assert db.is_replayable(rec) is True
        q = await db.mark_feedback(999, correct=False, db_path=p)
        assert q == "q?"
        rec = await db.get_by_message_id(999, db_path=p)
        assert db.is_replayable(rec) is False   # admin-marked wrong -> never replay
        assert db.is_replayable({"grounded": 0, "marked_correct": None}) is False
    asyncio.run(run())
