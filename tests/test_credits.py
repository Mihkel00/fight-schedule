"""Photo credits: only photos of known origin are credited, Wikimedia ones with
author and licence, and the credit follows the photo actually shown."""
import image_pipeline as I


CC = {'author': 'Jane Doe', 'author_url': 'https://commons.wikimedia.org/wiki/User:Jane', 'license': 'CC BY-SA 4.0',
      'license_url': 'https://creativecommons.org/licenses/by-sa/4.0', 'file_url': 'https://commons.wikimedia.org/wiki/File:Dubois.jpg',
      'free': True}
WIKI = 'https://upload.wikimedia.org/wikipedia/commons/9/92/Dubois.jpg'


def test_wikimedia_file_names():
    assert I.wikimedia_file(WIKI) == ('https://commons.wikimedia.org/w/api.php', 'File:Dubois.jpg')
    assert I.wikimedia_file('https://thumb.wikimedia.org/wikipedia/en/thumb/c/c8/V_2021.jpeg/960px-V_2021.jpeg') == \
        ('https://en.wikipedia.org/w/api.php', 'File:V_2021.jpeg')
    assert I.wikimedia_file('https://commons.wikimedia.org/wiki/Special:FilePath/Bak%20Bak.jpg?width=600')[1] == 'File:Bak Bak.jpg'
    assert I.wikimedia_file('https://ufc.com/images/x.png') is None


def test_ufc_photos_are_credited_to_ufc(data_dir):
    I.update_entry('Arnold Allen', sport='UFC', status='approved', source='ufc',
                   source_url='https://ufc.com/images/ALLEN.png', path='/persisted-fighters/arnold-allen.png?v=1')
    assert I.credit_for('Arnold Allen', 'UFC', shown='/persisted-fighters/arnold-allen.png?v=1') == {'text': 'UFC'}
    I.update_entry('Kayla Harrison', sport='UFC', status='auto', source='legacy',
                   source_url='/static/fighters/kayla-harrison.png', path='/static/fighters/kayla-harrison.png')
    assert I.credit_for('Kayla Harrison', 'UFC') == {'text': 'UFC'}


def test_unknown_origin_is_not_credited(data_dir):
    I.update_entry('Peter McGrail', sport='Boxing', status='auto', source='legacy',
                   source_url='/static/fighters/peter-mcgrail.jpg', path='/static/fighters/peter-mcgrail.jpg')
    I.update_entry('Fabio Wardley', sport='Boxing', status='manual', source='url',
                   source_url='https://www.fightmag.com/x.jpg', path='/persisted-fighters/fabio-wardley.jpg')
    assert I.credit_for('Peter McGrail', 'Boxing') is None
    assert I.credit_for('Fabio Wardley', 'Boxing') is None


def test_wikimedia_needs_fetched_free_licence(data_dir):
    I.update_entry('Daniel Dubois', sport='Boxing', status='approved', source='wikipedia',
                   source_url=WIKI, path='/persisted-fighters/daniel-dubois.jpg')
    assert I.credit_for('Daniel Dubois', 'Boxing') is None                    # not fetched yet
    I.update_entry('Daniel Dubois', credit=dict(CC, free=False, **{'for': WIKI}))
    assert I.credit_for('Daniel Dubois', 'Boxing') is None                    # non-free file
    I.update_entry('Daniel Dubois', credit=dict(CC, **{'for': WIKI}))
    c = I.credit_for('Daniel Dubois', 'Boxing')
    assert c['text'] == 'Wikimedia Commons' and c['author'] == 'Jane Doe' and c['license'] == 'CC BY-SA 4.0'
    I.update_entry('Daniel Dubois', source_url=WIKI.replace('Dubois', 'Other'))
    assert I.credit_for('Daniel Dubois', 'Boxing') is None                    # credit was for the old file


def test_credit_follows_the_photo_shown(data_dir):
    I.update_entry('Arnold Allen', sport='UFC', status='approved', source='ufc',
                   source_url='https://ufc.com/images/ALLEN.png', path='/persisted-fighters/arnold-allen.png?v=2')
    assert I.credit_for('Arnold Allen', 'UFC', shown='/persisted-fighters/something-else.png') is None


def test_fetch_wikimedia_credit_reads_author_and_licence(monkeypatch):
    class R:
        def json(self):
            return {'query': {'pages': {'1': {'imageinfo': [{'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Dubois.jpg',
                    'extmetadata': {'Artist': {'value': '<a href="//commons.wikimedia.org/wiki/User:Jane">Jane Doe</a>'},
                                    'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                                    'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0'}}}]}}}}
    monkeypatch.setattr(I.requests, 'get', lambda *a, **k: R())
    c = I.fetch_wikimedia_credit(WIKI)
    assert c['author'] == 'Jane Doe' and c['author_url'] == 'https://commons.wikimedia.org/wiki/User:Jane'
    assert c['license'] == 'CC BY-SA 4.0' and c['free'] and c['file_url'].endswith('File:Dubois.jpg')


def test_fight_page_shows_credit_line(client):
    import app as A
    I.update_entry('Natalia Silva', sport='UFC', status='approved', source='ufc',
                   source_url='https://ufc.com/images/SILVA.png', path='/persisted-fighters/natalia-silva.png')
    I.update_entry('Wang Cong', sport='UFC', status='approved', source='ufc',
                   source_url='https://ufc.com/images/WANG.png', path='/persisted-fighters/wang-cong.png')
    body = client.get('/event/ufc-332-silva-vs.-wang-2026-10-04').get_data(as_text=True)
    assert '<p class="photo-credit">Photos: UFC</p>' in body
    assert 'Fighter photos: UFC, Wikimedia Commons and others.' in body
    home = client.get('/').get_data(as_text=True)
    assert 'Credits on each fight page.' in home


def test_mixed_sources_name_each_fighter(client):
    I.update_entry('Natalia Silva', sport='UFC', status='approved', source='ufc',
                   source_url='https://ufc.com/images/SILVA.png', path='/persisted-fighters/natalia-silva.png')
    I.update_entry('Wang Cong', sport='UFC', status='approved', source='wikipedia',
                   source_url=WIKI, path='/persisted-fighters/wang-cong.jpg', credit=dict(CC, **{'for': WIKI}))
    body = client.get('/event/ufc-332-silva-vs.-wang-2026-10-04').get_data(as_text=True)
    line = body.split('<p class="photo-credit">')[1].split('</p>')[0]
    assert line.startswith('Photos: UFC (Silva) ·')
    assert '>Jane Doe</a> / <a href="https://commons.wikimedia.org/wiki/File:Dubois.jpg"' in line
    assert '>CC BY-SA 4.0</a>, cropped (Cong)' in line
