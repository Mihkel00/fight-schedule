"""
Scrapers Package
Contains all event scraping modules for different fight sources
"""

from .ufc_scraper import scrape_ufc, scrape_ufc_events
from .boxing_scraper import scrape_boxing, scrape_boxing_events

__all__ = ['scrape_ufc', 'scrape_ufc_events', 'scrape_boxing', 'scrape_boxing_events']
