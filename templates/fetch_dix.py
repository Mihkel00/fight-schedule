"""
DIX (Dark Index) Calculation Script

Downloads FINRA short sale volume data and calculates the Dark Index
for S&P 500 components weighted by market cap.
"""

import pandas as pd
import requests
from datetime import datetime, timedelta
import sqlite3
import time

def download_finra_data(date):
    """
    Download FINRA short sale volume data for a specific date.
    
    Args:
        date: datetime object for the trading date
    
    Returns:
        DataFrame with short sale volume data
    """
    date_str = date.strftime('%Y%m%d')
    
    # FINRA publishes data with T+1 delay
    url = f"https://api.finra.org/data/group/otcMarket/name/consolidatedShortVolume"
    
    # Try alternative direct download approach
    # FINRA data is at: http://regsho.finra.org/CNMSshvol{YYYYMMDD}.txt
    url = f"http://regsho.finra.org/CNMSshvol{date_str}.txt"
    
    print(f"Downloading FINRA data for {date_str}...")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Parse pipe-delimited file
        from io import StringIO
        df = pd.read_csv(StringIO(response.text), sep='|')
        
        print(f"Downloaded {len(df)} records")
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Error downloading data: {e}")
        return None


def get_sp500_market_caps():
    """
    Get current S&P 500 components and their market caps using yfinance.
    
    Returns:
        Dictionary of {ticker: market_cap}
    """
    import yfinance as yf
    
    print("Fetching S&P 500 market caps...")
    
    # S&P 500 tickers - simplified list for MVP
    # Full list: https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
    sp500_tickers = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK.B',
        'JPM', 'JNJ', 'V', 'PG', 'XOM', 'UNH', 'HD', 'MA', 'BAC', 'ABBV',
        'PFE', 'COST', 'DIS', 'AVGO', 'MRK', 'CRM', 'KO', 'CSCO', 'PEP',
        'TMO', 'ACN', 'ADBE', 'WMT', 'NFLX', 'ABT', 'LIN', 'NKE', 'DHR',
        'VZ', 'ORCL', 'CMCSA', 'AMD', 'TXN', 'QCOM', 'PM', 'NEE', 'HON'
        # Add remaining tickers as needed - using top 45 for MVP
    ]
    
    market_caps = {}
    
    for ticker in sp500_tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            market_cap = info.get('marketCap', 0)
            
            if market_cap > 0:
                market_caps[ticker] = market_cap
                
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            continue
    
    print(f"Loaded {len(market_caps)} S&P 500 components")
    return market_caps


def calculate_dpi(short_volume, total_volume):
    """
    Calculate Dark Pool Indicator (DPI) for a single stock.
    
    DPI = 1 - (ShortVolume / TotalVolume)
    
    High DPI = more buying (market makers shorting to provide liquidity)
    Low DPI = more selling
    """
    if total_volume == 0:
        return 0
    return 1 - (short_volume / total_volume)


def calculate_dix(df, market_caps):
    """
    Calculate the Dark Index (DIX) - market cap weighted average of DPIs.
    
    Args:
        df: DataFrame with FINRA short sale data
        market_caps: Dictionary of {ticker: market_cap}
    
    Returns:
        DIX value (float between 0 and 1)
    """
    # Filter for TRF market (dark pools only)
    dark_pool_data = df[df['Market'] == 'TRF'].copy()
    
    # Calculate DPI for each stock
    dark_pool_data['DPI'] = dark_pool_data.apply(
        lambda row: calculate_dpi(row['ShortVolume'], row['TotalVolume']),
        axis=1
    )
    
    # Filter for S&P 500 components only
    sp500_tickers = set(market_caps.keys())
    dark_pool_data = dark_pool_data[dark_pool_data['Symbol'].isin(sp500_tickers)]
    
    # Add market caps
    dark_pool_data['MarketCap'] = dark_pool_data['Symbol'].map(market_caps)
    
    # Remove any missing market caps
    dark_pool_data = dark_pool_data.dropna(subset=['MarketCap'])
    
    # Calculate weighted DIX
    total_market_cap = dark_pool_data['MarketCap'].sum()
    
    if total_market_cap == 0:
        return None
    
    dix = (dark_pool_data['DPI'] * dark_pool_data['MarketCap']).sum() / total_market_cap
    
    print(f"Calculated DIX: {dix:.4f} from {len(dark_pool_data)} stocks")
    
    return dix


def store_dix(date, dix_value, db_path='data/market_data.db'):
    """
    Store DIX value in SQLite database.
    
    Args:
        date: datetime object
        dix_value: calculated DIX (float)
        db_path: path to SQLite database
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_data (
            date DATE PRIMARY KEY,
            dix REAL,
            gex REAL,
            spx_close REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert or update DIX value
    cursor.execute('''
        INSERT INTO market_data (date, dix)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET dix = excluded.dix
    ''', (date.strftime('%Y-%m-%d'), dix_value))
    
    conn.commit()
    conn.close()
    
    print(f"Stored DIX value for {date.strftime('%Y-%m-%d')}")


def main():
    """
    Main function to fetch and calculate DIX for yesterday (T+1 delay).
    """
    # FINRA data is published T+1, so fetch yesterday's data
    yesterday = datetime.now() - timedelta(days=1)
    
    # Skip weekends
    while yesterday.weekday() >= 5:  # 5=Saturday, 6=Sunday
        yesterday -= timedelta(days=1)
    
    print(f"Calculating DIX for {yesterday.strftime('%Y-%m-%d')}")
    
    # Step 1: Download FINRA data
    finra_data = download_finra_data(yesterday)
    
    if finra_data is None:
        print("Failed to download FINRA data. Exiting.")
        return
    
    # Step 2: Get S&P 500 market caps
    market_caps = get_sp500_market_caps()
    
    # Step 3: Calculate DIX
    dix = calculate_dix(finra_data, market_caps)
    
    if dix is None:
        print("Failed to calculate DIX. Exiting.")
        return
    
    # Step 4: Store in database
    store_dix(yesterday, dix)
    
    print(f"✓ DIX calculation complete: {dix:.4f}")


if __name__ == "__main__":
    main()
