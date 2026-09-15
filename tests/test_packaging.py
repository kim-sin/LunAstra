import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lunastra_release_tool',ROOT/'tools'/'release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

class PackagingTests(unittest.TestCase):
    def test_source_allowlist_has_expected_entrypoints(self):
        files=release.collect();self.assertTrue(release.TOP<=set(files));self.assertIn('luna_astra/team.py',files)
    def test_internal_documentation_links_resolve(self):release.check_links(release.collect())
    def test_archive_manifest_matches_all_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'public.zip';result=release.build(p)
            self.assertEqual(result['manifest'],'PASS');self.assertEqual(result['crc'],'PASS');self.assertGreater(result['files'],80)
    def test_archive_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'public.zip';p.write_bytes(b'keep')
            with self.assertRaises(ValueError):release.build(p)
            self.assertEqual(p.read_bytes(),b'keep')
    def test_source_has_no_runtime_database_or_logs(self):
        for name in release.collect():self.assertFalse(name.endswith(('.sqlite3','.db','.log','.zip','.pem','.key')))
    def test_public_json_parses(self):
        for name,data in release.collect().items():
            if name.endswith('.json'):json.loads(data)

    def test_public_docs_are_english(self):
        import re
        for name,data in release.collect().items():
            if name.endswith('.md'):
                self.assertIsNone(re.search(r'[\uAC00-\uD7A3]',data.decode('utf-8-sig')),name)

    def test_only_reviewed_artwork_is_allowed(self):
        files=release.collect();name='docs/assets/lunastra-hero.webp'
        self.assertIn(name,files)
        with self.assertRaisesRegex(ValueError,'unreviewed artwork'):
            release.validate_files({**files,name:files[name]+b'changed'})
        with self.assertRaisesRegex(ValueError,'extension refused'):
            release.validate_files({**files,'docs/assets/other.webp':files[name]})
    def test_html_image_link_must_resolve(self):
        with self.assertRaisesRegex(ValueError,'broken local documentation link'):
            release.check_links({'README.md':b'<img src="docs/assets/missing.webp" width="420">'})
