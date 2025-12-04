"""
Pre-generate AI previews on deployment to avoid slow page loads
"""
import sys
import os
from app import fetch_fights, get_or_generate_preview, is_big_name_fight, logger

def generate_all_previews():
    """Generate previews for featured and main card fights"""
    logger.info("=" * 60)
    logger.info("PRE-GENERATING AI PREVIEWS")
    logger.info("=" * 60)
    
    try:
        fights = fetch_fights()
        
        # Separate by sport, filter out prelims
        ufc_fights = [f for f in fights if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims']
        boxing_fights = [f for f in fights if f.get('sport') == 'Boxing']
        
        # Get featured fights
        featured = []
        
        # UFC Featured: Next title fight OR first UFC event
        ufc_featured = None
        for fight in ufc_fights:
            if fight.get('weight_class') == 'Title':
                ufc_featured = fight
                break
        if not ufc_featured and ufc_fights:
            ufc_featured = ufc_fights[0]
        if ufc_featured:
            featured.append(ufc_featured)
        
        # Boxing Featured: Next big-name fight
        for fight in boxing_fights:
            if is_big_name_fight(fight):
                featured.append(fight)
                break
        
        # Generate previews for featured + first 10 fights from each sport
        to_generate = featured + ufc_fights[:10] + boxing_fights[:10]
        
        generated = 0
        skipped = 0
        
        for fight in to_generate:
            try:
                # Create preview ID
                if fight.get('sport') == 'UFC':
                    preview_id = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
                else:
                    fighter1_slug = fight['fighter1'].lower().replace(' ', '-')
                    fighter2_slug = fight['fighter2'].lower().replace(' ', '-')
                    preview_id = f"boxing_{fighter1_slug}_{fighter2_slug}_{fight['date']}"
                
                # Generate preview
                is_title = fight.get('weight_class') == 'Title'
                preview = get_or_generate_preview(
                    preview_id=preview_id,
                    fighter1=fight['fighter1'],
                    fighter2=fight['fighter2'],
                    sport=fight['sport'],
                    is_title=is_title,
                    weight_class=fight.get('weight_class')
                )
                
                if preview:
                    if preview.get('generated_at'):
                        # Check if just generated (within last minute)
                        from datetime import datetime, timedelta
                        gen_time = datetime.fromisoformat(preview['generated_at'])
                        if datetime.now() - gen_time < timedelta(minutes=1):
                            generated += 1
                            logger.info(f"  ✓ Generated: {fight['fighter1']} vs {fight['fighter2']}")
                        else:
                            skipped += 1
                            logger.info(f"  ↻ Cached: {fight['fighter1']} vs {fight['fighter2']}")
                else:
                    logger.warning(f"  ✗ Failed: {fight['fighter1']} vs {fight['fighter2']}")
                    
            except Exception as e:
                logger.error(f"  ✗ Error generating preview: {e}")
                continue
        
        logger.info("=" * 60)
        logger.info(f"PREVIEW GENERATION COMPLETE")
        logger.info(f"  Generated: {generated}")
        logger.info(f"  Cached: {skipped}")
        logger.info(f"  Total: {generated + skipped}")
        logger.info("=" * 60)
        
        return generated + skipped > 0
        
    except Exception as e:
        logger.error(f"Preview generation failed: {e}")
        return False

if __name__ == "__main__":
    success = generate_all_previews()
    sys.exit(0 if success else 1)
