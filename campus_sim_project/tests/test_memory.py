from campus.memory import MemoryStream


def test_add_memory():
    memory = MemoryStream()

    memory.add(
        time="Day1 09:00",
        description="Alice met Bob in the cafeteria.",
        importance=5,
        tags=["Alice", "Bob", "cafeteria"],
    )

    assert len(memory.items) == 1
    assert memory.items[0].description == "Alice met Bob in the cafeteria."
    assert memory.items[0].importance == 5
    assert "Bob" in memory.items[0].tags


def test_retrieve_by_keyword_relevance():
    memory = MemoryStream()

    memory.add("Day1 09:00", "Alice invited Bob to Game Night.", 8, ["Alice", "Bob", "game", "night", "invite"])
    memory.add("Day1 10:00", "Bob studied for the AI exam.", 7, ["Bob", "exam", "study"])
    memory.add("Day1 11:00", "Cathy ate lunch at cafeteria.", 3, ["Cathy", "cafeteria"])

    results = memory.retrieve("game night invite", top_k=1)

    assert results[0].description == "Alice invited Bob to Game Night."


def test_retrieve_considers_importance():
    memory = MemoryStream()

    memory.add("Day1 09:00", "Bob said hello.", 2, ["Bob", "hello"])
    memory.add("Day1 10:00", "Bob is very worried about the exam.", 9, ["Bob", "exam", "worried"])

    results = memory.retrieve("Bob exam", top_k=2)

    assert results[0].description == "Bob is very worried about the exam."


def test_retrieve_considers_recency():
    memory = MemoryStream()

    memory.add("Day1 08:00", "Alice mentioned Game Night.", 5, ["Alice", "game", "night"])
    memory.add("Day1 18:00", "Alice changed Game Night location to Quad.", 5, ["Alice", "game", "night", "location", "Quad"])

    results = memory.retrieve("Game Night location", top_k=1)

    assert results[0].description == "Alice changed Game Night location to Quad."
