from campus.agent import Agent
from campus.conversation import Conversation


def test_conversation_spreads_event_information():
    alice = Agent("Alice", "friendly", ["organize Game Night"], "Cafeteria")
    bob = Agent("Bob", "shy", ["make one new friend"], "Cafeteria")

    alice.known_events.add("Game Night")

    conversation = Conversation(random_seed=42)
    conversation.run(alice, bob)

    assert "Game Night" in bob.known_events


def test_conversation_updates_both_agents_memories():
    alice = Agent("Alice", "friendly", ["organize Game Night"], "Cafeteria")
    bob = Agent("Bob", "shy", ["study"], "Cafeteria")

    alice.known_events.add("Game Night")

    conversation = Conversation(random_seed=42)
    conversation.run(alice, bob)

    assert len(alice.memory.items) > 0
    assert len(bob.memory.items) > 0
    assert any("Game Night" in memory.description for memory in bob.memory.items)


def test_agent_invites_higher_relationship_friend_first():
    alice = Agent("Alice", "friendly", ["organize Game Night"], "Dorm")
    bob = Agent("Bob", "shy", [], "Dorm")
    cathy = Agent("Cathy", "social", [], "Dorm")

    alice.relationships = {
        "Bob": 2,
        "Cathy": 8,
    }

    invitee = alice.choose_invitee([bob, cathy])

    assert invitee.name == "Cathy"
