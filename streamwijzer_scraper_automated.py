import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import time

# ============================================================================
# CONFIGURATIE
# ============================================================================

STREAMWIJZER_URL = "https://www.streamwijzer.nl/nieuws/"
FILMVANDAAG_URL = "https://www.filmvandaag.nl/nieuws/populair"
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://hook.eu1.make.com/wbq45srdf6qr7r7bqi7x4v7381s6j0to')
SEEN_ARTICLES_FILE = "seen_articles.json"

# Maximum aantal artikelen per bron
MAX_ARTICLES_PER_SOURCE = 10

# ============================================================================
# SCHEDULED TIMES
# ============================================================================

def get_scheduled_times():
    """
    Genereer dynamische scheduled times op basis van vandaag.
    Artikelen worden verspreid over vandaag en morgen.
    """
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    
    scheduled_times = [
        today.strftime("%Y-%m-%d") + " 19:30:00",
        today.strftime("%Y-%m-%d") + " 20:45:00",
        tomorrow.strftime("%Y-%m-%d") + " 10:30:00",
        tomorrow.strftime("%Y-%m-%d") + " 11:45:00",
        tomorrow.strftime("%Y-%m-%d") + " 12:30:00",
        tomorrow.strftime("%Y-%m-%d") + " 14:00:00",
        tomorrow.strftime("%Y-%m-%d") + " 15:30:00",
        tomorrow.strftime("%Y-%m-%d") + " 17:00:00",
        tomorrow.strftime("%Y-%m-%d") + " 18:30:00",
        tomorrow.strftime("%Y-%m-%d") + " 20:00:00"
    ]
    
    return scheduled_times

# ============================================================================
# ARTIKEL TRACKING
# ============================================================================

def load_seen_articles():
    """Laad eerder geziene artikelen uit JSON bestand"""
    if Path(SEEN_ARTICLES_FILE).exists():
        try:
            with open(SEEN_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"✅ Geladen: {len(data.get('streamwijzer', []))} Streamwijzer + {len(data.get('filmvandaag', []))} FilmVandaag artikelen")
                return data
        except Exception as e:
            print(f"⚠️ Fout bij laden seen_articles.json: {e}")
    return {'streamwijzer': [], 'filmvandaag': []}

