"""Plugin fincept-fondo (subagentes con sus skills) y comando del equipo."""
import json

import pytest

from server.fund import build_plugin as B
from server.fund import team
from server.fund import training as T


def test_plugin_agents_match_the_fund():
    profiles = {p["id"]: p for p in T.agent_profiles()}
    files = sorted(p.name for p in (B.PLUGIN / "agents").glob("*.md"))
    assert files == sorted(f"{B.ROLES[a['id']]['file']}.md" for a in T.AGENTS)
    for ag in T.AGENTS:
        path = B.PLUGIN / "agents" / f"{B.ROLES[ag['id']]['file']}.md"
        assert path.read_text(encoding="utf-8") == B.agent_markdown(ag, profiles[ag["id"]]), \
            f"{path.name} desactualizado: python -m server.fund.build_plugin"


def test_every_agent_skill_is_bundled_with_its_license_or_source():
    for ag in T.AGENTS:
        for s in ag["skills"]:
            assert (B.PLUGIN / "skills" / s / "SKILL.md").is_file(), s
    assert (B.PLUGIN / "skills" / "llm-trading-agent-security" / "LICENSE").is_file()
    assert (B.PLUGIN / "skills" / "comite-fincept" / "SKILL.md").read_text(encoding="utf-8") == B.COMMITTEE_SKILL


def test_marketplace_and_manifest():
    mk = json.loads(B.MARKETPLACE.read_text(encoding="utf-8"))
    assert mk["name"] == "fincept" and mk["plugins"][0]["source"] == "./plugins/fincept-fondo"
    man = json.loads((B.PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert man["name"] == B.NAME == mk["plugins"][0]["name"]


def test_no_agent_can_approve_real_orders():
    for ag in T.AGENTS:
        text = (B.PLUGIN / "agents" / f"{B.ROLES[ag['id']]['file']}.md").read_text(encoding="utf-8")
        assert "Nunca apruebes ni envíes órdenes reales" in text and "tools: Read, Grep, Glob, Bash" in text


def test_team_sections_from_a_real_cycle(client, user, tmp_path):
    rep = client.post("/fund/cycle", headers=user["headers"], json={}).json()["data"]["report"]
    out = {r: team.section(rep, r) for r in team.ROLES}
    assert out["macro"]["regimen"]["regime"] in {"risk_on", "neutral", "risk_off"}
    assert out["cuant"]["estrategias"] and out["riesgos"]["politica"]["min_cash"] == pytest.approx(0.05)
    assert set(out["todos"]) >= {"macro", "trader", "equipo"} and out["equipo"]["committee"]
    p = tmp_path / "acta.json"
    p.write_text(json.dumps(rep, default=str))
    assert team.main(["trader", "--from", str(p)]) == 0
