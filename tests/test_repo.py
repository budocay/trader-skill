import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["trader-copycat", "trader-news", "trader-budget", "trader-pelosi", "trader-analyst",
          "trader-screener", "trader-risk", "trader-broker", "trader-tax", "trader-alerts",
          "trader-rebalance", "trader-frais", "trader-dirigeants"]
ABOUT = ("13 skills Claude pour investir depuis la France : les vrais frais de BoursoBank et Fortuneo, "
         "la fiscalité française, le PEA, les dirigeants qui achètent, et jamais un ordre sans ton oui.")
# skills that can lead to an order carry the safety block
ORDER_PATH = ["trader-copycat", "trader-budget", "trader-pelosi", "trader-risk", "trader-broker",
              "trader-tax", "trader-alerts", "trader-rebalance"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_thirteen_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_matches_the_reel(self):
        root = sorted(d for d in os.listdir(ROOT) if not d.startswith(".git"))
        self.assertEqual(root, sorted([".claude-plugin", "LICENSE", "README.md", "tests"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertTrue("not financial advice" in low or "pas un conseil financier" in low, s)
            self.assertTrue("yes" in low or "oui" in low, s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "trader-skill-fr")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "trader-skill-fr")
        self.assertEqual(market["plugins"][0]["name"], "trader-skill-fr")

    def test_readme_carries_the_reel_copy(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# Trader skill, version française"))
        for line in (ABOUT,
                     "/plugin marketplace add budocay/trader-skill",
                     "/plugin install trader-skill-fr@trader-skill-fr",
                     "https://github.com/Jakeschincariol/trader-skill",
                     "## Les petits caractères"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)  # built, so this file passes too

    def test_paper_trading_is_the_default(self):
        for name in ("config.example.json", "config.fr.example.json"):
            with open(os.path.join(ROOT, "trader-budget", name), encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.assertIs(cfg["paper"], True, name)
            self.assertIs(cfg.get("allow_options", False), False, name)

    def test_french_config_names_a_known_broker(self):
        with open(os.path.join(ROOT, "trader-budget", "config.fr.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        with open(os.path.join(ROOT, "trader-frais", "grilles.json"), encoding="utf-8") as fh:
            grilles = json.load(fh)
        self.assertIn(cfg["formule"], grilles["courtiers"][cfg["courtier"]]["formules"])
        self.assertEqual(cfg["devise"], "EUR")


if __name__ == "__main__":
    unittest.main()
