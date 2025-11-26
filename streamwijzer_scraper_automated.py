import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import os
import time
import sys

# ============================================================================
# CONFIGURATIE
# ============================================================================

# Haal webhook URL uit environment variable (VERPLICHT voor cloud deployments)
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://hook.eu1.make.com/wbq45srdf6qr7r7bqi7x4v7381s6j0to')
WEBSITE_URL = "https://www.streamwijzer.nl/nieuws/"
SEEN_ARTICLES_FILE = "seen_articles.json"

# Maximum aantal artikelen om per run te versturen
MAX_ARTICLES_PER_RUN = 5

# ============================================================================
# ARTIKEL TRACKING
# ============================================================================

def load_seen_articles():
    """Laad eerder geziene artikelen"""
    if os.path.exists(SEEN_ARTICLES_FILE):
        try:
            with open(SEEN_ARTICLES_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"⚠️  Waarschuwing: seen_articles.json is corrupt, wordt opnieuw aangemaakt")
            print(f"   Error: {e}")
            if os.path.exists(SEEN_ARTICLES_FILE):
                backup_name = f"{SEEN_ARTICLES_FILE}.backup.{int(time.time())}"
                os.rename(SEEN_ARTICLES_FILE, backup_name)
                print(f"   Backup opgeslagen als: {backup_name}")
            return []
        except Exception as e:
            print(f"⚠️  Fout bij lezen seen_articles.json: {e}")
            return []
    return []

def save_seen_articles(articles):
    """Sla geziene artikelen op"""
    try:
        with open(SEEN_ARTICLES_FILE, 'w') as f:
            json.dump(articles, f, indent=2)
        print(f"✓ Opgeslagen: {len(articles)} geziene artikelen")
    except Exception as e:
        print(f"✗ Fout bij opslaan seen_articles.json: {e}")

def is_article_recent(article_date_str, hours=24):
    """Check of artikel binnen de laatste X uren is gepubliceerd"""
    try:
        # Probeer verschillende datum formaten
        for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d']:
            try:
                article_date = datetime.strptime(article_date_str, fmt)
                cutoff_date = datetime.now() - timedelta(hours=hours)
                return article_date >= cutoff_date
            except ValueError:
                continue
        
        # Als geen formaat werkt, accepteer het artikel
        print(f"  ⚠️  Kon datum niet parsen: {article_date_str}, accepteer artikel")
        return True
    except Exception as e:
        print(f"  ⚠️  Fout bij datum check: {e}, accepteer artikel")
        return True

# ============================================================================
# SCRAPING FUNCTIES
# ============================================================================

