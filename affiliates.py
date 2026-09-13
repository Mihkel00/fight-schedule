"""
Affiliate / streaming link layer.

Every "Watch on X" on the site goes through /go/<provider>, which redirects to
the provider's affiliate URL (or plain URL until one is configured) and logs
the click. Configure affiliate URLs with environment variables:

    AFFILIATE_DAZN=https://www.dazn.com/?ref=YOURID
    AFFILIATE_PARAMOUNT_PLUS=https://.../?subid={event}   # {event} -> event slug

The env var name is AFFILIATE_ + the provider key upper-cased with '-' -> '_'.
"""

import os
import re

# key -> display name, default (non-affiliate) URL, keywords that identify it in scraped text
PROVIDERS = {
    'dazn':               ('DAZN',                 'https://www.dazn.com/',              ('dazn',)),
    'paramount-plus':     ('Paramount+',           'https://www.paramountplus.com/',     ('paramount',)),
    'espn-plus':          ('ESPN+',                'https://plus.espn.com/',             ('espn+', 'espn plus', 'espn')),
    'ufc-fight-pass':     ('UFC Fight Pass',       'https://ufcfightpass.com/',          ('fight pass', 'fightpass')),
    'netflix':            ('Netflix',              'https://www.netflix.com/',           ('netflix',)),
    'prime-video':        ('Prime Video',          'https://www.primevideo.com/',        ('prime video', 'amazon')),
    'sky-sports':         ('Sky Sports',           'https://www.skysports.com/boxing',   ('sky sports', 'sky box office', 'sky')),
    'tnt-sports':         ('TNT Sports',           'https://www.tntsports.co.uk/boxing', ('tnt',)),
    'max':                ('Max',                  'https://www.max.com/',               ('max',)),
    'peacock':            ('Peacock',              'https://www.peacocktv.com/',         ('peacock',)),
    'tillertv':           ('TillerTV',             'https://tiller.tv/',                 ('tiller',)),
    'combat-sports-now':  ('Combat Sports Now',    'https://combatsportsnow.com/',       ('combat sports now',)),
    'wynn-records':       ('Wynn Records Network', 'https://www.wynnrecords.com/',       ('wynn',)),
}

_NOISE = re.compile(r'\s*[-–—|]\s*click here.*$|\s*\(.*?\)\s*$|^\s*live\s+on\s+', re.IGNORECASE)


def clean_broadcaster(text):
    """'DAZN - Click here' -> 'DAZN'; 'LIVE on Paramount+' -> 'Paramount+'."""
    if not text:
        return None
    t = _NOISE.sub('', text).strip()
    return t or None


def resolve_provider(text):
    """Map scraped broadcaster text to a provider key, or None if unknown."""
    t = (clean_broadcaster(text) or '').lower()
    if not t:
        return None
    # longer keywords first so 'espn+' beats 'espn', 'sky sports' beats 'sky'
    for key, (_, _, kws) in sorted(PROVIDERS.items(), key=lambda kv: -max(len(k) for k in kv[1][2])):
        if any(kw in t for kw in kws):
            return key
    return None


def provider_name(key):
    return PROVIDERS[key][0] if key in PROVIDERS else None


def affiliate_url(key, event_slug=''):
    """Affiliate URL from env if configured, else the provider's plain URL."""
    if key not in PROVIDERS:
        return None
    env = os.environ.get('AFFILIATE_' + key.upper().replace('-', '_'))
    url = env or PROVIDERS[key][1]
    return url.replace('{event}', event_slug or '')


def is_affiliate_configured(key):
    return bool(os.environ.get('AFFILIATE_' + key.upper().replace('-', '_')))
