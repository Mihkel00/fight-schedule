"""
UFC Fighter Image Scraper
Scrapes all UFC fighters and their images from ufc.com/athletes
Total: ~955 fighters across 85 pages
Includes rate limiting to be respectful
"""

import requests
from bs4 import BeautifulSoup
import json
from time import sleep

def scrape_ufc_fighters():
    """Scrape all UFC fighters from official roster"""
    
    print("\n" + "="*60)
    print("UFC FIGHTER IMAGE SCRAPER")
    print("="*60 + "\n")
    
    fighters_ufc = {}
    total_pages = 85  # 955 fighters ÷ 12 per page ≈ 85 pages
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for page in range(1, total_pages + 1):
        try:
            url = f'https://www.ufc.com/athletes/all?filters%5B0%5D=status%3A23&page={page}'
            
            print(f"[Page {page}/{total_pages}] Fetching fighters... ", end='')
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                print(f"✗ Failed (status {response.status_code})")
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all fighter cards
            cards = soup.find_all('div', class_='c-listing-athlete-flipcard')
            
            page_count = 0
            for card in cards:
                try:
                    # Extract fighter name
                    name_elem = card.find('span', class_='c-listing-athlete__name')
                    if not name_elem:
                        continue
                    fighter_name = name_elem.get_text(strip=True)
                    
                    # Extract image URL
                    thumbnail = card.find('div', class_='c-listing-athlete__thumbnail')
                    if thumbnail:
                        img_elem = thumbnail.find('img')
                        if img_elem and img_elem.get('src'):
                            img_url = img_elem['src']
                            
                            # Clean up URL (remove query params for cleaner URLs)
                            if '?' in img_url:
                                img_url = img_url.split('?')[0]
                            
                            fighters_ufc[fighter_name] = img_url
                            page_count += 1
                
                except Exception as e:
                    print(f"\n  Error parsing card: {e}")
                    continue
            
            print(f"✓ Found {page_count} fighters")
            
            # Rate limiting - be respectful to UFC servers
            sleep(1)
            
        except Exception as e:
            print(f"✗ Error on page {page}: {e}")
            continue
    
    # Save to JSON
    print(f"\nSaving to fighters_ufc.json...")
    with open('fighters_ufc.json', 'w', encoding='utf-8') as f:
        json.dump(fighters_ufc, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("SCRAPING COMPLETE")
    print("="*60)
    print(f"Total UFC fighters: {len(fighters_ufc)}")
    print(f"Database saved to: fighters_ufc.json")
    print("="*60 + "\n")
    
    return fighters_ufc

if __name__ == '__main__':
    scrape_ufc_fighters()