def get_article_content(article_url, headers):
    """Scrape de volledige artikel content van de pagina"""
    try:
        print(f"  → Ophalen artikel content van: {article_url}")
        response = requests.get(article_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        content_text = ''
        
        # Strategie 1: WordPress/Streamwijzer content div
        content_div = (
            soup.find('div', class_='td-post-content') or
            soup.find('div', class_='entry-content') or
            soup.find('article', class_='post') or
            soup.find('div', class_='post-content')
        )
        
        if content_div:
            # Verwijder ongewenste elementen
            for unwanted in content_div.find_all(['script', 'style', 'iframe', 'aside', 'nav']):
                unwanted.decompose()
            
            # Haal alle paragrafen op
            paragraphs = content_div.find_all('p')
            if paragraphs:
                # Neem de eerste 10 paragrafen voor voldoende context
                content_text = '\n\n'.join([p.get_text(strip=True) for p in paragraphs[:10] if p.get_text(strip=True)])
                print(f"  ✓ Content opgehaald: {len(content_text)} karakters")
            
            # Als geen paragrafen, pak alle tekst
            if not content_text:
                content_text = content_div.get_text(strip=True)
                print(f"  ✓ Content (algemeen) opgehaald: {len(content_text)} karakters")
        
        # Strategie 2: Open Graph description als fallback
        if not content_text or len(content_text) < 100:
            og_desc = soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                content_text = og_desc.get('content')
                print(f"  ✓ Open Graph description gebruikt: {len(content_text)} karakters")
        
        # Limiteer tot 5000 karakters voor OpenAI
        if len(content_text) > 5000:
            content_text = content_text[:5000] + '...'
        
        return content_text if content_text else 'Geen content beschikbaar'
        
    except Exception as e:
        print(f"  ✗ Fout bij ophalen artikel content: {e}")
        return ''

def get_featured_image_from_article(article_url, headers):
    """Scrape de artikel pagina zelf om de featured image te vinden"""
    try:
        print(f"  → Ophalen featured image van: {article_url}")
        response = requests.get(article_url, headers=headers, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Strategie 1: Open Graph image
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            content = og_image.get('content')
            print(f"  ✓ Open Graph image gevonden")
            return content
        
        # Strategie 2: Streamwijzer specifieke featured image div
        featured_div = soup.find('div', class_='td-post-featured-image')
        if featured_div:
            img = featured_div.find('img', src=True)
            if img:
                if img.get('srcset'):
                    srcset = img.get('srcset', '')
                    srcset_parts = srcset.split(',')
                    if srcset_parts:
                        image_url = srcset_parts[-1].strip().split()[0]
                        print(f"  ✓ Image van srcset gevonden")
                        return image_url
                src = img.get('src', '')
                if src:
                    print(f"  ✓ Image van src gevonden")
                    return src
        
        # Strategie 3: WordPress featured image
        img = soup.find('img', class_=lambda x: x and ('wp-post-image' in str(x) or 'featured' in str(x).lower()))
        if img and img.get('src'):
            print(f"  ✓ WordPress featured image gevonden")
            return img.get('src')
        
        # Strategie 4: Twitter card image
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            print(f"  ✓ Twitter card image gevonden")
            return twitter_image.get('content')
        
        print(f"  ✗ Geen afbeelding gevonden")
        return ''
    except Exception as e:
        print(f"  ✗ Fout bij ophalen featured image: {e}")
        return ''

def scrape_streamwijzer():
    """Scrape de nieuwspagina"""
    print(f"\n{'='*60}")
    print(f"Scraping {WEBSITE_URL}")
    print(f"{'='*60}\n")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(WEBSITE_URL, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"✗ Fout bij ophalen website: {e}")
        return []
    
    soup = BeautifulSoup(response.content, 'html.parser')
    articles = []
    seen_urls = set()
    
    # Zoek alle artikel containers
    article_containers = (
        soup.find_all('article') or 
        soup.find_all('div', class_=lambda x: x and 'post' in x.lower()) or
        soup.find_all('div', class_=lambda x: x and 'article' in x.lower())
    )
    
    print(f"Gevonden containers: {len(article_containers)}")
    print(f"Limiteer tot: {MAX_ARTICLES_PER_RUN} nieuwste artikelen\n")
    
    for container in article_containers[:MAX_ARTICLES_PER_RUN * 2]:  # Extra marge voor filtering
        try:
            # Probeer titel te vinden
            title_elem = (
                container.find('h2') or 
                container.find('h3') or 
                container.find('h1') or
                container.find(class_=lambda x: x and 'title' in str(x).lower())
            )
            
            # Probeer link te vinden
            link_elem = container.find('a', href=True)
            
            if not title_elem or not link_elem:
                continue
            
            # Maak complete URL
            url = link_elem['href'] if link_elem['href'].startswith('http') else f"https://www.streamwijzer.nl{link_elem['href']}"
            
            # Skip duplicaten
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Probeer datum te vinden
            date_elem = (
                container.find('time') or
                container.find(class_=lambda x: x and 'date' in str(x).lower())
            )
            date_str = date_elem.get_text(strip=True) if date_elem else datetime.now().strftime('%Y-%m-%d')
            
            # Check of artikel recent is (laatste 24 uur)
            # OPTIONEEL: Zet dit uit als je ALLE artikelen wilt, niet alleen recente
            # if not is_article_recent(date_str, hours=24):
            #     print(f"⊗ Skip (te oud): {title_elem.get_text(strip=True)[:50]}...")
            #     continue
            
            # Probeer afbeelding te vinden
            img_elem = container.find('img', src=True)
            image_url = ''
            
            if img_elem:
                if img_elem.get('srcset'):
                    srcset = img_elem.get('srcset', '')
                    srcset_parts = srcset.split(',')
                    if srcset_parts:
                        image_url = srcset_parts[-1].strip().split()[0]
                else:
                    image_url = img_elem.get('data-src') or img_elem.get('data-lazy-src') or img_elem.get('src', '')
            
            # Als geen image, haal van artikel pagina
            if not image_url and url:
                image_url = get_featured_image_from_article(url, headers)
            
            # Haal volledige artikel content op
            excerpt_text = ''
            if url:
                excerpt_text = get_article_content(url, headers)
            
            # Fallback: probeer excerpt van lijst pagina
            if not excerpt_text or len(excerpt_text) < 50:
                excerpt_elem = (
                    container.find('p') or
                    container.find(class_=lambda x: x and ('excerpt' in str(x).lower() or 'description' in str(x).lower()))
                )
                if excerpt_elem:
                    excerpt_text = excerpt_elem.get_text(strip=True)
            
            # Maak artikel object
            article = {
                'title': title_elem.get_text(strip=True),
                'url': url,
                'image_url': image_url if image_url and image_url.startswith('http') else f"https://www.streamwijzer.nl{image_url}" if image_url else '',
                'excerpt': excerpt_text if excerpt_text else 'Geen content beschikbaar. Check het artikel voor details.',
                'date': date_str,
                'scraped_at': datetime.now().isoformat()
            }
            
            articles.append(article)
            print(f"✓ Gevonden: {article['title'][:60]}...")
            
            # Stop als we genoeg artikelen hebben
            if len(articles) >= MAX_ARTICLES_PER_RUN:
                break
        
        except Exception as e:
            print(f"✗ Fout bij verwerken container: {e}")
            continue
    
    print(f"\n{'='*60}")
    print(f"Scraping voltooid: {len(articles)} artikelen gevonden")
    print(f"{'='*60}\n")
    
    return articles

# ============================================================================
# WEBHOOK COMMUNICATIE
# ============================================================================

def send_to_webhook_batch(articles):
    """Stuur alle artikelen in 1 batch naar Make.com webhook"""
    if not articles:
        print("Geen artikelen om te versturen")
        return True
    
    try:
        payload = {
            'articles': articles,
            'total': len(articles),
            'scraped_at': datetime.now().isoformat(),
            'source': 'automated_scraper'
        }
        
        print(f"Versturen naar Make.com webhook...")
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        print(f"\n{'='*60}")
        print(f"✓ SUCCESVOL VERZONDEN: {len(articles)} artikelen")
        print(f"{'='*60}\n")
        
        for i, article in enumerate(articles, 1):
            print(f"  {i}. {article['title'][:70]}...")
        
        print()
        return True
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 410:
            print(f"\n{'='*60}")
            print(f"✗ WEBHOOK ERROR (410): Webhook is verlopen")
            print(f"{'='*60}")
            print(f"Actie vereist:")
            print(f"1. Maak een nieuwe webhook in Make.com")
            print(f"2. Update WEBHOOK_URL environment variable")
            print()
        else:
            print(f"✗ HTTP error bij verzenden: {e}")
        return False
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Fout bij verzenden naar webhook: {e}")
        return False

# ============================================================================
# MAIN FUNCTIE
# ============================================================================

def main():
    """Hoofdfunctie - wordt aangeroepen door scheduler"""
    
    print("\n" + "="*60)
    print("STREAMWIJZER SCRAPER - AUTOMATED RUN")
    print(f"Start tijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    # Valideer webhook URL
    if not WEBHOOK_URL or WEBHOOK_URL == "HIER_JOUW_MAKE_WEBHOOK_URL":
        print("✗ ERROR: WEBHOOK_URL niet ingesteld!")
        print("\nActie vereist:")
        print("- Cloud: Stel WEBHOOK_URL environment variable in")
        print("- Lokaal: Pas het script aan met je webhook URL")
        sys.exit(1)
    
    # Laad eerder geziene artikelen
    seen_articles = load_seen_articles()
    seen_urls = [a['url'] for a in seen_articles]
    print(f"Geladen: {len(seen_articles)} eerder geziene artikelen\n")
    
    # Scrape nieuwe artikelen
    articles = scrape_streamwijzer()
    
    if not articles:
        print("✗ Geen artikelen gevonden")
        print("Mogelijke oorzaken:")
        print("- Website is offline")
        print("- Website structuur is veranderd")
        print("- CSS selectors moeten worden aangepast")
        sys.exit(1)
    
    # Filter nieuwe artikelen
    new_articles = [a for a in articles if a['url'] not in seen_urls]
    
    print(f"{'='*60}")
    print(f"RESULTATEN:")
    print(f"{'='*60}")
    print(f"Totaal gevonden:     {len(articles)}")
    print(f"Nieuwe artikelen:    {len(new_articles)}")
    print(f"Al gezien (skip):    {len(articles) - len(new_articles)}")
    print(f"{'='*60}\n")
    
    # Verzend nieuwe artikelen
    if new_articles:
        # Limiteer tot MAX_ARTICLES_PER_RUN
        articles_to_send = new_articles[:MAX_ARTICLES_PER_RUN]
        
        if len(new_articles) > MAX_ARTICLES_PER_RUN:
            print(f"⚠️  Limiteer tot {MAX_ARTICLES_PER_RUN} artikelen (van {len(new_articles)})")
            print(f"   Overige artikelen worden volgende run verwerkt\n")
        
        if send_to_webhook_batch(articles_to_send):
            # Markeer artikelen als gezien
            for article in articles_to_send:
                seen_articles.append({
                    'url': article['url'],
                    'title': article['title'],
                    'date': article['scraped_at']
                })
            
            save_seen_articles(seen_articles)
            
            print(f"{'='*60}")
            print(f"✓ KLAAR: {len(articles_to_send)} nieuwe artikelen verzonden")
            print(f"{'='*60}\n")
            sys.exit(0)
        else:
            print(f"{'='*60}")
            print(f"✗ FOUT: Artikelen NIET verzonden")
            print(f"{'='*60}\n")
            sys.exit(1)
    else:
        print(f"{'='*60}")
        print(f"✓ KLAAR: Geen nieuwe artikelen om te verzenden")
        print(f"{'='*60}\n")
        sys.exit(0)

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✗ Script gestopt door gebruiker")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ONVERWACHTE FOUT: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
