from scripts.audit_publish import private_research_path
import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_public_content import audit_entries, git_entries, public_findings
from scripts.deprioritize_irrelevant_remaining_sources import load_private_dispositions
from scripts.configure_remaining_retrieval import load_private_specs


ROOT = Path(__file__).resolve().parents[1]


def test_private_research_artifacts_are_never_publishable():
    for path in ('RAI_in_Full.pdf','other.PDF','data/exports/review.xlsx','data/raw/sample.jsonl',
                 'config/taxonomy.json','notebooks/audit.ipynb','PROMPTS.md',
                 'docs/final50_report.md','backup.csv','dump.parquet','sample.sqlite',
                 'CONFIG/registry.json','Data/hidden.md','.publish-local/backup.md'):
        assert private_research_path(path),path


def test_code_and_general_documentation_remain_publishable():
    for path in ('README.md','LICENSE','.gitignore','.env.example','requirements.txt',
                 'src/processing/category.py','tests/test_review_state.py',
                 'docs/github_publishing.md','scripts/check_private_tracking.py',
                 'docs/PROMPTS.md','docs/methodology_public.md','docs/source_strategy_public.md',
                 'examples/config/sources.example.json'):
        assert not private_research_path(path),path


@pytest.mark.parametrize('form', ['video', 'short', 'channel', 'messaging', 'encoded', 'escaped', 'identifier', 'comment'])
def test_concrete_platform_reference_is_rejected(form):
    # Assemble non-evidence tokens only inside an offline test, never as sources.
    host = 'www.youtube' + '.com'
    video = 'https://' + host + '/watch?v=' + 'A' * 11
    samples = {
        'video': video,
        'short': 'https://' + 'youtu' + '.be/' + 'A' * 11,
        'channel': 'https://' + host + '/@' + 'fixture_only',
        'messaging': 'https://' + 't' + '.me/' + 'fixture_only',
        'encoded': video.replace(':', '%3A').replace('/', '%2F'),
        'escaped': video.replace('/', '\\/'),
        'identifier': 'YT-' + 'A' * 11,
        'comment': 'Ug' + 'w' + 'A' * 25,
    }
    assert public_findings(samples[form])


def test_generic_api_and_unresolved_runtime_template_are_not_collected_links():
    host = 'www.youtube' + '.com'
    text = 'https://' + host + '/oembed?' + '\n' + 'https://' + host + '/watch?v={video_id}'
    assert public_findings(text) == {}
    assert public_findings('https://research-fixture.invalid/discussion') == {}


def test_private_evidence_guard_reports_no_matched_values():
    private_token = 'private-fixture-identifier-only'
    original = 'Fixture-only text for a private evidence matching test.'
    evidence = {private_token: 'known_source_identifier', original: 'known_raw_text'}
    findings = audit_entries({'unsafe.md': (private_token + '\n' + original).encode()}, evidence)
    assert findings[0]['kinds'] == {'known_source_identifier': 1, 'known_raw_text': 1}
    report = json.dumps(findings)
    assert private_token not in report
    assert original not in report


def test_content_guard_checks_staged_bytes_not_working_tree(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    target = tmp_path / 'public.md'
    private_token = 'fixture-private-identifier'
    target.write_text(private_token, encoding='utf-8')
    subprocess.run(['git', 'add', 'public.md'], cwd=tmp_path, check=True, capture_output=True)
    target.write_text('Sanitized working copy, not yet staged.', encoding='utf-8')
    entries = git_entries(tmp_path)
    assert entries['public.md'].decode() == private_token
    assert audit_entries(entries, {private_token: 'known_source_identifier'})


def test_unknown_binary_is_not_silently_declared_safe():
    assert audit_entries({'unexpected.bin': b'\xff\xfe\x00'})[0]['kinds'] == {'uninspected_binary_file': 1}


def test_public_configuration_templates_contain_no_active_inputs():
    base = ROOT / 'examples/config'
    sources = json.loads((base / 'sources.example.json').read_text())
    taxonomy = json.loads((base / 'taxonomy.example.json').read_text())
    terms = json.loads((base / 'search_terms.example.json').read_text())
    dispositions = json.loads((base / 'source_dispositions.example.json').read_text())
    assert sources['sources'] == []
    assert taxonomy['subcategories'] == []
    assert taxonomy['category_template']['full_definition'] == ''
    assert taxonomy['category_template']['reference_examples'] == []
    assert terms['categories'] == {}
    assert terms['gen1_category_template']['observed_real_world_phrases'] == []
    assert terms['general_category_template']['discovery_queries'] == []
    assert terms['general_category_template']['harm_terms'] == {}
    assert terms['general_category_template']['compound_patterns'] == {}
    assert dispositions == {'exact_source_ids': [], 'reassign': {}, 'markers': []}
    assert json.loads((base / 'remaining_retrieval.example.json').read_text()) == {'common_quality': {}, 'specs': {}}


def test_public_taxonomy_overview_has_all_sixteen_codes():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    expected = [f'{group}-{n}' for group, maximum in [('GEN', 5), ('REG', 4), ('STA', 5), ('REL', 2)]
                for n in range(1, maximum + 1)]
    rows = [line for line in readme.splitlines() if line.startswith(('| GEN-', '| REG-', '| STA-', '| REL-'))]
    assert len(rows) == 16
    assert {row.split('|')[1].strip() for row in rows} == set(expected)


def test_public_prompts_are_labelled_summaries_not_original_transcript():
    text = (ROOT / 'docs/PROMPTS.md').read_text(encoding='utf-8')
    assert 'not verbatim historical prompts' in text
    assert 'original root-level PROMPTS.md remains unchanged' in text
    assert 'Exact supplied attachment text. Original SHA-256:' not in text
    assert public_findings(text) == {}


def test_private_dispositions_load_without_modifying_input(tmp_path):
    path = tmp_path / 'dispositions.json'
    path.write_text(json.dumps({'exact_source_ids': ['fixture-source'], 'reassign': {'fixture-source': ['REG-1', 'REG-3']}}))
    before = path.read_bytes()
    exact, reassign = load_private_dispositions(path)
    assert exact == {'fixture-source'}
    assert reassign == {'fixture-source': ('REG-1', 'REG-3')}
    assert path.read_bytes() == before


def test_missing_private_dispositions_fail_before_maintenance(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_private_dispositions(tmp_path / 'missing.json')


def test_private_retrieval_specs_are_loaded_without_writes(tmp_path):
    path = tmp_path / 'specs.json'
    path.write_text(json.dumps({'common_quality': {'positive': []}, 'specs': {}}))
    before = path.read_bytes()
    assert load_private_specs(path) == ({'positive': []}, {})
    assert path.read_bytes() == before
    with pytest.raises(FileNotFoundError):
        load_private_specs(tmp_path / 'missing.json')
