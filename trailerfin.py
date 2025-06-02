import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import argparse
from dotenv import load_dotenv
import urllib.parse
import time
import threading

try:
    import schedule
except ImportError:
    schedule = None

load_dotenv()

base_path = os.getenv("SCAN_PATH")
video_filename = os.getenv("VIDEO_FILENAME")
schedule_days = int(os.getenv("SCHEDULE_DAYS", 7))
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.imdb.com/',
    'Connection': 'keep-alive',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1',
}



def get_trailer_video_page_url(imdb_id):
    url = f"https://www.imdb.com/title/{imdb_id}/videogallery/?sort=date,asc"
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            print(f"Failed to fetch trailers for {imdb_id} (status {response.status_code})")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        trailer_links = soup.find_all('a', href=re.compile(r'/video/vi\\d+'))
        if not trailer_links:
            # Broader match: any link containing '/video/vi'
            trailer_links = soup.find_all('a', href=lambda x: x and '/video/vi' in x)
        for link in trailer_links:
            if 'trailer' in link.get_text(strip=True).lower():
                video_page_url = f"https://www.imdb.com{link['href']}"
                return video_page_url
        # If no trailer found, grab the first video
        if trailer_links:
            video_page_url = f"https://www.imdb.com{trailer_links[0]['href']}"
            return video_page_url
        print(f"No video found for {imdb_id}")
        return None
    except Exception as e:
        print(f"Error fetching trailers for {imdb_id}: {e}")
        return None

def get_direct_video_url_from_page(video_page_url):
    try:
        response = requests.get(video_page_url, headers=headers, timeout=20)
        if response.status_code != 200:
            print(f"Failed to fetch video page: {video_page_url} (status {response.status_code})")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__', type='application/json')
        if not script_tag:
            print(f"No __NEXT_DATA__ script tag found on page: {video_page_url}")
            return None
        import json
        data = json.loads(script_tag.string)
        playback_urls = data['props']['pageProps']['videoPlaybackData']['video']['playbackURLs']
        mp4_urls = [item for item in playback_urls if item.get('videoMimeType') == 'MP4']
        if mp4_urls:
            def quality_key(item):
                if '1080' in item.get('videoDefinition', ''):
                    return 3
                if '720' in item.get('videoDefinition', ''):
                    return 2
                if '480' in item.get('videoDefinition', ''):
                    return 1
                return 0
            best = sorted(mp4_urls, key=quality_key, reverse=True)[0]
            return best['url'] + '#t=8'
        if playback_urls:
            return playback_urls[0]['url'] + '#t=8'
        print(f"No playback URLs found in JSON on page: {video_page_url}")
        return None
    except Exception as e:
        print(f"Error parsing playback URLs from JSON: {e}")
        return None

def create_or_update_strm_file(folder_path, video_url):
    backdrops_path = os.path.join(folder_path, "backdrops")
    os.makedirs(backdrops_path, exist_ok=True)
    strm_path = os.path.join(backdrops_path, video_filename)
    with open(strm_path, "w") as f:
        f.write(video_url)
    print(f"Updated {strm_path}")

def is_strm_expired(strm_path):
    if not os.path.exists(strm_path):
        return True
    try:
        with open(strm_path, 'r') as f:
            url = f.read().strip()
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        expires_list = query.get('Expires')
        if not expires_list:
            return True
        expires = int(expires_list[0])
        import time
        now = int(time.time())
        return now >= expires
    except Exception as e:
        print(f"Error checking expiration for {strm_path}: {e}")
        return True

def scan_and_refresh_trailers(scan_path=None):
    path_to_scan = scan_path if scan_path else base_path
    if not os.path.exists(path_to_scan):
        print(f"Provided path does not exist: {path_to_scan}")
        return
    for root, dirs, files in os.walk(path_to_scan):
        match = re.search(r'\{imdb-(tt\d+)\}', root)
        if match:
            if not root.rstrip(os.sep).endswith(f'{{imdb-{match.group(1)}}}'): 
                continue
            imdb_id = match.group(1)
            backdrops_path = os.path.join(root, "backdrops")
            strm_path = os.path.join(backdrops_path, video_filename)
            if not is_strm_expired(strm_path):
                print(f"[{datetime.now()}] Trailer link still valid for {imdb_id} in {root}")
                continue
            print(f"[{datetime.now()}] Refreshing trailer for {imdb_id} in {root}")
            video_page_url = get_trailer_video_page_url(imdb_id)
            if video_page_url:
                video_url = get_direct_video_url_from_page(video_page_url)
                if video_url:
                    create_or_update_strm_file(root, video_url)

def run_scheduler(scan_path=None):
    if not schedule:
        print("schedule module not installed. Please install with 'pip install schedule'.")
        return
    def job():
        scan_and_refresh_trailers(scan_path)
    schedule.every(schedule_days).days.do(job)
    print(f"Scheduler started. Running every {schedule_days} day(s).")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan and refresh IMDb trailers.")
    parser.add_argument('--dir', type=str, help='Directory to scan (defaults to /mnt/plex)')
    parser.add_argument('--schedule', action='store_true', help='Run as a weekly scheduled job')
    args = parser.parse_args()
    if args.schedule:
        run_scheduler(args.dir)
    else:
        scan_and_refresh_trailers(args.dir)
