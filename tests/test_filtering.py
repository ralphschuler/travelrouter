import unittest

from travelrouter.filtering import domains_from_text, parse_country_networks, render_block_zones, validate_settings


class FilteringTests(unittest.TestCase):
    def test_domain_sources_cannot_inject_unbound_configuration(self):
        source = '# comment\n0.0.0.0 ads.example\ntracker.example\nserver: evil\nlocalhost\n'
        self.assertEqual(domains_from_text(source), {'ads.example', 'tracker.example'})

    def test_allowlist_exempts_subtree_without_disabling_parent_block(self):
        zones = render_block_zones({'example.org', 'bad.example', 'ads.allowed.example'},
                                  ['safe.example.org', 'allowed.example'], ['ru'])
        self.assertIn('"bad.example" always_nxdomain', zones)
        self.assertIn('"ru" always_nxdomain', zones)
        self.assertIn('"example.org" always_nxdomain', zones)
        self.assertIn('"safe.example.org" transparent', zones)
        self.assertNotIn('ads.allowed.example', zones)

    def test_country_ranges_reject_defaults_and_local_destinations(self):
        self.assertEqual(parse_country_networks('8.8.8.0/24\n9.9.9.0/24'), ['8.8.8.0/24', '9.9.9.0/24'])
        for value in ['0.0.0.0/0', '10.0.0.0/8', '8.8.8.0/24; drop', '::/0']:
            with self.assertRaises(ValueError):
                parse_country_networks(value)

    def test_settings_are_bounded_and_countries_are_identifiers(self):
        validated = validate_settings({'ads': True, 'threats': True, 'countries': ['RU', 'CN'],
                                       'domains': ['bad.example'], 'allow': [], 'tlds': ['ru']})
        self.assertEqual(set(validated['countries']), {'RU', 'CN'})
        for countries in [['../../etc'], ['USA'], ['RU\nflush ruleset']]:
            with self.assertRaises(ValueError):
                validate_settings({'countries': countries})
