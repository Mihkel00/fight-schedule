"""
Cloudflare R2 Storage Helper
Handles fighter image uploads to R2 bucket
"""

import boto3
import os
from botocore.client import Config

# R2 credentials from environment
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID')
R2_BUCKET = os.getenv('R2_BUCKET_NAME', 'fightschedule-fighters')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL')

# Initialize R2 client
s3_client = None
if R2_ACCESS_KEY and R2_SECRET_KEY and R2_ACCOUNT_ID:
    s3_client = boto3.client(
        's3',
        endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto'
    )


def upload_fighter_image(file_data, filename):
    """
    Upload fighter image to R2
    
    Args:
        file_data: File bytes or file object
        filename: Target filename (e.g., 'conor-mcgregor.png')
    
    Returns:
        str: Public URL of uploaded image, or None on failure
    """
    if not s3_client:
        print("R2 not configured - falling back to local storage")
        return None
    
    try:
        # Upload to R2
        s3_client.put_object(
            Bucket=R2_BUCKET,
            Key=f'fighters/{filename}',
            Body=file_data,
            ContentType='image/png'
        )
        
        # Return public URL
        if R2_PUBLIC_URL:
            public_url = f'{R2_PUBLIC_URL}/fighters/{filename}'
        else:
            public_url = f'https://pub-{R2_ACCOUNT_ID}.r2.dev/fighters/{filename}'
        print(f"✓ Uploaded to R2: {public_url}")
        return public_url
        
    except Exception as e:
        print(f"R2 upload failed: {e}")
        return None


def get_fighter_image_url(filename):
    """
    Get public URL for fighter image
    
    Args:
        filename: Fighter image filename
    
    Returns:
        str: Public URL or local path fallback
    """
    if R2_PUBLIC_URL:
        return f'{R2_PUBLIC_URL}/fighters/{filename}'
    elif R2_ACCOUNT_ID:
        return f'https://pub-{R2_ACCOUNT_ID}.r2.dev/fighters/{filename}'
    else:
        return f'/static/fighters/{filename}'


def is_r2_enabled():
    """Check if R2 is properly configured"""
    return bool(s3_client)