def save_seen_articles(seen_articles):
    """Sla geziene artikelen op in JSON bestand"""
    try:
        with open(SEEN_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(seen_articles, f, ensure_ascii=False, indent=2)
        print(f"💾 Opgeslagen: {len(seen_articles.get('streamwijzer', []))} Streamwijzer + {len(seen_articles.get('filmvandaag', []))} FilmVandaag artikelen")
    except Exception as e:
        print(f"❌ Fout bij opslaan: {e}")

# ============================================================================
# CONTENT EXTRACTION
# ============================================================================

def get_article_content(article_url, headers):
    """Scrape de volledige artikel content van de pagina"""
    try:
        print(f"  → Ophalen content van: {article_url[:60]}...")
        response = requests.get(article_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        content_text = ''
        
        # Strategie 1: WordPress/Streamwijzer content div
        content_div = (
            soup.find('div', class_='td-post-content') or
            soup.find('div', class_='entry-content') or
            soup.find('article', class_='post') or
            soup.find('div', class_='post-content') or
            soup.find('div', class_='article')
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
        print(f"  ✗ Fout bij ophalen content: {e}")
        return 'Geen content beschikbaar'

# ============================================================================
# STREAMWIJZER SCRAPING
# ============================================================================

def scrape_streamwijzer():
    """Scrape nieuwste artikelen van Streamwijzer"""
    try:
        print(f"\n🔍 Scraping Streamwijzer: {STREAMWIJZER_URL}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(STREAMWIJZER_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        
        article_items = soup.select('li.article-item')
        print(f"📊 Gevonden: {len(article_items)} artikelen op Streamwijzer")
        
        for item in article_items[:MAX_ARTICLES_PER_SOURCE]:
            try:
                link_tag = item.select_one('a')
                if not link_tag:
                    continue
                
                url = link_tag.get('href', '')
                if not url.startswith('http'):
                    url = f"https://www.streamwijzer.nl{url}"
                
                title = link_tag.get('title', '').strip()
                if not title:
                    title_tag = item.select_one('h3')
                    title = title_tag.text.strip() if title_tag else 'Geen titel'
                
                img_tag = item.select_one('img')
                img_url = img_tag.get('src', '') if img_tag else ''
                if img_url and not img_url.startswith('http'):
                    img_url = f"https://www.streamwijzer.nl{img_url}"
                
                # Haal datum op
                date_tag = item.select_one('time')
                date_str = date_tag.get('datetime', '') if date_tag else datetime.now().strftime('%Y-%m-%d')
                
                # Haal artikel content op
                excerpt = get_article_content(url, headers)
                
                if url and title:
                    articles.append({
                        'source': 'Streamwijzer',
                        'title': title,
                        'url': url,
                        'image_url': img_url,
                        'excerpt': excerpt,
                        'date': date_str,
                        'scraped_at': datetime.now().isoformat()
                    })
                    print(f"✓ Verwerkt: {title[:60]}...")
                
                # Kleine pauze tussen artikel requests
                time.sleep(0.5)
                
            except Exception as e:
                print(f"⚠️ Fout bij verwerken Streamwijzer artikel: {e}")
                continue
        
        print(f"✅ Verwerkt: {len(articles)} Streamwijzer artikelen")
        return articles
    
    except Exception as e:
        print(f"❌ Fout bij scrapen Streamwijzer: {e}")
        return []

# ============================================================================
# FILMVANDAAG SCRAPING
# ============================================================================

def scrape_filmvandaag():
    """Scrape meest gelezen artikelen van FilmVandaag"""
    try:
        print(f"\n🔍 Scraping FilmVandaag: {FILMVANDAAG_URL}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(FILMVANDAAG_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = []
        
        # Zoek naar de artikel lijst items
        article_items = soup.select('ul.article-list li')
        print(f"📊 Gevonden: {len(article_items)} artikelen op FilmVandaag")
        
        for item in article_items[:MAX_ARTICLES_PER_SOURCE]:
            try:
                link_tag = item.select_one('a')
                if not link_tag:
                    continue
                
                url = link_tag.get('href', '')
                if not url.startswith('http'):
                    url = f"https://www.filmvandaag.nl{url}"
                
                # Titel uit h4 tag
                title_tag = item.select_one('h4')
                if title_tag:
                    # Verwijder de kleine datum/tijd tekst
                    small_tag = title_tag.select_one('small')
                    if small_tag:
                        small_tag.decompose()
                    title = title_tag.text.strip()
                else:
                    title = 'Geen titel'
                
                # Haal de grote artikel-afbeelding op van de artikel pagina
                img_url = ''
                try:
                    article_response = requests.get(url, headers=headers, timeout=10)
                    article_response.raise_for_status()
                    article_soup = BeautifulSoup(article_response.content, 'html.parser')
                    
                    # Zoek naar de grote artikel afbeelding met class 'article-image'
                    article_img = article_soup.select_one('img.article-image')
                    if article_img:
                        img_url = article_img.get('src', '')
                        # Gebruik de hoogste kwaliteit zonder parameters
                        if '?' in img_url:
                            img_url = img_url.split('?')[0]
                        if not img_url.startswith('http'):
                            img_url = f"https://static.filmvandaag.nl{img_url}"
                        print(f"  ✓ Grote afbeelding gevonden: {img_url[:60]}...")
                    
                    # Haal ook meteen de content op (we zijn toch al op de pagina)
                    excerpt = ''
                    content_div = (
                        article_soup.find('div', class_='article') or
                        article_soup.find('div', class_='td-post-content')
                    )
                    if content_div:
                        paragraphs = content_div.find_all('p')
                        if paragraphs:
                            excerpt = '\n\n'.join([p.get_text(strip=True) for p in paragraphs[:10] if p.get_text(strip=True)])
                            if len(excerpt) > 5000:
                                excerpt = excerpt[:5000] + '...'
                    
                    if not excerpt:
                        og_desc = article_soup.find('meta', property='og:description')
                        if og_desc and og_desc.get('content'):
                            excerpt = og_desc.get('content')
                    
                    excerpt = excerpt if excerpt else 'Geen content beschikbaar'
                    
                except Exception as e:
                    print(f"  ⚠️ Kon artikel pagina niet ophalen: {e}")
                    # Fallback naar kleine afbeelding uit lijst
                    img_tag = item.select_one('img')
                    if img_tag:
                        img_url = img_tag.get('src', '') or img_tag.get('data-original', '')
                        if img_url and not img_url.startswith('http'):
                            img_url = f"https://static.filmvandaag.nl{img_url}"
                    excerpt = 'Geen content beschikbaar'
                
                if url and title:
                    articles.append({
                        'source': 'FilmVandaag',
                        'title': title,
                        'url': url,
                        'image_url': img_url,
                        'excerpt': excerpt,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'scraped_at': datetime.now().isoformat()
                    })
                    print(f"✓ Verwerkt: {title[:60]}...")
                
                # Pauze tussen artikel requests (al op de detail pagina geweest)
                time.sleep(1)
                
            except Exception as e:
                print(f"⚠️ Fout bij verwerken FilmVandaag artikel: {e}")
                continue
        
        print(f"✅ Verwerkt: {len(articles)} FilmVandaag artikelen")
        return articles
    
    except Exception as e:
        print(f"❌ Fout bij scrapen FilmVandaag: {e}")
        return []

# ============================================================================
# WEBHOOK COMMUNICATIE
# ============================================================================

def send_to_webhook_batch(articles, source_name):
    """Verstuur alle artikelen van een bron in 1 batch naar webhook"""
    if not WEBHOOK_URL:
        print("⚠️ Geen webhook URL geconfigureerd")
        return False
    
    if not articles:
        print(f"Geen {source_name} artikelen om te versturen")
        return True
    
    try:
        # Genereer scheduled times
        scheduled_times = get_scheduled_times()
        
        # Voeg scheduled_time toe aan elk artikel
        for i, article in enumerate(articles):
            scheduled_time_index = i if i < len(scheduled_times) else len(scheduled_times) - 1
            article['scheduled_time'] = scheduled_times[scheduled_time_index]
        
        payload = {
            'articles': articles,
            'total': len(articles),
            'source': source_name,
            'scraped_at': datetime.now().isoformat()
        }
        
        print(f"\n📤 Verzenden naar webhook...")
        print(f"   Bron: {source_name}")
        print(f"   Artikelen: {len(articles)}")
        print(f"   URL: {WEBHOOK_URL}")
        
        response = requests.post(WEBHOOK_URL, json=payload, timeout=30)
        
        print(f"   Status: {response.status_code}")
        
        response.raise_for_status()
        
        print(f"\n{'='*60}")
        print(f"✅ SUCCESVOL: {len(articles)} {source_name} artikelen verzonden")
        print(f"{'='*60}")
        
        for i, article in enumerate(articles, 1):
            print(f"  {i}. {article['title'][:70]}...")
            print(f"     📅 Scheduled: {article['scheduled_time']}")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ Fout bij verzenden naar webhook: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# MAIN FUNCTIE
# ============================================================================

def main():
    print("\n" + "=" * 60)
    print("🚀 Streamwijzer & FilmVandaag Scraper - Geautomatiseerd")
    print(f"⏰ Starttijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Laad eerder geziene artikelen
    seen_articles = load_seen_articles()
    
    # Scrape beide bronnen
    print("\n" + "=" * 60)
    print("FASE 1: SCRAPING")
    print("=" * 60)
    
    streamwijzer_articles = scrape_streamwijzer()
    time.sleep(2)  # Wees beleefd naar de servers
    filmvandaag_articles = scrape_filmvandaag()
    
    all_articles = {
        'streamwijzer': streamwijzer_articles,
        'filmvandaag': filmvandaag_articles
    }
    
    # Verwerk nieuwe artikelen
    print("\n" + "=" * 60)
    print("FASE 2: FILTEREN & VERZENDEN")
    print("=" * 60)
    
    total_new_articles = 0
    
    for source, articles in all_articles.items():
        print(f"\n📝 Verwerken {source.capitalize()}...")
        seen_list = seen_articles.get(source, [])
        
        # Filter nieuwe artikelen
        new_articles = [a for a in articles if a['url'] not in seen_list]
        
        print(f"   Totaal gevonden: {len(articles)}")
        print(f"   Nieuw: {len(new_articles)}")
        print(f"   Al gezien: {len(articles) - len(new_articles)}")
        
        if new_articles:
            # Verzend alle nieuwe artikelen in 1 batch
            if send_to_webhook_batch(new_articles, source):
                # Voeg URLs toe aan gezien lijst
                for article in new_articles:
                    seen_list.append(article['url'])
                total_new_articles += len(new_articles)
            else:
                print(f"❌ Fout bij verzenden {source} artikelen")
        else:
            print(f"   ℹ️ Geen nieuwe {source} artikelen")
        
        seen_articles[source] = seen_list
    
    # Sla bijgewerkte lijst op
    save_seen_articles(seen_articles)
    
    # Samenvatting
    print("\n" + "=" * 60)
    print("📊 SAMENVATTING")
    print("=" * 60)
    print(f"🆕 Nieuwe artikelen verzonden: {total_new_articles}")
    print(f"📚 Totaal gevolgd (Streamwijzer): {len(seen_articles.get('streamwijzer', []))}")
    print(f"📚 Totaal gevolgd (FilmVandaag): {len(seen_articles.get('filmvandaag', []))}")
    print(f"⏰ Eindtijd: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Script gestopt door gebruiker")
    except Exception as e:
        print(f"\n❌ ONVERWACHTE FOUT: {e}")
        import traceback
        traceback.print_exc()
