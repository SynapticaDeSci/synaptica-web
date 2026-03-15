from shared.research.catalog import (
    RESEARCH_RUN_CONTRACT_VERSION,
    rank_supported_agents_for_todo,
    select_supported_agent_for_todo,
)


def test_rank_supported_agents_filters_critique_to_synthesis_agents(monkeypatch):
    agents = [
        {
            "agent_id": "literature-miner-001",
            "name": "Literature Miner",
            "description": "Searches for source papers and extracts evidence for a research topic.",
            "capabilities": ["literature-mining", "evidence-gathering", "citation-collection"],
            "pricing": {"rate": 8.0},
            "reputation_score": 0.99,
            "role_families": ["evidence"],
        },
        {
            "agent_id": "knowledge-synthesizer-001",
            "name": "Knowledge Synthesizer",
            "description": "Critiques drafts, fact-checks claims, and writes source-grounded answers.",
            "capabilities": ["knowledge-synthesis", "fact-checking", "critic-review"],
            "pricing": {"rate": 7.0},
            "reputation_score": 0.55,
            "role_families": ["synthesis"],
        },
    ]
    monkeypatch.setattr("shared.research.catalog.list_supported_research_agents", lambda: agents)

    ranked = rank_supported_agents_for_todo(
        "critique_and_fact_check",
        "fact checking, critic review, source verification",
        "Critique and fact-check",
    )

    assert ranked == ["knowledge-synthesizer-001"]


def test_select_supported_agent_uses_role_specific_default_when_ranked_list_is_empty(monkeypatch):
    monkeypatch.setattr("shared.research.catalog.list_supported_research_agents", lambda: [])

    assert (
        select_supported_agent_for_todo(
            "gather_evidence",
            "evidence gathering, source discovery, fresh web research",
            "Gather evidence",
        )
        == "literature-miner-001"
    )
    assert (
        select_supported_agent_for_todo(
            "critique_and_fact_check",
            "fact checking, critic review, source verification",
            "Critique and fact-check",
        )
        == "knowledge-synthesizer-001"
    )


def test_rank_supported_agents_excludes_custom_agent_without_current_contract(monkeypatch):
    agents = [
        {
            "agent_id": "custom-critic-001",
            "name": "Custom Critic",
            "description": "Critiques drafts and checks sourcing.",
            "capabilities": ["critique", "fact-checking"],
            "pricing": {"rate": 2.0},
            "reputation_score": 0.99,
            "role_families": ["synthesis"],
        },
        {
            "agent_id": "knowledge-synthesizer-001",
            "name": "Knowledge Synthesizer",
            "description": "Critiques drafts, fact-checks claims, and writes source-grounded answers.",
            "capabilities": ["knowledge-synthesis", "fact-checking", "critic-review"],
            "pricing": {"rate": 7.0},
            "reputation_score": 0.55,
            "role_families": ["synthesis"],
        },
    ]
    monkeypatch.setattr("shared.research.catalog.list_supported_research_agents", lambda: agents)

    ranked = rank_supported_agents_for_todo(
        "critique_and_fact_check",
        "fact checking, critic review, source verification",
        "Critique and fact-check",
    )

    assert ranked == ["knowledge-synthesizer-001"]


def test_rank_supported_agents_allows_custom_agent_with_current_contract(monkeypatch):
    agents = [
        {
            "agent_id": "literature-miner-001",
            "name": "Literature Miner",
            "description": "Searches for source papers and extracts evidence for a research topic.",
            "capabilities": ["literature-mining", "evidence-gathering", "citation-collection"],
            "pricing": {"rate": 8.0},
            "reputation_score": 0.55,
            "role_families": ["evidence"],
        },
        {
            "agent_id": "custom-evidence-001",
            "name": "Custom Evidence Agent",
            "description": "Runs current evidence gathering for research runs.",
            "capabilities": ["evidence-gathering", "source-discovery"],
            "pricing": {"rate": 3.0},
            "reputation_score": 0.99,
            "role_families": ["evidence"],
            "research_run_contract_version": RESEARCH_RUN_CONTRACT_VERSION,
            "supported_node_strategies": ["gather_evidence", "curate_sources"],
        },
    ]
    monkeypatch.setattr("shared.research.catalog.list_supported_research_agents", lambda: agents)

    ranked = rank_supported_agents_for_todo(
        "gather_evidence",
        "evidence gathering, source discovery, fresh web research",
        "Gather evidence",
    )

    assert ranked[0] == "custom-evidence-001"
